"""Evidence-first merchant pricing options. No synthetic financial inputs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from supplyforge.models import ChannelCostProfile, InventoryRecord, PricingScenarioSnapshot, Workspace
from supplyforge.services.temporal_feature_service import FeatureContractIncomplete, TemporalFeatureService


MONEY = Decimal('0.01')


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


class PricingGuardrailService:
    """Calculates options only when all validated financial facts are present."""

    @staticmethod
    def _inventory(workspace_id: int, sku: str, warehouse_code: str = ''):
        """Return one explicitly scoped inventory fact, never an arbitrary row.

        A price can only be approved against a particular inventory scope.  A
        SKU present in several warehouses cannot safely borrow the first row
        returned by a database ordering: its cost, availability and freshness
        may be different.  Callers must select a warehouse in that case.
        """
        qs = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id,
            canonical_sku=sku,
            as_of_verified=True,
        )
        if warehouse_code:
            return qs.filter(warehouse_code=warehouse_code).order_by(
                '-record_date', '-source_observed_at', '-id'
            ).first(), []

        # Only simultaneous latest facts define today's warehouse scope. A
        # warehouse used by an old stock import must not permanently block a
        # later single-warehouse price review.
        latest_date = qs.order_by('-record_date').values_list('record_date', flat=True).first()
        rows = list(qs.filter(record_date=latest_date).only('id', 'warehouse_code', 'record_date', 'source_observed_at').order_by(
            '-source_observed_at', '-id'
        )) if latest_date else []
        if not rows:
            return None, []
        warehouses = sorted({(row.warehouse_code or '').strip() or 'UNSPECIFIED' for row in rows})
        if len(warehouses) > 1:
            return None, warehouses
        record_id = rows[0].id
        return InventoryRecord.objects.get(id=record_id), warehouses

    @staticmethod
    def _profile(workspace_id: int, channel: str, as_of: date):
        return ChannelCostProfile.objects.filter(
            workspace_id=workspace_id, channel=channel, is_approved=True,
            effective_from__lte=as_of,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of)).order_by('-effective_from', '-id').first()

    @classmethod
    def build(cls, *, workspace_id: int, sku: str, channel: str, warehouse_code: str = '', duration_days: int = 14) -> dict:
        workspace = Workspace.objects.get(id=workspace_id)
        inventory, available_warehouses = cls._inventory(workspace_id, sku, warehouse_code)
        as_of = inventory.record_date if inventory else date.today()
        profile = cls._profile(workspace_id, channel, as_of)
        missing: list[str] = []
        if not inventory:
            if available_warehouses:
                missing.append('Phạm vi kho cụ thể (SKU đang có ở nhiều kho)')
            else:
                missing.append('Tồn kho đã xác thực')
        else:
            quantity = inventory.available_quantity if inventory.available_quantity is not None else inventory.quantity
            if quantity is None:
                missing.append('Số lượng tồn khả dụng')
            elif Decimal(quantity) < 0:
                missing.append('Số lượng tồn khả dụng hợp lệ')
            if inventory.cost_price is None or inventory.cost_price < 0:
                missing.append('Giá vốn đã xác thực')
            if inventory.selling_price is None or inventory.selling_price <= 0:
                missing.append('Giá bán đã xác thực')
        if not profile:
            missing.append('Hồ sơ phí kênh đã phê duyệt')
        elif any(value is None for value in (
            profile.platform_fee_rate, profile.payment_fee_rate, profile.tax_rate,
            profile.shipping_subsidy_per_unit, profile.voucher_cost_per_unit,
            profile.advertising_cost_per_unit,
        )):
            missing.append('Thành phần phí hoặc thuế trong hồ sơ kênh')
        # The current temporal demand contract is scoped to workspace + SKU.
        # It is intentionally not presented as channel-specific demand when a
        # merchant is calculating a price for one sales channel.
        velocity = None
        demand_projection_status = 'UNAVAILABLE_CHANNEL_SCOPE'
        demand_projection_reason = 'Chưa có vận tốc bán đã quan sát theo đúng kênh đang chọn; hệ thống chỉ tính giá sàn và biên lợi nhuận mỗi đơn vị.'
        try:
            velocity = Decimal(str(TemporalFeatureService().extract_for_workspace(sku, workspace_id).values['sales_velocity_30d']))
        except FeatureContractIncomplete:
            demand_projection_status = 'UNAVAILABLE_NO_OBSERVED_DEMAND'
            demand_projection_reason = 'Chưa có vận tốc bán đã quan sát; hệ thống chỉ tính giá sàn và biên lợi nhuận mỗi đơn vị.'

        lineage = {
            'inventory_record_id': inventory.id if inventory else None,
            'inventory_as_of': inventory.record_date.isoformat() if inventory else None,
            'inventory_source': inventory.source_lineage_json if inventory else {},
            'warehouse_scope': warehouse_code or (available_warehouses[0] if len(available_warehouses) == 1 else None),
            'available_warehouses': available_warehouses,
            'cost_profile_id': profile.id if profile else None,
            'cost_profile_effective_from': profile.effective_from.isoformat() if profile else None,
            'demand_scope': {
                'status': demand_projection_status,
                'known_velocity_scope': 'WORKSPACE_SKU_AGGREGATE' if velocity is not None else None,
                'reason': demand_projection_reason,
            },
        }
        if missing:
            payload = {
                'status': 'DATA_UNAVAILABLE', 'sku': sku, 'channel': channel,
                'duration_days': duration_days, 'missing_inputs': missing, 'options': [],
                'lineage': lineage,
                'message': 'Chưa đủ dữ liệu đã xác thực để lập phương án giá an toàn.',
            }
            PricingScenarioSnapshot.objects.create(
                workspace=workspace, sku=sku, warehouse_code=warehouse_code, channel=channel,
                inventory_record=inventory, cost_profile=profile, status='DATA_UNAVAILABLE',
                missing_inputs_json=missing, input_lineage_json=lineage, options_json=[],
            )
            return payload

        quantity = Decimal(inventory.available_quantity if inventory.available_quantity is not None else inventory.quantity)
        unit_cost, list_price = Decimal(inventory.cost_price), Decimal(inventory.selling_price)
        variable_rate = Decimal(profile.platform_fee_rate) + Decimal(profile.payment_fee_rate) + Decimal(profile.tax_rate)
        fixed_cost = Decimal(profile.shipping_subsidy_per_unit) + Decimal(profile.voucher_cost_per_unit) + Decimal(profile.advertising_cost_per_unit)
        minimum_margin = Decimal(profile.minimum_margin_rate)
        target_margin = Decimal(profile.target_margin_rate)
        denominator = Decimal('1') - variable_rate - minimum_margin
        target_denominator = Decimal('1') - variable_rate - target_margin
        if denominator <= 0 or target_denominator <= 0:
            return cls._invalid_profile(workspace, sku, channel, warehouse_code, inventory, profile, lineage)
        floor = (unit_cost + fixed_cost) / denominator
        target_floor = (unit_cost + fixed_cost) / target_denominator
        # Do not turn aggregate historical demand into a forecast for an
        # individual channel. The price floor remains usable; volume, revenue
        # and total contribution are intentionally withheld.
        expected_units = None

        def option(key: str, label: str, discount_rate: Decimal, needs_approval: bool = False) -> dict:
            selling_price = list_price * (Decimal('1') - discount_rate)
            total_cost = unit_cost + fixed_cost + (selling_price * variable_rate)
            profit = selling_price - total_cost
            margin = profit / selling_price if selling_price > 0 else Decimal('-1')
            blocked = selling_price < floor or margin < minimum_margin
            return {
                'key': key, 'label': label, 'discount_rate': float(discount_rate),
                'duration_days': duration_days, 'price': _money(selling_price),
                'price_floor': _money(floor), 'target_price_floor': _money(target_floor),
                'estimated_profit_per_unit': _money(profit), 'estimated_margin_rate': float(margin.quantize(Decimal('0.0001'))),
                'expected_units': None,
                'estimated_revenue': None,
                'projected_inventory_cost_rotation': None,
                'projected_net_contribution': None,
                'status': 'BLOCKED' if blocked else 'REQUIRES_APPROVAL',
                'warnings': (
                    ['Giá sau giảm thấp hơn giá sàn hoặc âm biên lợi nhuận.'] if blocked else
                    [demand_projection_reason]
                ),
            }

        safe_discount = max(Decimal('0'), Decimal('1') - (floor / list_price))
        options = [
            option('HOLD_PRICE', 'Giữ giá', Decimal('0')),
            option('CONTROLLED_DISCOUNT', 'Giảm giá có kiểm soát', min(safe_discount, Decimal('0.50'))),
            option('FAST_CLEARANCE', 'Xả hàng nhanh', min(safe_discount + Decimal('0.15'), Decimal('0.70')), True),
        ]
        payload = {
            'status': 'READY', 'sku': sku, 'channel': channel, 'duration_days': duration_days,
            'observed_daily_velocity_workspace_sku': float(velocity) if velocity is not None else None,
            'demand_projection_status': demand_projection_status,
            'available_quantity': float(quantity),
            'cost_breakdown': {
                'unit_cost': _money(unit_cost), 'platform_fee_rate': float(profile.platform_fee_rate),
                'payment_fee_rate': float(profile.payment_fee_rate), 'tax_rate': float(profile.tax_rate),
                'shipping_subsidy_per_unit': _money(Decimal(profile.shipping_subsidy_per_unit)),
                'voucher_cost_per_unit': _money(Decimal(profile.voucher_cost_per_unit)),
                'advertising_cost_per_unit': _money(Decimal(profile.advertising_cost_per_unit)),
            }, 'options': options, 'lineage': lineage,
            'message': 'Các phương án dưới đây là giá sàn và biên lợi nhuận mỗi đơn vị. Dự báo số lượng/doanh thu chỉ được bật khi có nhu cầu đã quan sát khớp kênh và kho.',
        }
        PricingScenarioSnapshot.objects.create(
            workspace=workspace, sku=sku, warehouse_code=warehouse_code, channel=channel,
            inventory_record=inventory, cost_profile=profile, status='READY',
            input_lineage_json=lineage, options_json=options,
        )
        return payload

    @staticmethod
    def _invalid_profile(workspace, sku, channel, warehouse_code, inventory, profile, lineage):
        missing = ['Hồ sơ phí kênh có tỷ lệ phí và biên lợi nhuận hợp lệ']
        PricingScenarioSnapshot.objects.create(
            workspace=workspace, sku=sku, warehouse_code=warehouse_code, channel=channel,
            inventory_record=inventory, cost_profile=profile, status='DATA_UNAVAILABLE',
            missing_inputs_json=missing, input_lineage_json=lineage, options_json=[],
        )
        return {'status': 'DATA_UNAVAILABLE', 'sku': sku, 'channel': channel, 'missing_inputs': missing, 'options': [], 'lineage': lineage}
