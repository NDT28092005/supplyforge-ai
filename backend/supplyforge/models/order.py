import uuid

from django.db import models


class Order(models.Model):
    id = models.CharField(max_length=24, primary_key=True, db_column='_id')
    user_id = models.CharField(max_length=24)
    # Source identities can be shared by multiple workspaces. Keeping this
    # explicit prevents reads, upserts and deletion from crossing that boundary.
    workspace = models.ForeignKey(
        'supplyforge.Workspace',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='orders',
    )
    order_id = models.CharField(max_length=255)
    platform = models.CharField(max_length=50, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    buyer_user_name = models.CharField(max_length=255, null=True, blank=True)
    cancelled_after_packaged = models.BooleanField(default=False)
    # Operational-demand contract.  These fields are intentionally explicit:
    # the temporal model must never infer completion or return status from
    # buyer data or an unversioned JSON payload.
    status = models.CharField(max_length=32, default='UNKNOWN', db_index=True)
    return_identifier = models.CharField(max_length=255, null=True, blank=True)
    is_accounting = models.BooleanField(default=False)
    warehouse_code = models.CharField(max_length=128, null=True, blank=True)
    source_event_at = models.DateTimeField(null=True, blank=True)
    demand_eligibility_verified = models.BooleanField(default=False)
    data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'orders'
        indexes = [
            models.Index(
                fields=['workspace', 'created_at'],
                name='order_workspace_created_idx',
            ),
            models.Index(
                fields=['workspace', 'status', 'source_event_at'],
                name='order_ws_status_event_idx',
            ),
            # Time-windowed sales features first narrow by merchant, then by
            # source event time.
            models.Index(
                fields=['user_id', 'created_at'],
                name='order_user_created_idx',
            ),
            models.Index(
                fields=['user_id', 'status', 'source_event_at'],
                name='order_user_status_event_idx',
            ),
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', db_column='order_id')
    item_id = models.CharField(max_length=255, null=True, blank=True)
    model_id = models.CharField(max_length=255, null=True, blank=True)
    sku = models.CharField(max_length=255, null=True, blank=True)
    # Stable merchant SKU used by temporal training and runtime feature
    # extraction. Raw marketplace identifiers remain available separately.
    canonical_sku = models.CharField(max_length=255, null=True, blank=True)
    product_name = models.TextField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'order_items'
        indexes = [
            # Supports SKU-level fallback lookup without scanning all items.
            models.Index(fields=['sku'], name='order_item_sku_idx'),
            models.Index(fields=['canonical_sku'], name='order_item_canonical_sku_idx'),
        ]


class DemandReturnEvent(models.Model):
    """Immutable SKU-level return fact used to calculate net fulfilled demand.

    ``Order.return_identifier`` cannot express partial returns or a return that
    arrives after the original sale.  This ledger deliberately records the
    return at its own event time and leaves the original qualified sale intact.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='demand_return_events'
    )
    ingestion_session = models.ForeignKey(
        'supplyforge.IngestionSession', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demand_return_events',
    )
    canonical_sku = models.CharField(max_length=255, db_index=True)
    platform = models.CharField(max_length=50, blank=True, default='')
    warehouse_code = models.CharField(max_length=128, blank=True, default='')
    original_order_id = models.CharField(max_length=255, blank=True, default='')
    external_return_id = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    occurred_at = models.DateTimeField(db_index=True)
    # A deterministic source-event digest makes streaming retries idempotent.
    source_event_key = models.CharField(max_length=64)
    source_lineage_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'demand_return_events'
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source_event_key'],
                name='demand_return_workspace_event_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'canonical_sku', 'occurred_at'],
                name='demand_return_ws_sku_time_idx',
            ),
            models.Index(
                fields=['workspace', 'platform', 'occurred_at'], name='demand_return_ws_plat_idx',
            ),
        ]
