from django.db import models

from .user import Workspace


class Sku(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    original_name = models.CharField(max_length=2000)
    normalized_name = models.CharField(max_length=2000)
    is_duplicate = models.BooleanField(default=False)
    parent_sku = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, db_column='parent_sku_id')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'skus'


class InventoryRecord(models.Model):
    sku = models.ForeignKey(Sku, on_delete=models.CASCADE)
    record_date = models.DateField()
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0.0)
    cost_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    data_source = models.ForeignKey('supplyforge.DataSource', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_records'


class Product(models.Model):
    id = models.CharField(max_length=24, primary_key=True, db_column='_id')
    user_id = models.CharField(max_length=24)
    third_party_id = models.CharField(max_length=255)
    item_id = models.CharField(max_length=255, null=True, blank=True)
    product_name = models.CharField(max_length=255, null=True, blank=True)
    platform = models.CharField(max_length=50, null=True, blank=True)
    item_sku = models.CharField(max_length=255, null=True, blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    stock = models.IntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    total_revenue = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    total_profit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    total_orders = models.IntegerField(null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    images = models.JSONField(null=True, blank=True)
    active_on_web = models.BooleanField(default=True)
    expiration_date = models.DateField(null=True, blank=True)  # F&B expiration date
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'products'
        indexes = [
            # Import reconciliation and product projections are always scoped
            # by merchant before resolving a SKU.
            models.Index(
                fields=['user_id', 'item_sku'],
                name='product_user_sku_idx',
            ),
            models.Index(
                fields=['user_id', 'created_at'],
                name='product_user_created_idx',
            ),
        ]


class SkuMergeHistory(models.Model):
    parent_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='merge_children_history', db_column='parent_product_id')
    child_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='merge_parent_history', db_column='child_product_id')
    original_child_stock = models.IntegerField(default=0)
    original_child_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0.00)
    merged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sku_merge_history'


class IgnoredSkuPair(models.Model):
    sku_a_id = models.CharField(max_length=24)
    sku_b_id = models.CharField(max_length=24)
    user_id = models.CharField(max_length=24)
    ignored_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ignored_sku_pairs'
        unique_together = ('sku_a_id', 'sku_b_id', 'user_id')
