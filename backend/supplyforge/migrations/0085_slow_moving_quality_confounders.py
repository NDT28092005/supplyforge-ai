"""Add capital weighting and operational outcome-confounder lineage."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0084_demand_return_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='opening_capital_exposure',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='confounder_types',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='slowmovingoutcomecohort',
            name='status',
            field=models.CharField(choices=[
                ('PENDING', 'Awaiting outcome'), ('MATURED', '60-day outcome mature'),
                ('DATA_BLOCKED', 'Outcome data incomplete'),
                ('CONFOUNDED', 'Outcome confounded by an operational event'),
            ], db_index=True, default='PENDING', max_length=20),
        ),
        migrations.CreateModel(
            name='SlowMovingDispositionEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('CSV', 'CSV'), ('ODOO', 'Odoo')], max_length=16)),
                ('source_key', models.CharField(max_length=128)),
                ('source_scope_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('event_type', models.CharField(choices=[
                    ('STOCKOUT', 'Stockout'), ('DELISTED', 'Delisted'),
                    ('STOCK_TRANSFER', 'Stock transfer'), ('SUPPLIER_RETURN', 'Supplier return'),
                    ('INVENTORY_ADJUSTMENT', 'Inventory adjustment'),
                ], max_length=32)),
                ('occurred_at', models.DateTimeField(db_index=True)),
                ('evidence_reference', models.CharField(blank=True, default='', max_length=512)),
                ('provenance_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_disposition_events', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_disposition_events'},
        ),
        migrations.AddIndex(
            model_name='slowmovingdispositionevent',
            index=models.Index(fields=['workspace', 'source_scope_fingerprint', 'canonical_sku', 'occurred_at'], name='slow_disp_scope_sku_time_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingdispositionevent',
            index=models.Index(fields=['workspace', 'source_key', 'event_type', 'occurred_at'], name='slow_disp_source_type_time_idx'),
        ),
    ]
