"""Add Vietnam commerce connections and source-health governance."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


def mark_existing_odoo_service_accounts(apps, schema_editor):
    Connection = apps.get_model('supplyforge', 'IntegrationConnection')
    Connection.objects.filter(provider='ODOO').update(auth_mode='SERVICE_ACCOUNT')


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0077_actionplan_execution_pricing_procurement'),
    ]

    operations = [
        migrations.AlterField(
            model_name='integrationconnection',
            name='provider',
            field=models.CharField(
                choices=[
                    ('SHOPEE', 'Shopee'), ('TIKTOK_SHOP', 'TikTok Shop'),
                    ('LAZADA', 'Lazada'), ('HARAVAN', 'Haravan'),
                    ('SAPO', 'Sapo'), ('KIOTVIET', 'KiotViet'), ('ODOO', 'Odoo'),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='integrationconnection',
            name='base_url',
            field=models.URLField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='integrationconnection',
            name='auth_mode',
            field=models.CharField(
                choices=[
                    ('OAUTH', 'OAuth'), ('API_KEY', 'API key'),
                    ('SERVICE_ACCOUNT', 'Service account'),
                ],
                default='OAUTH',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='integrationconnection',
            name='provider_config_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='integrationconnection',
            name='sync_interval_minutes',
            field=models.PositiveSmallIntegerField(default=15),
        ),
        migrations.AddIndex(
            model_name='integrationconnection',
            index=models.Index(fields=['status', 'last_successful_sync_at'], name='int_conn_status_sync_idx'),
        ),
        migrations.RunPython(mark_existing_odoo_service_accounts, migrations.RunPython.noop),
        migrations.CreateModel(
            name='IntegrationOAuthState',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('state', models.CharField(max_length=128, unique=True)),
                ('code_verifier_encrypted', models.TextField(blank=True, default='')),
                ('redirect_uri', models.URLField(max_length=512)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='oauth_states', to='supplyforge.integrationconnection')),
            ],
            options={'db_table': 'integration_oauth_states'},
        ),
        migrations.CreateModel(
            name='WorkspaceInventoryPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('variance_absolute_threshold', models.DecimalField(decimal_places=4, default=2, max_digits=18)),
                ('variance_rate_threshold', models.DecimalField(decimal_places=6, default='0.02', max_digits=8)),
                ('updated_by', models.CharField(blank=True, default='', max_length=128)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('inventory_master_connection', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_master_for_workspaces', to='supplyforge.integrationconnection')),
                ('workspace', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='inventory_policy', to='supplyforge.workspace')),
            ],
            options={'db_table': 'workspace_inventory_policies'},
        ),
        migrations.CreateModel(
            name='IntegrationDataHealthSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_data_as_of', models.DateTimeField(blank=True, null=True)),
                ('source_observed_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(db_index=True, default='NO_DATA', max_length=32)),
                ('mapped_sku_count', models.PositiveIntegerField(default=0)),
                ('total_sku_count', models.PositiveIntegerField(default=0)),
                ('mapping_coverage_rate', models.DecimalField(decimal_places=6, default=0, max_digits=8)),
                ('verified_inventory_sku_count', models.PositiveIntegerField(default=0)),
                ('missing_cost_sku_count', models.PositiveIntegerField(default=0)),
                ('inconsistency_alert_count', models.PositiveIntegerField(default=0)),
                ('details_json', models.JSONField(blank=True, default=dict)),
                ('calculated_at', models.DateTimeField(auto_now=True)),
                ('connection', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='data_health', to='supplyforge.integrationconnection')),
            ],
            options={'db_table': 'integration_data_health_snapshots'},
        ),
        migrations.CreateModel(
            name='InventoryConsistencyAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('master_quantity', models.DecimalField(decimal_places=4, max_digits=18)),
                ('compared_quantity', models.DecimalField(decimal_places=4, max_digits=18)),
                ('variance_quantity', models.DecimalField(decimal_places=4, max_digits=18)),
                ('variance_rate', models.DecimalField(decimal_places=6, max_digits=12)),
                ('status', models.CharField(choices=[('OPEN', 'Open'), ('ACKNOWLEDGED', 'Acknowledged'), ('RESOLVED', 'Resolved')], db_index=True, default='OPEN', max_length=32)),
                ('last_detected_at', models.DateTimeField(auto_now=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolution_note', models.CharField(blank=True, default='', max_length=500)),
                ('compared_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='compared_inventory_alerts', to='supplyforge.integrationconnection')),
                ('inventory_master_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='master_inventory_alerts', to='supplyforge.integrationconnection')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inventory_consistency_alerts', to='supplyforge.workspace')),
            ],
            options={'db_table': 'inventory_consistency_alerts'},
        ),
        migrations.AddIndex(
            model_name='integrationoauthstate',
            index=models.Index(fields=['connection', 'expires_at'], name='int_oauth_conn_expires_idx'),
        ),
        migrations.AddConstraint(
            model_name='inventoryconsistencyalert',
            constraint=models.UniqueConstraint(fields=('workspace', 'inventory_master_connection', 'compared_connection', 'canonical_sku'), name='inventory_consistency_pair_sku_uq'),
        ),
        migrations.AddIndex(
            model_name='inventoryconsistencyalert',
            index=models.Index(fields=['workspace', 'status', 'last_detected_at'], name='inventory_alert_ws_status_idx'),
        ),
    ]
