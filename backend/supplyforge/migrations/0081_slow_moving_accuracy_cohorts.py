"""Persist outcome cohorts and append-only feedback for slow-moving quality."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0080_slow_moving_operational_runs'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingassessmentrun',
            name='source_scope',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='slowmovingassessmentrun',
            name='source_scope_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.CreateModel(
            name='SlowMovingOutcomeCohort',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('CSV', 'CSV'), ('ODOO', 'Odoo')], max_length=16)),
                ('source_key', models.CharField(max_length=128)),
                ('source_scope', models.JSONField(blank=True, default=dict)),
                ('source_scope_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('policy_version', models.CharField(max_length=64)),
                ('policy_checksum', models.CharField(db_index=True, max_length=64)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('decision_cutoff', models.DateTimeField()),
                ('predicted_risk_class', models.CharField(max_length=20)),
                ('opened_alert', models.BooleanField(db_index=True, default=False)),
                ('opening_stock_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('opening_inventory_verified', models.BooleanField(default=False)),
                ('outcome_30_ends_at', models.DateTimeField()),
                ('outcome_60_ends_at', models.DateTimeField()),
                ('outcome_90_ends_at', models.DateTimeField()),
                ('maturity_eligible_at', models.DateTimeField(db_index=True)),
                ('status', models.CharField(choices=[('PENDING', 'Awaiting outcome'), ('MATURED', '60-day outcome mature'), ('DATA_BLOCKED', 'Outcome data incomplete')], db_index=True, default='PENDING', max_length=20)),
                ('block_reason', models.CharField(blank=True, default='', max_length=128)),
                ('future_net_fulfilled_units_30', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('future_net_fulfilled_units_60', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('future_net_fulfilled_units_90', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('outcome_30_observed_at', models.DateTimeField(blank=True, null=True)),
                ('outcome_60_observed_at', models.DateTimeField(blank=True, null=True)),
                ('outcome_90_observed_at', models.DateTimeField(blank=True, null=True)),
                ('label_revision', models.PositiveIntegerField(default=0)),
                ('label_revision_reason', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('alert_state', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='outcome_cohorts', to='supplyforge.slowmovingalertstate')),
                ('assessment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='outcome_cohort', to='supplyforge.slowmovingriskassessment')),
                ('assessment_run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='outcome_cohorts', to='supplyforge.slowmovingassessmentrun')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_outcome_cohorts', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_outcome_cohorts'},
        ),
        migrations.CreateModel(
            name='SlowMovingAlertFeedback',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(max_length=20)),
                ('reason', models.CharField(choices=[('ACCEPTED', 'Accepted'), ('DATA_INCORRECT', 'Data incorrect'), ('STOCK_ALREADY_MOVED', 'Stock already moved'), ('SEASONAL_ITEM', 'Seasonal item'), ('PLANNED_CAMPAIGN', 'Planned campaign'), ('NOT_RELEVANT', 'Not relevant'), ('SNOOZED', 'Snoozed'), ('RESOLVED', 'Resolved')], max_length=32)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('evidence_reference', models.CharField(blank=True, default='', max_length=512)),
                ('submitted_by', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('alert_state', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback_events', to='supplyforge.slowmovingalertstate')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_alert_feedback', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_alert_feedback'},
        ),
        migrations.AddIndex(
            model_name='slowmovingoutcomecohort',
            index=models.Index(fields=['workspace', 'source_key', 'policy_checksum', 'maturity_eligible_at'], name='slow_outcome_maturity_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingoutcomecohort',
            index=models.Index(fields=['workspace', 'source_scope_fingerprint', 'decision_cutoff'], name='slow_outcome_scope_cutoff_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingoutcomecohort',
            index=models.Index(fields=['workspace', 'opened_alert', 'status'], name='slow_outcome_open_status_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertfeedback',
            index=models.Index(fields=['workspace', 'reason', '-created_at'], name='slow_feedback_reason_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertfeedback',
            index=models.Index(fields=['alert_state', '-created_at'], name='slow_feedback_alert_idx'),
        ),
    ]
