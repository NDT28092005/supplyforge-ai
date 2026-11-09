"""Govern ACTIVE temporal promotions and retain reconciled action observations."""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0071_temporal_source_lineage_and_inventory_evidence'),
    ]

    operations = [
        migrations.CreateModel(
            name='TemporalCandidatePromotionApproval',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('model_version', models.CharField(db_index=True, max_length=128)),
                ('selected_model', models.CharField(max_length=128)),
                ('benchmark_manifest_sha256', models.CharField(max_length=64)),
                ('source_sha256', models.CharField(max_length=64)),
                ('feature_contract_sha256', models.CharField(max_length=64)),
                ('promotion_policy_sha256', models.CharField(max_length=64)),
                ('shadow_report_sha256', models.CharField(max_length=64)),
                ('shadow_quality_json', models.JSONField(default=dict)),
                ('approved_by', models.CharField(max_length=128)),
                ('approval_reference', models.CharField(max_length=255)),
                ('approved_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('APPROVED', 'Approved'), ('REVOKED', 'Revoked')], db_index=True, default='APPROVED', max_length=16)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_by', models.CharField(blank=True, default='', max_length=128)),
                ('revoke_reference', models.CharField(blank=True, default='', max_length=255)),
                ('revoke_reason', models.TextField(blank=True, default='')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='temporal_candidate_promotion_approvals', to='supplyforge.workspace')),
            ],
            options={'db_table': 'temporal_candidate_promotion_approvals'},
        ),
        migrations.AddConstraint(
            model_name='temporalcandidatepromotionapproval',
            constraint=models.UniqueConstraint(fields=('workspace', 'model_version', 'benchmark_manifest_sha256'), name='temporal_promotion_approval_uq'),
        ),
        migrations.AddIndex(
            model_name='temporalcandidatepromotionapproval',
            index=models.Index(fields=['workspace', 'model_version', 'status'], name='temporal_prom_ws_model_idx'),
        ),
        migrations.CreateModel(
            name='ActionPlanOutcomeObservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('observation_start', models.DateField(blank=True, null=True)),
                ('observation_end', models.DateField(blank=True, null=True)),
                ('observed_net_units_sold', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('observed_sales_value', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('opening_inventory_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('closing_inventory_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('observed_inventory_change', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('observed_inventory_value_change', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('status', models.CharField(choices=[('OBSERVED', 'Observed'), ('PARTIAL', 'Partial'), ('UNAVAILABLE', 'Unavailable')], db_index=True, default='UNAVAILABLE', max_length=16)),
                ('missing_fields_json', models.JSONField(blank=True, default=list)),
                ('source_lineage_json', models.JSONField(blank=True, default=dict)),
                ('reconciled_at', models.DateTimeField(auto_now=True)),
                ('connection', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='action_outcome_observations', to='supplyforge.integrationconnection')),
                ('plan', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='observed_outcome', to='supplyforge.actionplanrecord')),
            ],
            options={'db_table': 'action_plan_outcome_observations'},
        ),
        migrations.AddIndex(
            model_name='actionplanoutcomeobservation',
            index=models.Index(fields=['status', 'reconciled_at'], name='action_obs_status_at_idx'),
        ),
    ]
