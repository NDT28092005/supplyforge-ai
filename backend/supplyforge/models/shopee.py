"""
Shopee Integration — Database Models
=====================================
Defines 6 tables for persisting Shopee connection credentials,
synced product/variation/order data, and audit sync logs.

Design decisions:
  - ShopeeVariation is the source of truth for stock & price (not ShopeeProduct).
  - cost_price on ShopeeVariation is nullable: Shopee API never provides COGS.
  - item_id, model_id, order_sn carry db_index=True / unique constraints
    to prevent full-table scans during select_for_update() lookups.
"""

from django.db import models
from .user import User


class ShopeeConnection(models.Model):
    """
    Stores OAuth2 credentials for a linked Shopee shop.
    One user can connect multiple shops.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='shopee_connections',
        db_column='user_id',
    )
    shop_id = models.BigIntegerField(unique=True, help_text='Shopee shop_id')
    shop_name = models.CharField(max_length=255, blank=True, default='')
    access_token = models.CharField(max_length=512)
    refresh_token = models.CharField(max_length=512)
    token_expire_at = models.DateTimeField(
        help_text='UTC timestamp when access_token expires'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shopee_connections'

    def __str__(self) -> str:
        return f'ShopeeConn #{self.shop_id} ({self.shop_name})'


class ShopeeProduct(models.Model):
    """
    Parent-level product synced from Shopee.
    Business rule: analysis MUST be performed at variation (model) level,
    never aggregated at product (item) level.
    """

    connection = models.ForeignKey(
        ShopeeConnection,
        on_delete=models.CASCADE,
        related_name='products',
        db_column='connection_id',
    )
    # db_index=True — critical for select_for_update() and webhook lookups
    item_id = models.BigIntegerField(db_index=True)
    item_name = models.CharField(max_length=512, blank=True, default='')
    item_sku = models.CharField(max_length=255, blank=True, default='')
    item_status = models.CharField(
        max_length=32,
        default='NORMAL',
        help_text='NORMAL | BANNED | DELETED | UNLIST',
    )
    category_id = models.BigIntegerField(null=True, blank=True)
    image_url = models.URLField(max_length=1024, blank=True, default='')
    shopee_updated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='update_time from Shopee API, used for delta sync cursor',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shopee_products'
        # Composite unique: same item cannot appear twice under same connection
        unique_together = ('connection', 'item_id')

    def __str__(self) -> str:
        return f'{self.item_name} (item:{self.item_id})'


class ShopeeVariation(models.Model):
    """
    Variation (model) level — the atomic unit of inventory tracking.
    stock, price live here. cost_price is nullable because Shopee API
    never provides COGS; a SyncLog warning is generated for every
    variation missing this value.
    """

    product = models.ForeignKey(
        ShopeeProduct,
        on_delete=models.CASCADE,
        related_name='variations',
        db_column='product_id',
    )
    # db_index=True — critical for select_for_update() during webhook stock updates
    model_id = models.BigIntegerField(db_index=True)
    model_name = models.CharField(max_length=512, blank=True, default='')
    model_sku = models.CharField(max_length=255, blank=True, default='')
    price = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    stock = models.IntegerField(default=0)

    # Nullable: Shopee never returns cost. System must flag this.
    cost_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Must be manually provided; Shopee API does not supply COGS.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shopee_variations'
        unique_together = ('product', 'model_id')

    def __str__(self) -> str:
        return f'{self.model_name} (model:{self.model_id})'


class ShopeeOrder(models.Model):
    """
    Order header synced from Shopee.
    order_sn is indexed for fast webhook / polling lookups.
    """

    connection = models.ForeignKey(
        ShopeeConnection,
        on_delete=models.CASCADE,
        related_name='orders',
        db_column='connection_id',
    )
    # unique=True implies db_index — prevents duplicate orders and ensures
    # O(1) lookup during select_for_update()
    order_sn = models.CharField(max_length=64, unique=True)
    order_status = models.CharField(
        max_length=32,
        default='UNPAID',
        help_text='UNPAID | READY_TO_SHIP | SHIPPED | COMPLETED | CANCELLED | ...',
    )
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    buyer_username = models.CharField(max_length=255, blank=True, default='')
    shipping_carrier = models.CharField(max_length=128, blank=True, default='')
    order_created_at = models.DateTimeField(
        null=True, blank=True,
        help_text='create_time from Shopee API',
    )
    order_updated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='update_time from Shopee API',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shopee_orders'

    def __str__(self) -> str:
        return f'Order {self.order_sn} ({self.order_status})'


class ShopeeOrderItem(models.Model):
    """Line item within a Shopee order."""

    order = models.ForeignKey(
        ShopeeOrder,
        on_delete=models.CASCADE,
        related_name='items',
        db_column='order_id',
    )
    item_id = models.BigIntegerField()
    model_id = models.BigIntegerField(null=True, blank=True)
    item_name = models.CharField(max_length=512, blank=True, default='')
    item_sku = models.CharField(max_length=255, blank=True, default='')
    model_sku = models.CharField(max_length=255, blank=True, default='')
    quantity = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'shopee_order_items'

    def __str__(self) -> str:
        return f'{self.item_name} x{self.quantity}'


class SyncLog(models.Model):
    """
    Audit trail for every sync operation.
    Also used as a communication channel: entries with
    log_level='WARNING' and event_type='MISSING_COST_PRICE'
    signal downstream modules that a variation needs user input.
    """

    SYNC_TYPE_CHOICES = [
        ('PRODUCT', 'Product Sync'),
        ('ORDER', 'Order Sync'),
        ('STOCK_WEBHOOK', 'Stock Webhook'),
        ('ORDER_WEBHOOK', 'Order Webhook'),
    ]

    LOG_LEVEL_CHOICES = [
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
    ]

    connection = models.ForeignKey(
        ShopeeConnection,
        on_delete=models.CASCADE,
        related_name='sync_logs',
        db_column='connection_id',
    )
    sync_type = models.CharField(max_length=32, choices=SYNC_TYPE_CHOICES)
    log_level = models.CharField(max_length=16, choices=LOG_LEVEL_CHOICES, default='INFO')
    event_type = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='E.g. MISSING_COST_PRICE, SYNC_COMPLETED, TOKEN_REFRESHED',
    )
    message = models.TextField(blank=True, default='')
    records_processed = models.IntegerField(default=0)
    records_created = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'shopee_sync_logs'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'[{self.log_level}] {self.sync_type} — {self.event_type}'
