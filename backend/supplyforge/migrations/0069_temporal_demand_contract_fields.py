"""Add explicit source fields required by the temporal demand-risk contract."""

from django.db import migrations, models


def backfill_stable_sku_fields(apps, schema_editor):
    Product = apps.get_model('supplyforge', 'Product')
    OrderItem = apps.get_model('supplyforge', 'OrderItem')

    for product in Product.objects.filter(canonical_sku__isnull=True).exclude(item_sku__isnull=True).iterator():
        product.canonical_sku = product.item_sku
        product.save(update_fields=['canonical_sku'])
    for item in OrderItem.objects.filter(canonical_sku__isnull=True).exclude(sku__isnull=True).iterator():
        item.canonical_sku = item.sku
        item.save(update_fields=['canonical_sku'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0068_integration_operational_risk_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='status',
            field=models.CharField(db_index=True, default='UNKNOWN', max_length=32),
        ),
        migrations.AddField(
            model_name='order',
            name='return_identifier',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='is_accounting',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='order',
            name='warehouse_code',
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='source_event_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='demand_eligibility_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='canonical_sku',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='canonical_sku',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='canonical_sku',
            field=models.CharField(blank=True, db_index=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='warehouse_code',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='available_quantity',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='reserved_quantity',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='lifecycle_status',
            field=models.CharField(blank=True, default='UNKNOWN', max_length=32),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='as_of_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['user_id', 'status', 'source_event_at'], name='order_user_status_event_idx'),
        ),
        migrations.AddIndex(
            model_name='orderitem',
            index=models.Index(fields=['canonical_sku'], name='order_item_canonical_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['user_id', 'canonical_sku'], name='product_user_canonical_sku_idx'),
        ),
        migrations.RunPython(backfill_stable_sku_fields, migrations.RunPython.noop),
    ]
