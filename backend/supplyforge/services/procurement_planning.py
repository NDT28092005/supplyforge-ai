"""Conservative replenishment and cash-flow planning from governed operating facts."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from django.utils import timezone

from supplyforge.models import (
    DecisionRecord, InventoryRecord, PaymentSchedule, ProcurementBudget,
    ProcurementPortfolioRun, PurchaseOrderLine, ReplenishmentPlan,
    SupplierSkuTerm, Workspace,
)
from supplyforge.services.temporal_feature_service import FeatureContractIncomplete, TemporalFeatureService


class ProcurementPlanningService:
    HORIZON_DAYS = 90
    MAX_PORTFOLIO_SKUS = 500

    @staticmethod
    def _latest_inventory(workspace_id: int, sku: str, warehouse_code: str = ''):
        """Resolve inventory only for an explicit, unambiguous warehouse."""
        qs = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id, canonical_sku=sku, as_of_verified=True,
        )
        if warehouse_code:
            return qs.filter(warehouse_code=warehouse_code).order_by(
                '-record_date', '-source_observed_at', '-id'
            ).first(), []
        # Evaluate the latest inventory snapshot, not every warehouse ever
        # seen for the SKU. Historical transfers otherwise turn a now
        # single-warehouse SKU into a false multi-warehouse ambiguity.
        latest_date = qs.order_by('-record_date').values_list('record_date', flat=True).first()
        rows = list(qs.filter(record_date=latest_date).only('id', 'warehouse_code').order_by('-source_observed_at', '-id')) if latest_date else []
        if not rows:
            return None, []
        warehouses = sorted({(row.warehouse_code or '').strip() or 'UNSPECIFIED' for row in rows})
        if len(warehouses) > 1:
            return None, warehouses
        return InventoryRecord.objects.get(id=rows[0].id), warehouses

    @staticmethod
    def _term(workspace_id: int, sku: str):
        today = timezone.localdate()
        return SupplierSkuTerm.objects.filter(
            supplier__workspace_id=workspace_id, supplier__is_active=True, canonical_sku=sku,
            effective_from__lte=today,
        ).filter(effective_to__isnull=True).order_by('-effective_from', '-id').first() or SupplierSkuTerm.objects.filter(
            supplier__workspace_id=workspace_id, supplier__is_active=True, canonical_sku=sku,
            effective_from__lte=today, effective_to__gte=today,
        ).order_by('-effective_from', '-id').first()

    @classmethod
    def plan_sku(
        cls, *, workspace_id: int, sku: str, horizon_days: int = HORIZON_DAYS,
        warehouse_code: str = '', persist: bool = True,
    ) -> dict:
        horizon_days = max(1, min(int(horizon_days), cls.HORIZON_DAYS))
        workspace = Workspace.objects.get(id=workspace_id)
        inventory, available_warehouses = cls._latest_inventory(workspace_id, sku, warehouse_code)
        term = cls._term(workspace_id, sku)
        missing = []
        if not inventory or inventory.available_quantity is None:
            missing.append(
                'Phạm vi kho cụ thể (SKU đang có ở nhiều kho)'
                if available_warehouses else 'Tồn kho khả dụng đã xác thực'
            )
        elif Decimal(inventory.available_quantity) < 0:
            missing.append('Số lượng tồn khả dụng hợp lệ')
        if not term:
            missing.append('Điều khoản nhà cung cấp')
        elif any(value is None or value <= 0 for value in (term.lead_time_days, term.moq, term.order_multiple, term.unit_cost)):
            missing.append('Lead time, MOQ, bội số đặt hàng hoặc giá mua')
        try:
            velocity = Decimal(str(TemporalFeatureService().extract_for_workspace(sku, workspace_id).values['sales_velocity_30d']))
        except FeatureContractIncomplete:
            velocity = None
            missing.append('Vận tốc bán đã quan sát')
        lineage = {
            'inventory_record_id': inventory.id if inventory else None,
            'warehouse_scope': warehouse_code or (available_warehouses[0] if len(available_warehouses) == 1 else None),
            'available_warehouses': available_warehouses,
            'supplier_term_id': term.id if term else None,
        }
        if missing or velocity is None:
            payload = {'status': 'DATA_UNAVAILABLE', 'sku': sku, 'missing_inputs': missing, 'lineage': lineage}
            if persist:
                ReplenishmentPlan.objects.create(workspace=workspace, sku=sku, horizon_days=horizon_days, status='DATA_UNAVAILABLE', missing_inputs_json=missing, input_lineage_json=lineage, forecast_json={})
            return payload
        on_hand = Decimal(inventory.available_quantity)
        open_lines = list(PurchaseOrderLine.objects.filter(
            canonical_sku=sku, purchase_order__workspace_id=workspace_id,
            purchase_order__status__in=['OPEN', 'PARTIALLY_RECEIVED'],
        ).select_related('purchase_order').prefetch_related('purchase_order__payment_schedules').order_by('purchase_order__expected_receipt_date', 'purchase_order_id'))
        open_po = sum(
            (max(Decimal('0'), Decimal(line.ordered_quantity) - Decimal(line.received_quantity)) for line in open_lines),
            Decimal('0'),
        )
        lead_days = int(term.lead_time_days)
        demand_during_lead = velocity * lead_days
        safety_stock = velocity * Decimal('7')
        proposed_arrival = timezone.localdate() + timedelta(days=lead_days)
        # An ETA is an observed PO field, not a promise that the supplier has
        # confirmed delivery.  The old API field is retained below only for
        # compatibility; new consumers must use the accurately named field.
        scheduled_before_arrival = Decimal('0')
        unconfirmed_open_po = Decimal('0')
        late_open_po = Decimal('0')
        open_po_details = []
        for line in open_lines:
            outstanding = max(Decimal('0'), Decimal(line.ordered_quantity) - Decimal(line.received_quantity))
            eta = line.purchase_order.expected_receipt_date
            timing = 'UNCONFIRMED'
            if eta:
                timing = 'BEFORE_REPLENISHMENT_ARRIVAL' if eta <= proposed_arrival else 'AFTER_REPLENISHMENT_ARRIVAL'
            if timing == 'BEFORE_REPLENISHMENT_ARRIVAL':
                scheduled_before_arrival += outstanding
            elif timing == 'AFTER_REPLENISHMENT_ARRIVAL':
                late_open_po += outstanding
            else:
                unconfirmed_open_po += outstanding
            open_po_details.append({
                'purchase_order_id': line.purchase_order_id,
                'po_number': line.purchase_order.po_number,
                'quantity': float(outstanding),
                'expected_receipt_date': eta.isoformat() if eta else None,
                'timing': timing,
                'receipt_date_status': 'SCHEDULED_NOT_CONFIRMED' if eta else 'UNKNOWN',
                'payment_schedule_status': 'KNOWN' if list(line.purchase_order.payment_schedules.all()) else 'UNKNOWN',
                'payment_schedule': [
                    {'due_date': schedule.due_date.isoformat(), 'amount': float(schedule.amount), 'status': schedule.status}
                    for schedule in line.purchase_order.payment_schedules.all()
                ],
            })

        stockout_days = int((on_hand / velocity).to_integral_value(rounding=ROUND_CEILING)) if velocity > 0 and on_hand > 0 else 0
        required = max(Decimal('0'), demand_during_lead + safety_stock - on_hand - scheduled_before_arrival)
        proposed_quantity = max(Decimal(term.moq), required) if required > 0 else Decimal('0')
        if proposed_quantity:
            multiple = Decimal(term.order_multiple)
            proposed_quantity = (proposed_quantity / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
        capital_required = proposed_quantity * Decimal(term.unit_cost)
        expected_stockout = timezone.localdate() + timedelta(days=stockout_days) if stockout_days is not None else None
        payload = {
            'status': 'READY', 'sku': sku, 'horizon_days': horizon_days,
            'observed_daily_velocity': float(velocity), 'on_hand_quantity': float(on_hand), 'open_purchase_order_quantity': float(open_po),
            'scheduled_before_replenishment_quantity': float(scheduled_before_arrival),
            # Deprecated name retained for existing clients. It must not be
            # labelled "confirmed" in merchant-facing copy.
            'confirmed_before_replenishment_quantity': float(scheduled_before_arrival),
            'late_open_purchase_order_quantity': float(late_open_po),
            'unconfirmed_open_purchase_order_quantity': float(unconfirmed_open_po),
            'proposed_receipt_date': proposed_arrival.isoformat(),
            'estimated_stockout_date': expected_stockout.isoformat() if expected_stockout else None,
            'lead_time_days': lead_days, 'safety_stock_quantity': float(safety_stock),
            'recommended_order_quantity': float(proposed_quantity), 'capital_required': float(capital_required),
            'recommendation': 'ORDER' if proposed_quantity > 0 else 'DEFER',
            'open_purchase_orders': open_po_details,
            'lineage': lineage,
        }
        if persist:
            ReplenishmentPlan.objects.create(workspace=workspace, sku=sku, supplier_term=term, horizon_days=horizon_days, status='READY', input_lineage_json=lineage, forecast_json=payload)
        return payload

    @staticmethod
    def _replenishment_skus(workspace_id: int) -> list[str]:
        """Return only workspace-scoped SKUs that have operational evidence.

        This intentionally does not scrape a mutable product catalogue: a SKU
        needs verified stock, a supplier term, or a current stop-buy decision
        before it is useful in a procurement review.
        """
        inventory_skus = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id, canonical_sku__gt='', as_of_verified=True,
        ).values_list('canonical_sku', flat=True)
        term_skus = SupplierSkuTerm.objects.filter(
            supplier__workspace_id=workspace_id, supplier__is_active=True,
        ).values_list('canonical_sku', flat=True)
        stop_skus = DecisionRecord.objects.filter(
            workspace_id=workspace_id,
            action_type='STOP_REPLENISHMENT',
            status__in=['GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW', 'REVIEWED', 'ACCEPTED'],
            assessment_run__status='COMPLETED', assessment_run__is_current=True,
        ).values_list('sku', flat=True)
        return sorted({str(sku).strip() for sku in [*inventory_skus, *term_skus, *stop_skus] if str(sku).strip()})

    @staticmethod
    def _current_stop_buy_decisions(workspace_id: int) -> dict[str, list[DecisionRecord]]:
        rows = DecisionRecord.objects.filter(
            workspace_id=workspace_id,
            action_type='STOP_REPLENISHMENT',
            status__in=['GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW', 'REVIEWED', 'ACCEPTED'],
            assessment_run__status='COMPLETED', assessment_run__is_current=True,
        ).select_related('assessment_run').order_by('sku', 'decision_id')
        result: dict[str, list[DecisionRecord]] = {}
        for row in rows:
            result.setdefault(row.sku, []).append(row)
        return result

    @staticmethod
    def _active_budget(workspace_id: int, today):
        """Resolve exactly one active budget; overlapping budgets are ambiguous."""
        budgets = list(ProcurementBudget.objects.filter(
            workspace_id=workspace_id, period_start__lte=today, period_end__gte=today,
        ).order_by('period_start', 'id'))
        if len(budgets) != 1:
            return None, budgets
        return budgets[0], budgets

    @classmethod
    def plan_portfolio(
        cls, *, workspace_id: int, horizon_days: int = HORIZON_DAYS,
        limit: int = MAX_PORTFOLIO_SKUS,
    ) -> dict:
        """Build a read-only order/defer/review portfolio for one workspace.

        Results are conservative: a missing budget, unknown payment schedule,
        multi-warehouse scope or a current slow-moving stop-buy decision leads
        to a visible review/data-needed item rather than an auto PO change.
        """
        horizon_days = max(1, min(int(horizon_days), cls.HORIZON_DAYS))
        limit = max(1, min(int(limit), cls.MAX_PORTFOLIO_SKUS))
        workspace = Workspace.objects.get(id=workspace_id)
        all_skus = cls._replenishment_skus(workspace_id)
        skus = all_skus[:limit]
        stop_decisions = cls._current_stop_buy_decisions(workspace_id)
        today = timezone.localdate()
        budget, ambiguous_budgets = cls._active_budget(workspace_id, today)
        budget_summary = {
            'status': 'DATA_NEEDED' if not budget else 'READY',
            'budget_id': budget.id if budget else None,
            'period_start': budget.period_start.isoformat() if budget else None,
            'period_end': budget.period_end.isoformat() if budget else None,
            'amount': float(budget.amount) if budget else None,
            'currency': budget.currency if budget else None,
            'reason': (
                'Chưa có đúng một ngân sách mua hàng đang hiệu lực; hệ thống không tự giả định ngân sách bằng 0.'
                if not budget else None
            ),
            'overlapping_budget_ids': [item.id for item in ambiguous_budgets] if len(ambiguous_budgets) > 1 else [],
        }
        scheduled_commitment = Decimal('0')
        undated_commitment = Decimal('0')
        if budget:
            scheduled_commitment = sum(
                (Decimal(row.amount) for row in PaymentSchedule.objects.filter(
                    purchase_order__workspace_id=workspace_id,
                    due_date__gte=budget.period_start, due_date__lte=budget.period_end,
                ).exclude(status='PAID')),
                Decimal('0'),
            )
            undated_commitment = sum(
                (
                    max(Decimal('0'), Decimal(line.ordered_quantity) - Decimal(line.received_quantity)) * Decimal(line.unit_cost)
                    for line in PurchaseOrderLine.objects.filter(
                        purchase_order__workspace_id=workspace_id,
                        purchase_order__status__in=['OPEN', 'PARTIALLY_RECEIVED'],
                        purchase_order__payment_schedules__isnull=True,
                        unit_cost__isnull=False,
                    )
                ),
                Decimal('0'),
            )
            budget_summary.update({
                'scheduled_commitment': float(scheduled_commitment),
                'undated_open_commitment': float(undated_commitment),
                'remaining_before_new_orders': float(Decimal(budget.amount) - scheduled_commitment),
                'payment_date_boundary': 'Cam kết PO chưa có lịch thanh toán không được trừ vào ngân sách theo ngày; chúng được hiển thị riêng để cần rà soát.',
            })

        items: list[dict] = []
        for sku in skus:
            item = cls.plan_sku(
                workspace_id=workspace_id, sku=sku, horizon_days=horizon_days, persist=False,
            )
            item['portfolio_state'] = 'DATA_NEEDED' if item['status'] != 'READY' else 'PENDING'
            item['portfolio_reasons'] = list(item.get('missing_inputs') or [])
            linked = stop_decisions.get(sku, [])
            item['slow_moving_conflict'] = {
                'status': 'REVIEW_REQUIRED' if linked else 'NONE',
                'decision_ids': [row.decision_id for row in linked],
                'message': (
                    'SKU có khuyến nghị tạm dừng tái nhập từ cảnh báo tồn chậm. Không tự sửa PO; chủ sở hữu cần quyết định giữ, hoãn hoặc hủy theo chính sách nhà cung cấp.'
                    if linked else None
                ),
                'owner_resolution_checklist': (
                    [
                        'Đối chiếu số lượng còn lại và ngày nhận dự kiến của từng PO mở.',
                        'Xác nhận điều kiện giữ/hoãn/hủy với nhà cung cấp.',
                        'Ghi quyết định, người phụ trách và bằng chứng vào action plan hoặc hệ thống mua hàng.',
                    ] if linked else []
                ),
            }
            if linked:
                item['portfolio_state'] = 'REVIEW_STOP_REPLENISHMENT'
                item['portfolio_reasons'].append(item['slow_moving_conflict']['message'])
            items.append(item)

        # Earliest expected stockout is reviewed first.  No price/discount
        # forecast participates in this order, and ties are stable by SKU.
        def order_key(item: dict):
            stockout = item.get('estimated_stockout_date') or '9999-12-31'
            return (stockout, -float(item.get('capital_required') or 0), item.get('sku') or '')

        remaining = Decimal(str(budget_summary.get('remaining_before_new_orders', '0'))) if budget else None
        for item in sorted(items, key=order_key):
            if item['portfolio_state'] != 'PENDING':
                continue
            capital = Decimal(str(item.get('capital_required') or 0))
            if item.get('recommendation') != 'ORDER' or capital <= 0:
                item['portfolio_state'] = 'DEFER_REVIEW'
                item['portfolio_reasons'].append('Chưa cần đơn mua bổ sung theo tồn, vận tốc bán quan sát và PO có ngày nhận đã ghi nhận.')
                continue
            if not budget:
                item['portfolio_state'] = 'REVIEW_BUDGET'
                item['portfolio_reasons'].append('Cần ngân sách mua hàng đang hiệu lực trước khi đề xuất review đơn mua.')
                continue
            if budget.currency != 'VND':
                item['portfolio_state'] = 'REVIEW_BUDGET'
                item['portfolio_reasons'].append('Ngân sách không cùng tiền tệ VND với giá mua; hệ thống không tự quy đổi.')
                continue
            if capital > remaining:
                item['portfolio_state'] = 'REVIEW_BUDGET'
                item['portfolio_reasons'].append('Vốn cần cho đơn mua vượt ngân sách còn lại theo lịch thanh toán đã biết.')
                continue
            item['portfolio_state'] = 'ORDER_REVIEW'
            item['portfolio_reasons'].append('Đủ điều kiện dữ liệu và ngân sách hiện có để tạo bản nháp PO cho người phụ trách review; hệ thống không tự tạo PO.')
            remaining -= capital

        sections = {
            'order_review': [item for item in items if item['portfolio_state'] == 'ORDER_REVIEW'],
            'stop_replenishment_review': [item for item in items if item['portfolio_state'] == 'REVIEW_STOP_REPLENISHMENT'],
            'budget_review': [item for item in items if item['portfolio_state'] == 'REVIEW_BUDGET'],
            'defer_review': [item for item in items if item['portfolio_state'] == 'DEFER_REVIEW'],
            'data_needed': [item for item in items if item['portfolio_state'] == 'DATA_NEEDED'],
        }
        result = {
            'version': 'PROCUREMENT_PORTFOLIO_V1',
            'status': 'READY',
            'horizon_days': horizon_days,
            'as_of': today.isoformat(),
            'coverage': {
                'eligible_sku_count': len(all_skus), 'evaluated_sku_count': len(skus),
                'truncated': len(all_skus) > len(skus), 'limit': limit,
                'message': (
                    f'Đang đánh giá {len(skus)}/{len(all_skus)} SKU có bằng chứng mua hàng/tồn kho.'
                    if len(all_skus) > len(skus) else f'Đã đánh giá {len(skus)} SKU có bằng chứng mua hàng/tồn kho.'
                ),
            },
            'budget': budget_summary | ({'remaining_after_selected_orders': float(remaining)} if remaining is not None else {}),
            'items': sorted(items, key=order_key),
            'sections': sections,
            'boundary': 'Mọi đề xuất đều là hàng đợi review. SupplyForge không tự tạo, hoãn, hủy hoặc sửa đơn mua; ngày thanh toán chỉ được hiển thị khi có lịch PO đã ghi nhận.',
        }
        run = ProcurementPortfolioRun.objects.create(
            workspace=workspace, horizon_days=horizon_days,
            input_lineage_json={
                'sku_count': len(skus), 'eligible_sku_count': len(all_skus),
                'stop_replenishment_decision_ids': [row.decision_id for rows in stop_decisions.values() for row in rows],
                'budget_id': budget.id if budget else None,
            },
            result_snapshot_json=result,
        )
        return {'run_id': str(run.id), 'created_at': run.created_at.isoformat(), **result}

    @classmethod
    def cash_flow(cls, *, workspace_id: int, horizon_days: int = HORIZON_DAYS) -> dict:
        horizon_days = max(1, min(int(horizon_days), cls.HORIZON_DAYS))
        start, end = timezone.localdate(), timezone.localdate() + timedelta(days=horizon_days)
        schedules = PaymentSchedule.objects.filter(
            purchase_order__workspace_id=workspace_id, due_date__gte=start, due_date__lte=end,
        ).exclude(status='PAID').select_related('purchase_order')
        daily: dict[str, Decimal] = {}
        for row in schedules:
            key = row.due_date.isoformat()
            daily[key] = daily.get(key, Decimal('0')) + Decimal(row.amount)
        # A payment date cannot be invented from a PO without a schedule or a
        # supplier term. Report the known value separately instead of folding
        # it into the dated cash-flow series.
        undated_commitment = sum(
            (
                max(Decimal('0'), Decimal(line.ordered_quantity) - Decimal(line.received_quantity)) * Decimal(line.unit_cost)
                for line in PurchaseOrderLine.objects.filter(
                    purchase_order__workspace_id=workspace_id,
                    purchase_order__status__in=['OPEN', 'PARTIALLY_RECEIVED'],
                    purchase_order__payment_schedules__isnull=True,
                    unit_cost__isnull=False,
                )
            ),
            Decimal('0'),
        )
        return {
            'status': 'READY', 'horizon_days': horizon_days, 'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'scheduled_payments': [{'date': day, 'amount': float(amount)} for day, amount in sorted(daily.items())],
            'total_scheduled_payment': float(sum(daily.values(), Decimal('0'))),
            'undated_open_purchase_commitment': float(undated_commitment),
            'scope': 'Chỉ bao gồm lịch thanh toán PO đã ghi nhận. Cam kết PO chưa có lịch được hiển thị riêng và không được gán ngày thanh toán. Chưa bao gồm doanh thu hoặc chi phí chưa được nhập.',
        }
