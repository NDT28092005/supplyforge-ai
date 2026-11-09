"""Tenant-safe APIs for merchant pricing guardrails and procurement planning."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models import (
    ActionPlanRecord, ChannelCostProfile, PaymentSchedule, ProcurementBudget, PurchaseOrder,
    PurchaseOrderLine, Supplier, SupplierReturnRequest, SupplierSkuTerm,
)
from supplyforge.permissions import PERM_EXECUTE_ACTION, PERM_VIEW_FINANCIAL, has_permission
from supplyforge.services.pricing_guardrails import PricingGuardrailService
from supplyforge.services.procurement_planning import ProcurementPlanningService


def _workspace_id(request):
    return int(request.workspace_id) if getattr(request, 'tenant_context_validated', False) and getattr(request, 'workspace_id', None) else None


def _auth_error(request, *, write=False):
    workspace_id = _workspace_id(request)
    if not workspace_id:
        return Response({'error': {'code': 'UNAUTHENTICATED', 'message': 'Yêu cầu cần workspace đã xác thực.'}}, status=status.HTTP_401_UNAUTHORIZED)
    permission = PERM_EXECUTE_ACTION if write else PERM_VIEW_FINANCIAL
    if not has_permission(getattr(request, 'user_role', None), permission):
        return Response({'error': {'code': 'PERMISSION_DENIED', 'message': 'Tài khoản hiện tại không có quyền truy cập dữ liệu vận hành này.'}}, status=status.HTTP_403_FORBIDDEN)
    return None


def _as_date(value, field):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} phải có định dạng YYYY-MM-DD.') from exc


def _decimal(value, field, *, allow_zero=True):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'{field} phải là số hợp lệ.') from exc
    if not parsed.is_finite():
        raise ValueError(f'{field} phải là số hữu hạn.')
    if parsed < 0 or (not allow_zero and parsed == 0):
        comparison = 'lớn hơn 0' if not allow_zero else 'lớn hơn hoặc bằng 0'
        raise ValueError(f'{field} phải {comparison}.')
    return parsed


def _integer(value, field, *, minimum=0):
    try:
        if isinstance(value, bool):
            raise ValueError
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} phải là số nguyên hợp lệ.') from exc
    if parsed < minimum:
        raise ValueError(f'{field} phải lớn hơn hoặc bằng {minimum}.')
    return parsed


def _horizon_days(value):
    try:
        days = _integer(value or 90, 'horizon_days', minimum=1)
    except ValueError as exc:
        raise ValueError('Kỳ dự báo phải là số nguyên từ 1 đến 90 ngày.') from exc
    if days > 90:
        raise ValueError('Kỳ dự báo phải từ 1 đến 90 ngày.')
    return days


def _validated_purchase_order_payload(data):
    po_number = str(data.get('po_number') or '').strip()
    if not po_number:
        raise ValueError('Số PO là bắt buộc.')
    if len(po_number) > 128:
        raise ValueError('Số PO không được dài quá 128 ký tự.')

    status_value = str(data.get('status') or PurchaseOrder.STATUS_OPEN).upper()
    allowed_statuses = {
        PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_OPEN,
        PurchaseOrder.STATUS_PARTIALLY_RECEIVED, PurchaseOrder.STATUS_RECEIVED,
        PurchaseOrder.STATUS_CANCELLED,
    }
    if status_value not in allowed_statuses:
        raise ValueError('Trạng thái PO không hợp lệ.')

    ordered_at = _as_date(data.get('ordered_at'), 'ordered_at') if data.get('ordered_at') else None
    expected_receipt_date = _as_date(data.get('expected_receipt_date'), 'expected_receipt_date') if data.get('expected_receipt_date') else None
    payment_due_date = _as_date(data.get('payment_due_date'), 'payment_due_date') if data.get('payment_due_date') else None
    if ordered_at and expected_receipt_date and expected_receipt_date < ordered_at:
        raise ValueError('Ngày nhận hàng dự kiến không thể trước ngày đặt PO.')

    raw_lines = data.get('lines') or []
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError('Cần ít nhất một dòng SKU.')
    lines, skus = [], set()
    for row in raw_lines:
        if not isinstance(row, dict):
            raise ValueError('Mỗi dòng PO phải là một đối tượng dữ liệu.')
        sku = str(row.get('sku') or '').strip()
        if not sku:
            raise ValueError('Mỗi dòng PO cần SKU.')
        if sku in skus:
            raise ValueError(f'SKU {sku} bị lặp trong PO.')
        skus.add(sku)
        ordered_quantity = _decimal(row.get('ordered_quantity'), 'ordered_quantity', allow_zero=False)
        received_quantity = _decimal(row.get('received_quantity', 0), 'received_quantity')
        if received_quantity > ordered_quantity:
            raise ValueError(f'Số lượng đã nhận của SKU {sku} không thể lớn hơn số lượng đặt.')
        unit_cost = _decimal(row['unit_cost'], 'unit_cost') if row.get('unit_cost') not in (None, '') else None
        lines.append({
            'canonical_sku': sku[:255], 'ordered_quantity': ordered_quantity,
            'received_quantity': received_quantity, 'unit_cost': unit_cost,
        })

    raw_schedules = data.get('payment_schedules') or []
    if not isinstance(raw_schedules, list):
        raise ValueError('Lịch thanh toán phải là một danh sách.')
    payment_schedules = []
    for row in raw_schedules:
        if not isinstance(row, dict):
            raise ValueError('Mỗi lịch thanh toán phải là một đối tượng dữ liệu.')
        payment_schedules.append({
            'due_date': _as_date(row.get('due_date'), 'due_date'),
            'amount': _decimal(row.get('amount'), 'amount', allow_zero=False),
        })
    return {
        'po_number': po_number, 'status': status_value, 'ordered_at': ordered_at,
        'expected_receipt_date': expected_receipt_date, 'payment_due_date': payment_due_date,
        'currency': str(data.get('currency') or 'VND').upper()[:3], 'lines': lines,
        'payment_schedules': payment_schedules,
    }


def _profile_payload(item):
    return {
        'id': item.id, 'channel': item.channel, 'effective_from': item.effective_from.isoformat(),
        'effective_to': item.effective_to.isoformat() if item.effective_to else None,
        'platform_fee_rate': float(item.platform_fee_rate) if item.platform_fee_rate is not None else None,
        'payment_fee_rate': float(item.payment_fee_rate) if item.payment_fee_rate is not None else None,
        'tax_rate': float(item.tax_rate) if item.tax_rate is not None else None,
        'shipping_subsidy_per_unit': float(item.shipping_subsidy_per_unit) if item.shipping_subsidy_per_unit is not None else None,
        'voucher_cost_per_unit': float(item.voucher_cost_per_unit) if item.voucher_cost_per_unit is not None else None,
        'advertising_cost_per_unit': float(item.advertising_cost_per_unit) if item.advertising_cost_per_unit is not None else None,
        'target_margin_rate': float(item.target_margin_rate), 'minimum_margin_rate': float(item.minimum_margin_rate),
        'is_approved': item.is_approved, 'approved_by': item.approved_by,
    }


class PricingScenarioView(APIView):
    def get(self, request, sku, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        channel = str(request.query_params.get('channel') or '').strip()
        if not channel:
            return Response({'error': {'code': 'CHANNEL_REQUIRED', 'message': 'Cần chọn kênh bán để tính giá sàn.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            duration = int(request.query_params.get('duration_days') or 14)
            if not 1 <= duration <= 90:
                raise ValueError
        except ValueError:
            return Response({'error': {'code': 'INVALID_DURATION', 'message': 'Thời gian phải từ 1 đến 90 ngày.'}}, status=status.HTTP_400_BAD_REQUEST)
        payload = PricingGuardrailService.build(
            workspace_id=_workspace_id(request), sku=sku.strip(), channel=channel[:64],
            warehouse_code=str(request.query_params.get('warehouse_code') or '').strip()[:128], duration_days=duration,
        )
        return Response(payload, status=status.HTTP_200_OK if payload['status'] == 'READY' else status.HTTP_422_UNPROCESSABLE_ENTITY)


class ChannelCostProfileView(APIView):
    REQUIRED_DECIMALS = (
        'platform_fee_rate', 'payment_fee_rate', 'tax_rate', 'shipping_subsidy_per_unit',
        'voucher_cost_per_unit', 'advertising_cost_per_unit', 'target_margin_rate', 'minimum_margin_rate',
    )

    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        qs = ChannelCostProfile.objects.filter(workspace_id=_workspace_id(request)).order_by('channel', '-effective_from')
        return Response({'items': [_profile_payload(item) for item in qs]})

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        try:
            channel = str(data.get('channel') or '').strip()
            if not channel:
                raise ValueError('Kênh bán là bắt buộc.')
            values = {field: _decimal(data.get(field), field) for field in self.REQUIRED_DECIMALS}
            if any(values[field] > 1 for field in ('platform_fee_rate', 'payment_fee_rate', 'tax_rate', 'target_margin_rate', 'minimum_margin_rate')):
                raise ValueError('Tỷ lệ phí, thuế và biên lợi nhuận phải nằm trong khoảng 0 đến 1.')
            effective_from = _as_date(data.get('effective_from'), 'effective_from')
            effective_to = _as_date(data['effective_to'], 'effective_to') if data.get('effective_to') else None
            if effective_to and effective_to < effective_from:
                raise ValueError('Ngày kết thúc hiệu lực không thể trước ngày bắt đầu.')
            profile = ChannelCostProfile.objects.create(
                workspace_id=_workspace_id(request), channel=channel[:64], effective_from=effective_from,
                effective_to=effective_to,
                is_approved=bool(data.get('is_approved', False)),
                approved_by=str(getattr(request, 'user_email', '') or '')[:128] if data.get('is_approved') else '',
                approved_at=timezone.now() if data.get('is_approved') else None, **values,
            )
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_COST_PROFILE', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_profile_payload(profile), status=status.HTTP_201_CREATED)


class SupplierListCreateView(APIView):
    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        items = Supplier.objects.filter(workspace_id=_workspace_id(request)).order_by('name')
        return Response({'items': [{'id': item.id, 'name': item.name, 'code': item.code, 'email': item.email, 'is_active': item.is_active} for item in items]})

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        name = str(data.get('name') or '').strip()
        if not name:
            return Response({'error': {'code': 'SUPPLIER_NAME_REQUIRED', 'message': 'Tên nhà cung cấp là bắt buộc.'}}, status=status.HTTP_400_BAD_REQUEST)
        supplier = Supplier.objects.create(
            workspace_id=_workspace_id(request), name=name[:255], code=str(data.get('code') or '').strip()[:64],
            email=str(data.get('email') or '').strip()[:254], phone=str(data.get('phone') or '').strip()[:64],
        )
        return Response({'id': supplier.id, 'name': supplier.name, 'code': supplier.code}, status=status.HTTP_201_CREATED)


class SupplierTermListCreateView(APIView):
    def get(self, request, supplier_id, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        terms = SupplierSkuTerm.objects.filter(supplier_id=supplier_id, supplier__workspace_id=_workspace_id(request)).order_by('-effective_from')
        return Response({'items': [{
            'id': item.id, 'sku': item.canonical_sku, 'lead_time_days': item.lead_time_days, 'moq': float(item.moq) if item.moq is not None else None,
            'order_multiple': float(item.order_multiple) if item.order_multiple is not None else None, 'unit_cost': float(item.unit_cost) if item.unit_cost is not None else None,
            'payment_term_days': item.payment_term_days, 'effective_from': item.effective_from.isoformat(),
        } for item in terms]})

    def post(self, request, supplier_id, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        supplier = Supplier.objects.filter(id=supplier_id, workspace_id=_workspace_id(request)).first()
        if not supplier:
            return Response({'error': {'code': 'SUPPLIER_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        data = request.data or {}
        try:
            sku = str(data.get('sku') or '').strip()
            if not sku:
                raise ValueError('SKU là bắt buộc.')
            term = SupplierSkuTerm.objects.create(
                supplier=supplier, canonical_sku=sku[:255], lead_time_days=_integer(data.get('lead_time_days'), 'lead_time_days', minimum=1),
                moq=_decimal(data.get('moq'), 'moq', allow_zero=False), order_multiple=_decimal(data.get('order_multiple'), 'order_multiple', allow_zero=False),
                unit_cost=_decimal(data.get('unit_cost'), 'unit_cost', allow_zero=False), payment_term_days=_integer(data.get('payment_term_days') or 0, 'payment_term_days'),
                effective_from=_as_date(data.get('effective_from'), 'effective_from'),
            )
        except (TypeError, ValueError) as exc:
            return Response({'error': {'code': 'INVALID_SUPPLIER_TERM', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': term.id, 'sku': term.canonical_sku}, status=status.HTTP_201_CREATED)


class ProcurementForecastView(APIView):
    def get(self, request, sku, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        try:
            horizon_days = _horizon_days(request.query_params.get('horizon_days'))
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_HORIZON', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        payload = ProcurementPlanningService.plan_sku(
            workspace_id=_workspace_id(request), sku=sku.strip(), horizon_days=horizon_days,
            warehouse_code=str(request.query_params.get('warehouse_code') or '').strip()[:128],
        )
        return Response(payload, status=status.HTTP_200_OK if payload['status'] == 'READY' else status.HTTP_422_UNPROCESSABLE_ENTITY)


class ProcurementCashFlowView(APIView):
    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        try:
            horizon_days = _horizon_days(request.query_params.get('horizon_days'))
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_HORIZON', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProcurementPlanningService.cash_flow(workspace_id=_workspace_id(request), horizon_days=horizon_days))


class ProcurementPortfolioView(APIView):
    """Read-only replenishment portfolio; it never creates or changes a PO."""

    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        try:
            horizon_days = _horizon_days(request.query_params.get('horizon_days'))
            raw_limit = request.query_params.get('limit') or ProcurementPlanningService.MAX_PORTFOLIO_SKUS
            limit = _integer(raw_limit, 'limit', minimum=1)
            if limit > ProcurementPlanningService.MAX_PORTFOLIO_SKUS:
                raise ValueError(f'limit phải từ 1 đến {ProcurementPlanningService.MAX_PORTFOLIO_SKUS}.')
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_PORTFOLIO_REQUEST', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        payload = ProcurementPlanningService.plan_portfolio(
            workspace_id=_workspace_id(request), horizon_days=horizon_days, limit=limit,
        )
        return Response(payload)


class PurchaseOrderListCreateView(APIView):
    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        items = PurchaseOrder.objects.filter(workspace_id=_workspace_id(request)).select_related('supplier').prefetch_related('lines', 'payment_schedules').order_by('-ordered_at', '-id')
        return Response({'items': [{
            'id': po.id, 'po_number': po.po_number, 'supplier': {'id': po.supplier_id, 'name': po.supplier.name}, 'status': po.status,
            'expected_receipt_date': po.expected_receipt_date.isoformat() if po.expected_receipt_date else None,
            'payment_due_date': po.payment_due_date.isoformat() if po.payment_due_date else None,
            'lines': [{'sku': line.canonical_sku, 'ordered_quantity': float(line.ordered_quantity), 'received_quantity': float(line.received_quantity), 'unit_cost': float(line.unit_cost) if line.unit_cost is not None else None} for line in po.lines.all()],
        } for po in items]})

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        supplier = Supplier.objects.filter(id=data.get('supplier_id'), workspace_id=_workspace_id(request)).first()
        if not supplier:
            return Response({'error': {'code': 'INVALID_PURCHASE_ORDER', 'message': 'Cần chọn nhà cung cấp và ít nhất một dòng SKU.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = _validated_purchase_order_payload(data)
            with transaction.atomic():
                po = PurchaseOrder.objects.create(
                    workspace_id=_workspace_id(request), supplier=supplier,
                    po_number=payload['po_number'], status=payload['status'],
                    ordered_at=payload['ordered_at'], expected_receipt_date=payload['expected_receipt_date'],
                    payment_due_date=payload['payment_due_date'], currency=payload['currency'],
                )
                PurchaseOrderLine.objects.bulk_create([
                    PurchaseOrderLine(purchase_order=po, **row) for row in payload['lines']
                ])
                PaymentSchedule.objects.bulk_create([
                    PaymentSchedule(purchase_order=po, **row) for row in payload['payment_schedules']
                ])
        except (TypeError, ValueError, InvalidOperation) as exc:
            return Response({'error': {'code': 'INVALID_PURCHASE_ORDER', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response({'error': {'code': 'PURCHASE_ORDER_CONFLICT', 'message': 'Số PO đã tồn tại hoặc dữ liệu PO đang được tạo đồng thời.'}}, status=status.HTTP_409_CONFLICT)
        return Response({'id': po.id, 'po_number': po.po_number}, status=status.HTTP_201_CREATED)


class ProcurementBudgetListCreateView(APIView):
    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        items = ProcurementBudget.objects.filter(workspace_id=_workspace_id(request)).order_by('-period_start')
        return Response({'items': [{'id': item.id, 'period_start': item.period_start.isoformat(), 'period_end': item.period_end.isoformat(), 'amount': float(item.amount), 'currency': item.currency} for item in items]})

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        try:
            period_start, period_end = _as_date(data.get('period_start'), 'period_start'), _as_date(data.get('period_end'), 'period_end')
            if period_end < period_start:
                raise ValueError('Kết thúc ngân sách không thể trước ngày bắt đầu.')
            budget = ProcurementBudget.objects.update_or_create(
                workspace_id=_workspace_id(request), period_start=period_start, period_end=period_end,
                defaults={'amount': _decimal(data.get('amount'), 'amount', allow_zero=False), 'currency': str(data.get('currency') or 'VND').upper()[:3]},
            )[0]
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_BUDGET', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': budget.id, 'amount': float(budget.amount)}, status=status.HTTP_201_CREATED)


class SupplierReturnRequestView(APIView):
    def get(self, request, *args, **kwargs):
        error = _auth_error(request)
        if error:
            return error
        items = SupplierReturnRequest.objects.filter(workspace_id=_workspace_id(request)).select_related('supplier', 'purchase_order').order_by('-created_at')
        return Response({'items': [{
            'id': item.id, 'supplier': item.supplier.name, 'purchase_order_id': item.purchase_order_id, 'sku': item.canonical_sku,
            'quantity': float(item.quantity), 'reason': item.reason, 'status': item.status, 'external_return_id': item.external_return_id,
            'last_error': item.last_error, 'created_at': item.created_at.isoformat(),
        } for item in items]})

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        supplier = Supplier.objects.filter(id=data.get('supplier_id'), workspace_id=_workspace_id(request)).first()
        if not supplier:
            return Response({'error': {'code': 'SUPPLIER_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        key = str(data.get('idempotency_key') or '').strip()
        if not key:
            return Response({'error': {'code': 'IDEMPOTENCY_KEY_REQUIRED', 'message': 'Cần idempotency_key để tạo yêu cầu hoàn trả.'}}, status=status.HTTP_400_BAD_REQUEST)
        if len(key) > 128:
            return Response({'error': {'code': 'INVALID_RETURN_REQUEST', 'message': 'idempotency_key không được dài quá 128 ký tự.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            purchase_order = None
            if data.get('purchase_order_id'):
                purchase_order = PurchaseOrder.objects.filter(
                    id=data['purchase_order_id'], workspace_id=_workspace_id(request),
                ).first()
                if not purchase_order:
                    raise ValueError('Đơn mua không thuộc workspace hiện tại hoặc không tồn tại.')
                if purchase_order.supplier_id != supplier.id:
                    raise ValueError('Đơn mua không thuộc nhà cung cấp đã chọn.')
            action_plan = None
            if data.get('action_plan_id'):
                action_plan = ActionPlanRecord.objects.filter(
                    plan_id=str(data['action_plan_id']), workspace_id=_workspace_id(request),
                ).first()
                if not action_plan:
                    raise ValueError('Kế hoạch xử lý không thuộc workspace hiện tại hoặc không tồn tại.')
            sku, reason = str(data.get('sku') or '').strip(), str(data.get('reason') or '').strip()
            if not sku or len(reason) < 8:
                raise ValueError('SKU và lý do hoàn trả tối thiểu 8 ký tự là bắt buộc.')
            quantity = _decimal(data.get('quantity'), 'quantity', allow_zero=False)
            if purchase_order and not purchase_order.lines.filter(canonical_sku=sku).exists():
                raise ValueError('SKU hoàn trả không có trong đơn mua đã chọn.')
            values = {
                'supplier': supplier, 'purchase_order': purchase_order, 'action_plan': action_plan,
                'canonical_sku': sku[:255], 'quantity': quantity, 'reason': reason,
                'source_picking_external_id': str(data.get('source_picking_external_id') or '').strip()[:128],
                'external_product_id': str(data.get('external_product_id') or '').strip()[:128],
                'status': SupplierReturnRequest.STATUS_PENDING_APPROVAL,
            }
            with transaction.atomic():
                record, created = SupplierReturnRequest.objects.get_or_create(
                    workspace_id=_workspace_id(request), idempotency_key=key, defaults=values,
                )
                if not created and any(getattr(record, field) != value for field, value in values.items() if field != 'status'):
                    return Response({'error': {'code': 'IDEMPOTENCY_KEY_REUSED', 'message': 'idempotency_key đã được dùng cho một yêu cầu khác.'}}, status=status.HTTP_409_CONFLICT)
        except (TypeError, ValueError, InvalidOperation) as exc:
            return Response({'error': {'code': 'INVALID_RETURN_REQUEST', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': record.id, 'status': record.status, 'created': created}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class SupplierReturnApprovalView(APIView):
    def post(self, request, request_id, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        if str(getattr(request, 'user_role', '')).upper() not in {'OWNER', 'ADMIN'}:
            return Response({'error': {'code': 'APPROVAL_PERMISSION_REQUIRED', 'message': 'Chỉ chủ workspace hoặc quản trị viên được phê duyệt hoàn trả nhà cung cấp.'}}, status=status.HTTP_403_FORBIDDEN)
        actor = str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))[:128]
        approved_at = timezone.now()
        updated = SupplierReturnRequest.objects.filter(
            id=request_id, workspace_id=_workspace_id(request),
            status=SupplierReturnRequest.STATUS_PENDING_APPROVAL,
        ).update(status=SupplierReturnRequest.STATUS_APPROVED, approved_by=actor, approved_at=approved_at, updated_at=approved_at)
        if updated:
            record = SupplierReturnRequest.objects.get(id=request_id, workspace_id=_workspace_id(request))
        else:
            record = SupplierReturnRequest.objects.filter(id=request_id, workspace_id=_workspace_id(request)).first()
        if not record:
            return Response({'error': {'code': 'RETURN_REQUEST_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        if not updated:
            return Response({'error': {'code': 'INVALID_RETURN_STATUS', 'message': 'Yêu cầu không còn chờ phê duyệt.'}}, status=status.HTTP_409_CONFLICT)
        from supplyforge.tasks import submit_supplier_return_request
        submit_supplier_return_request.delay(record.id)
        return Response({'id': record.id, 'status': record.status, 'message': 'Yêu cầu đã được phê duyệt và đang gửi sang Odoo.'})


class ProcurementCsvImportView(APIView):
    """Small, inspectable CSV importer for supplier terms and open purchase orders."""

    TERM_COLUMNS = {'supplier_name', 'sku', 'lead_time_days', 'moq', 'order_multiple', 'unit_cost', 'effective_from'}
    PO_COLUMNS = {'po_number', 'supplier_name', 'sku', 'ordered_quantity'}

    def post(self, request, *args, **kwargs):
        error = _auth_error(request, write=True)
        if error:
            return error
        upload = request.FILES.get('file')
        import_type = str(request.data.get('type') or '').strip().lower()
        dry_run = str(request.data.get('dry_run') or '').lower() in {'1', 'true', 'yes'}
        if not upload or import_type not in {'supplier_terms', 'purchase_orders'}:
            return Response({'error': {'code': 'INVALID_IMPORT', 'message': 'Cần file CSV và type là supplier_terms hoặc purchase_orders.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rows = list(csv.DictReader(io.TextIOWrapper(upload.file, encoding='utf-8-sig')))
        except UnicodeDecodeError:
            return Response({'error': {'code': 'INVALID_CSV_ENCODING', 'message': 'CSV cần dùng UTF-8.'}}, status=status.HTTP_400_BAD_REQUEST)
        if not rows:
            return Response({'error': {'code': 'EMPTY_CSV', 'message': 'CSV không có dòng dữ liệu.'}}, status=status.HTTP_400_BAD_REQUEST)
        required = self.TERM_COLUMNS if import_type == 'supplier_terms' else self.PO_COLUMNS
        headers = set(rows[0])
        if not required.issubset(headers):
            return Response({'error': {'code': 'CSV_COLUMNS_MISSING', 'message': f"Thiếu cột: {', '.join(sorted(required - headers))}."}}, status=status.HTTP_400_BAD_REQUEST)
        errors, parsed = [], []
        for number, row in enumerate(rows, start=2):
            try:
                supplier_name, sku = str(row.get('supplier_name') or '').strip(), str(row.get('sku') or '').strip()
                if not supplier_name or not sku:
                    raise ValueError('supplier_name và sku là bắt buộc.')
                base = {'supplier_name': supplier_name[:255], 'supplier_code': str(row.get('supplier_code') or '').strip()[:64], 'sku': sku[:255]}
                if import_type == 'supplier_terms':
                    parsed.append({**base,
                        'lead_time_days': _integer(row.get('lead_time_days'), 'lead_time_days', minimum=1), 'moq': _decimal(row.get('moq'), 'moq', allow_zero=False),
                        'order_multiple': _decimal(row.get('order_multiple'), 'order_multiple', allow_zero=False),
                        'unit_cost': _decimal(row.get('unit_cost'), 'unit_cost', allow_zero=False),
                        'payment_term_days': _integer(row.get('payment_term_days') or 0, 'payment_term_days'), 'effective_from': _as_date(row.get('effective_from'), 'effective_from'),
                    })
                else:
                    po_number = str(row.get('po_number') or '').strip()
                    if not po_number:
                        raise ValueError('po_number là bắt buộc.')
                    parsed.append({**base, 'po_number': po_number[:128], 'status': str(row.get('status') or 'OPEN').upper()[:32],
                        'ordered_at': _as_date(row.get('ordered_at'), 'ordered_at') if row.get('ordered_at') else None,
                        'expected_receipt_date': _as_date(row.get('expected_receipt_date'), 'expected_receipt_date') if row.get('expected_receipt_date') else None,
                        'payment_due_date': _as_date(row.get('payment_due_date'), 'payment_due_date') if row.get('payment_due_date') else None,
                        'ordered_quantity': _decimal(row.get('ordered_quantity'), 'ordered_quantity', allow_zero=False),
                        'received_quantity': _decimal(row.get('received_quantity') or 0, 'received_quantity'),
                        'unit_cost': _decimal(row['unit_cost'], 'unit_cost') if row.get('unit_cost') not in (None, '') else None,
                    })
            except (TypeError, ValueError, InvalidOperation) as exc:
                errors.append({'line': number, 'message': str(exc)})
        preview = {'type': import_type, 'total_rows': len(rows), 'valid_rows': len(parsed), 'errors': errors[:100], 'dry_run': dry_run}
        if errors or dry_run:
            return Response(preview, status=status.HTTP_200_OK if not errors else status.HTTP_422_UNPROCESSABLE_ENTITY)
        workspace_id = _workspace_id(request)
        with transaction.atomic():
            suppliers = {}
            for row in parsed:
                key = (row['supplier_code'] or row['supplier_name']).lower()
                if key not in suppliers:
                    supplier = Supplier.objects.filter(workspace_id=workspace_id, code=row['supplier_code']).first() if row['supplier_code'] else Supplier.objects.filter(workspace_id=workspace_id, name=row['supplier_name'], code='').first()
                    suppliers[key] = supplier or Supplier.objects.create(workspace_id=workspace_id, name=row['supplier_name'], code=row['supplier_code'], source='CSV')
            if import_type == 'supplier_terms':
                for row in parsed:
                    SupplierSkuTerm.objects.update_or_create(
                        supplier=suppliers[(row['supplier_code'] or row['supplier_name']).lower()], canonical_sku=row['sku'], effective_from=row['effective_from'],
                        defaults={key: row[key] for key in ('lead_time_days', 'moq', 'order_multiple', 'unit_cost', 'payment_term_days')} | {'source': 'CSV'},
                    )
            else:
                for row in parsed:
                    po, _ = PurchaseOrder.objects.update_or_create(
                        workspace_id=workspace_id, po_number=row['po_number'],
                        defaults={'supplier': suppliers[(row['supplier_code'] or row['supplier_name']).lower()], 'status': row['status'], 'ordered_at': row['ordered_at'], 'expected_receipt_date': row['expected_receipt_date'], 'payment_due_date': row['payment_due_date'], 'source': 'CSV'},
                    )
                    PurchaseOrderLine.objects.update_or_create(
                        purchase_order=po, canonical_sku=row['sku'],
                        defaults={key: row[key] for key in ('ordered_quantity', 'received_quantity', 'unit_cost')},
                    )
        return Response({**preview, 'imported_rows': len(parsed)}, status=status.HTTP_201_CREATED)
