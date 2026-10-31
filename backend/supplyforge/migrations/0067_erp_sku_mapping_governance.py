from django.db import migrations, models
import django.db.models.deletion


def backfill_mapping_products(apps, schema_editor):
    Mapping = apps.get_model('supplyforge', 'IntegrationSkuMapping')
    Product = apps.get_model('supplyforge', 'Product')

    active_statuses = ['AUTO_MAPPED', 'CONFIRMED']
    for mapping in Mapping.objects.filter(status__in=active_statuses).exclude(canonical_sku='').select_related('connection__workspace').iterator():
        owner_id = mapping.connection.workspace.owner_id
        products = list(Product.objects.filter(
            user_id=str(owner_id or ''), item_sku=mapping.canonical_sku,
        ).order_by('id')[:2])
        if len(products) == 1:
            mapping.canonical_product_id = products[0].id
        mapping.mapping_method = 'AUTO' if mapping.status == 'AUTO_MAPPED' else 'MANUAL'
        if mapping.status == 'CONFIRMED' and not mapping.confirmed_at:
            mapping.confirmed_at = mapping.updated_at
        mapping.save(update_fields=['canonical_product', 'mapping_method', 'confirmed_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0066_alter_backgroundjob_current_stage_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='integrationskumapping',
            name='canonical_product',
            field=models.ForeignKey(
                blank=True, db_column='canonical_product_id', null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='erp_sku_mappings', to='supplyforge.product',
            ),
        ),
        migrations.AddField(
            model_name='integrationskumapping',
            name='confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='integrationskumapping',
            name='ignored_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='integrationskumapping',
            name='mapping_method',
            field=models.CharField(blank=True, choices=[('AUTO', 'Automatic'), ('MANUAL', 'Manual')], default='', max_length=16),
        ),
        migrations.AddField(
            model_name='integrationskumapping',
            name='resolution_note',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.CreateModel(
            name='IntegrationSkuMappingAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[('AUTO_MAPPED', 'Automatically mapped'), ('CONFIRMED', 'Confirmed'), ('CORRECTED', 'Corrected'), ('IGNORED', 'Ignored'), ('REOPENED', 'Reopened'), ('UNLINKED', 'Unlinked')], max_length=32)),
                ('previous_canonical_product_id', models.CharField(blank=True, default='', max_length=24)),
                ('previous_canonical_sku', models.CharField(blank=True, default='', max_length=255)),
                ('canonical_product_id_snapshot', models.CharField(blank=True, default='', max_length=24)),
                ('canonical_sku', models.CharField(blank=True, default='', max_length=255)),
                ('actor', models.CharField(blank=True, default='', max_length=128)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('mapping', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audit_events', to='supplyforge.integrationskumapping')),
            ],
            options={
                'db_table': 'integration_sku_mapping_audits',
            },
        ),
        migrations.AddIndex(
            model_name='integrationskumappingaudit',
            index=models.Index(fields=['mapping', 'created_at'], name='int_map_audit_map_at_idx'),
        ),
        migrations.RunPython(backfill_mapping_products, migrations.RunPython.noop),
    ]
