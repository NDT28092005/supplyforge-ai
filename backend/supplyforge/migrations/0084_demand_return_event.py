"""Store immutable SKU-level return facts for net demand calculations."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0083_slow_moving_odoo_outcome_cohorts'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemandReturnEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('platform', models.CharField(blank=True, default='', max_length=50)),
                ('warehouse_code', models.CharField(blank=True, default='', max_length=128)),
                ('original_order_id', models.CharField(blank=True, default='', max_length=255)),
                ('external_return_id', models.CharField(blank=True, default='', max_length=255)),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=18)),
                ('occurred_at', models.DateTimeField(db_index=True)),
                ('source_event_key', models.CharField(max_length=64)),
                ('source_lineage_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ingestion_session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='demand_return_events', to='supplyforge.ingestionsession')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='demand_return_events', to='supplyforge.workspace')),
            ],
            options={'db_table': 'demand_return_events'},
        ),
        migrations.AddConstraint(
            model_name='demandreturnevent',
            constraint=models.UniqueConstraint(fields=('workspace', 'source_event_key'), name='demand_return_workspace_event_uq'),
        ),
        migrations.AddIndex(
            model_name='demandreturnevent',
            index=models.Index(fields=['workspace', 'canonical_sku', 'occurred_at'], name='demand_return_ws_sku_time_idx'),
        ),
        migrations.AddIndex(
            model_name='demandreturnevent',
            index=models.Index(fields=['workspace', 'platform', 'occurred_at'], name='demand_return_ws_plat_idx'),
        ),
    ]
