"""Workspace-scoped commercial operating facts used by pricing and procurement."""

import uuid

from django.db import models


class ChannelCostProfile(models.Model):
    """Versioned merchant-approved costs for calculating a sellable price floor."""

    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='channel_cost_profiles')
    channel = models.CharField(max_length=64)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    platform_fee_rate = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    payment_fee_rate = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    shipping_subsidy_per_unit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    voucher_cost_per_unit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    advertising_cost_per_unit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    target_margin_rate = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    minimum_margin_rate = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.CharField(max_length=128, blank=True, default='')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'channel_cost_profiles'
        indexes = [models.Index(fields=['workspace', 'channel', 'effective_from'], name='channel_cost_ws_channel_idx')]


class PricingScenarioSnapshot(models.Model):
    """Immutable calculation output with source lineage, not a price change command."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='pricing_scenarios')
    sku = models.CharField(max_length=255, db_index=True)
    warehouse_code = models.CharField(max_length=128, blank=True, default='')
    channel = models.CharField(max_length=64)
    inventory_record = models.ForeignKey('supplyforge.InventoryRecord', on_delete=models.SET_NULL, null=True, blank=True)
    cost_profile = models.ForeignKey(ChannelCostProfile, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=32, db_index=True)
    missing_inputs_json = models.JSONField(default=list, blank=True)
    input_lineage_json = models.JSONField(default=dict, blank=True)
    options_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pricing_scenario_snapshots'
        indexes = [models.Index(fields=['workspace', 'sku', 'created_at'], name='price_snapshot_ws_sku_idx')]


class Supplier(models.Model):
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=64, blank=True, default='')
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=32, default='MANUAL')
    external_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'suppliers'
        indexes = [models.Index(fields=['workspace', 'name'], name='supplier_ws_name_idx')]


class SupplierSkuTerm(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='sku_terms')
    canonical_sku = models.CharField(max_length=255)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    moq = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    order_multiple = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    payment_term_days = models.PositiveIntegerField(null=True, blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=32, default='MANUAL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'supplier_sku_terms'
        indexes = [models.Index(fields=['supplier', 'canonical_sku', 'effective_from'], name='supplier_term_sku_idx')]


class PurchaseOrder(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_OPEN = 'OPEN'
    STATUS_PARTIALLY_RECEIVED = 'PARTIALLY_RECEIVED'
    STATUS_RECEIVED = 'RECEIVED'
    STATUS_CANCELLED = 'CANCELLED'
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='purchase_orders')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    po_number = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default=STATUS_DRAFT, db_index=True)
    ordered_at = models.DateField(null=True, blank=True)
    expected_receipt_date = models.DateField(null=True, blank=True)
    payment_due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default='VND')
    source = models.CharField(max_length=32, default='MANUAL')
    external_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchase_orders'
        constraints = [models.UniqueConstraint(fields=['workspace', 'po_number'], name='po_ws_number_uq')]
        indexes = [models.Index(fields=['workspace', 'status', 'expected_receipt_date'], name='po_ws_status_eta_idx')]


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    canonical_sku = models.CharField(max_length=255, db_index=True)
    ordered_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    received_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'purchase_order_lines'
        constraints = [models.UniqueConstraint(fields=['purchase_order', 'canonical_sku'], name='po_line_po_sku_uq')]


class ProcurementBudget(models.Model):
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='procurement_budgets')
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, default='VND')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'procurement_budgets'
        constraints = [models.UniqueConstraint(fields=['workspace', 'period_start', 'period_end'], name='procurement_budget_period_uq')]


class PaymentSchedule(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='payment_schedules')
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    status = models.CharField(max_length=32, default='PLANNED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_schedules'
        indexes = [models.Index(fields=['due_date', 'status'], name='payment_due_status_idx')]


class ReplenishmentPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='replenishment_plans')
    sku = models.CharField(max_length=255, db_index=True)
    supplier_term = models.ForeignKey(SupplierSkuTerm, on_delete=models.SET_NULL, null=True, blank=True)
    horizon_days = models.PositiveIntegerField(default=90)
    status = models.CharField(max_length=32, db_index=True)
    forecast_json = models.JSONField(default=dict, blank=True)
    input_lineage_json = models.JSONField(default=dict, blank=True)
    missing_inputs_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'replenishment_plans'
        indexes = [models.Index(fields=['workspace', 'sku', 'created_at'], name='replenish_plan_ws_sku_idx')]


class ProcurementPortfolioRun(models.Model):
    """Immutable review snapshot for a workspace replenishment portfolio.

    It is an advisory read model.  Keeping it separate from purchase orders
    makes the boundary explicit: a recommendation to order, defer or review a
    PO never mutates the merchant's procurement system.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='procurement_portfolio_runs')
    horizon_days = models.PositiveIntegerField(default=90)
    input_lineage_json = models.JSONField(default=dict, blank=True)
    result_snapshot_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'procurement_portfolio_runs'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['workspace', 'created_at'], name='procure_portfolio_ws_at_idx')]


class SupplierReturnRequest(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_PENDING_APPROVAL = 'PENDING_APPROVAL'
    STATUS_APPROVED = 'APPROVED'
    STATUS_SUBMITTED = 'SUBMITTED'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='supplier_return_requests')
    action_plan = models.ForeignKey('supplyforge.ActionPlanRecord', on_delete=models.SET_NULL, null=True, blank=True, related_name='supplier_return_requests')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='return_requests')
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='return_requests')
    canonical_sku = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    reason = models.TextField()
    source_picking_external_id = models.CharField(max_length=128, blank=True, default='')
    external_product_id = models.CharField(max_length=128, blank=True, default='')
    status = models.CharField(max_length=32, default=STATUS_DRAFT, db_index=True)
    approved_by = models.CharField(max_length=128, blank=True, default='')
    approved_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True, default='')
    external_return_id = models.CharField(max_length=128, blank=True, default='')
    last_error = models.CharField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'supplier_return_requests'
        constraints = [models.UniqueConstraint(fields=['workspace', 'idempotency_key'], name='supplier_return_idempotency_uq')]
