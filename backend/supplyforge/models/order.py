from django.db import models


class Order(models.Model):
    id = models.CharField(max_length=24, primary_key=True, db_column='_id')
    user_id = models.CharField(max_length=24)
    order_id = models.CharField(max_length=255)
    platform = models.CharField(max_length=50, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    buyer_user_name = models.CharField(max_length=255, null=True, blank=True)
    cancelled_after_packaged = models.BooleanField(default=False)
    data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'orders'
        indexes = [
            # Time-windowed sales features first narrow by merchant, then by
            # source event time.
            models.Index(
                fields=['user_id', 'created_at'],
                name='order_user_created_idx',
            ),
        ]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', db_column='order_id')
    item_id = models.CharField(max_length=255, null=True, blank=True)
    model_id = models.CharField(max_length=255, null=True, blank=True)
    sku = models.CharField(max_length=255, null=True, blank=True)
    product_name = models.TextField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'order_items'
        indexes = [
            # Supports SKU-level fallback lookup without scanning all items.
            models.Index(fields=['sku'], name='order_item_sku_idx'),
        ]
