from django.db import models

class User(models.Model):
    email = models.EmailField(max_length=320, unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    display_name = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email


class Workspace(models.Model):
    name = models.CharField(max_length=200)
    slug = models.CharField(max_length=80, unique=True, null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_column='owner_user_id')
    gemini_api_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspaces'

    def __str__(self):
        return self.name


class WorkspaceMember(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=32, default='MEMBER')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_members'
        unique_together = ('workspace', 'user')


class DataSource(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    original_filename = models.CharField(max_length=512)
    storage_key = models.CharField(max_length=1024)
    content_type = models.CharField(max_length=128, null=True, blank=True)
    byte_size = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, default='PENDING')
    row_count = models.BigIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    column_mapping_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'data_sources'


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
    data_source = models.ForeignKey(DataSource, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_records'


class InsightAnomaly(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    insight_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=32, default='INFO')
    title = models.CharField(max_length=500)
    summary = models.TextField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    sku = models.ForeignKey(Sku, on_delete=models.SET_NULL, null=True, blank=True, db_column='sku_id')
    computed_at = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'insights_and_anomalies'


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
