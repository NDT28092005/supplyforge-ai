"""Retire marketplace integrations and retain Odoo as the sole live source."""

from django.db import migrations, models


def remove_non_odoo_connections(apps, schema_editor):
    """Purge credentials and operational facts for retired providers first."""
    IntegrationConnection = apps.get_model('supplyforge', 'IntegrationConnection')
    IntegrationConnection.objects.exclude(provider='ODOO').delete()


def set_odoo_service_account_auth(apps, schema_editor):
    IntegrationConnection = apps.get_model('supplyforge', 'IntegrationConnection')
    IntegrationConnection.objects.filter(provider='ODOO').update(auth_mode='SERVICE_ACCOUNT')


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0078_commerce_marketplace_integrations'),
    ]

    operations = [
        migrations.RunPython(remove_non_odoo_connections, migrations.RunPython.noop),
        migrations.DeleteModel(name='InventoryConsistencyAlert'),
        migrations.DeleteModel(name='WorkspaceInventoryPolicy'),
        migrations.DeleteModel(name='IntegrationOAuthState'),
        migrations.DeleteModel(name='ShopeeVariation'),
        migrations.DeleteModel(name='ShopeeOrderItem'),
        migrations.DeleteModel(name='ShopeeOrder'),
        migrations.DeleteModel(name='ShopeeProduct'),
        migrations.DeleteModel(name='SyncLog'),
        migrations.DeleteModel(name='ShopeeConnection'),
        migrations.RemoveField(
            model_name='integrationdatahealthsnapshot',
            name='inconsistency_alert_count',
        ),
        migrations.RemoveField(
            model_name='integrationconnection',
            name='provider_config_json',
        ),
        migrations.RunPython(set_odoo_service_account_auth, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='integrationconnection',
            name='provider',
            field=models.CharField(choices=[('ODOO', 'Odoo')], max_length=32),
        ),
        migrations.AlterField(
            model_name='integrationconnection',
            name='auth_mode',
            field=models.CharField(
                choices=[('SERVICE_ACCOUNT', 'Service account')],
                default='SERVICE_ACCOUNT',
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='integrationsyncrun',
            name='run_type',
            field=models.CharField(
                choices=[
                    ('VALIDATE', 'Validate'),
                    ('INITIAL', 'Initial'),
                    ('INCREMENTAL', 'Incremental'),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='backgroundjob',
            name='job_type',
            field=models.CharField(
                choices=[
                    ('CSV_IMPORT', 'CSV Import Pipeline'),
                    ('ML_RETRAIN', 'Model Retraining'),
                    ('FEATURE_REFRESH', 'Feature Store Refresh'),
                    ('MODEL_EVALUATION', 'Model Offline Evaluation'),
                    ('DATA_EXPORT', 'Data Export'),
                    ('REPORT_GENERATION', 'Report Generation'),
                    ('INTEGRATION_SYNC', 'ERP Integration Sync'),
                ],
                max_length=32,
            ),
        ),
    ]
