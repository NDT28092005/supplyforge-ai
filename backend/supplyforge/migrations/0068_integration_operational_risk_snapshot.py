# Generated manually to keep the operational ERP source independent of CSV risk runs.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0067_erp_sku_mapping_governance'),
    ]

    operations = [
        migrations.CreateModel(
            name='IntegrationOperationalRiskSnapshot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_data_as_of', models.DateField(blank=True, null=True)),
                ('source_synced_at', models.DateTimeField(blank=True, null=True)),
                ('risk_engine_version', models.CharField(default='odoo_operational_rules_v1', max_length=64)),
                ('coverage', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(db_index=True, default='READY', max_length=20)),
                ('calculated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('connection', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='operational_risk_snapshot', to='supplyforge.integrationconnection')),
            ],
            options={'db_table': 'integration_operational_risk_snapshots'},
        ),
        migrations.CreateModel(
            name='IntegrationOperationalRiskAssessment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_sku', models.CharField(max_length=255)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('product_name', models.CharField(blank=True, default='', max_length=512)),
                ('category', models.CharField(blank=True, default='ERP', max_length=100)),
                ('risk_class', models.CharField(db_index=True, max_length=20)),
                ('risk_probability', models.FloatField()),
                ('risk_score', models.FloatField(db_index=True)),
                ('primary_signals', models.JSONField(default=list)),
                ('supporting_signals', models.JSONField(default=list)),
                ('evidence', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('mapping', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operational_assessments', to='supplyforge.integrationskumapping')),
                ('snapshot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assessments', to='supplyforge.integrationoperationalrisksnapshot')),
            ],
            options={'db_table': 'integration_operational_risk_assessments'},
        ),
        migrations.AddConstraint(
            model_name='integrationoperationalriskassessment',
            constraint=models.UniqueConstraint(fields=('snapshot', 'external_sku'), name='int_op_risk_snapshot_sku_uq'),
        ),
        migrations.AddIndex(
            model_name='integrationoperationalriskassessment',
            index=models.Index(fields=['snapshot', 'risk_class', '-risk_score'], name='int_op_risk_class_score_idx'),
        ),
        migrations.AddIndex(
            model_name='integrationoperationalriskassessment',
            index=models.Index(fields=['snapshot', '-risk_score', 'external_sku'], name='int_op_risk_score_sku_idx'),
        ),
    ]
