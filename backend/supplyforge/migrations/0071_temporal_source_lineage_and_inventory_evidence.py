"""Add auditable source lineage for temporal serving and inventory snapshots."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0070_temporal_shadow_prediction'),
    ]

    operations = [
        migrations.CreateModel(
            name='TemporalDemandSourceImport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_sha256', models.CharField(db_index=True, max_length=64)),
                ('source_name', models.CharField(max_length=255)),
                ('feature_contract_sha256', models.CharField(max_length=64)),
                ('retained_orders', models.PositiveIntegerField(default=0)),
                ('retained_items', models.PositiveIntegerField(default=0)),
                ('skipped_orders', models.PositiveIntegerField(default=0)),
                ('skipped_items', models.PositiveIntegerField(default=0)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
                ('is_current', models.BooleanField(db_index=True, default=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='temporal_demand_source_imports', to='supplyforge.workspace')),
            ],
            options={'db_table': 'temporal_demand_source_imports'},
        ),
        migrations.AddIndex(
            model_name='temporaldemandsourceimport',
            index=models.Index(fields=['workspace', 'is_current', '-imported_at'], name='temporal_source_current_idx'),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='markdown_rate',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=7, null=True),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='source_checksum',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='source_lineage_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='source_observed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='inventoryrecord',
            name='source_snapshot_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
    ]
