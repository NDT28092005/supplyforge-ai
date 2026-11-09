# Generated manually for the P0 tenant-deletion safety boundary.
import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0074_decision_status_policy_states'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantDeletionAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('status', models.CharField(choices=[('PREVIEWED', 'Previewed'), ('CONFIRMED', 'Confirmed'), ('EXECUTED', 'Executed'), ('REJECTED', 'Rejected')], default='PREVIEWED', max_length=16)),
                ('confirmation_hash', models.CharField(blank=True, default='', max_length=64)),
                ('preview_json', models.JSONField(blank=True, default=dict)),
                ('purged_counts_json', models.JSONField(blank=True, default=dict)),
                ('executed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tenant_deletion_audits', to='supplyforge.user')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='supplyforge.workspace')),
            ],
            options={'db_table': 'tenant_deletion_audits'},
        ),
        migrations.AddIndex(
            model_name='tenantdeletionaudit',
            index=models.Index(fields=['workspace', 'created_at'], name='tenant_delete_ws_created_idx'),
        ),
    ]
