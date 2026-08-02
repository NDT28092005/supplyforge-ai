from django.contrib import admin
from supplyforge.models import (
    User, Workspace, WorkspaceMember,
    Product, Sku, InventoryRecord, SkuMergeHistory, IgnoredSkuPair,
    Order, OrderItem,
    DataSource,
    InsightAnomaly,
)

admin.site.register(User)
admin.site.register(Workspace)
admin.site.register(WorkspaceMember)
admin.site.register(Product)
admin.site.register(Sku)
admin.site.register(InventoryRecord)
admin.site.register(SkuMergeHistory)
admin.site.register(IgnoredSkuPair)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(DataSource)
admin.site.register(InsightAnomaly)
