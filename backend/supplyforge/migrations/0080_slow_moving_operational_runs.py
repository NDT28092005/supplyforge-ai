"""Bind merchant slow-moving results to immutable operational runs."""

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0079_remove_marketplace_integrations'),
    ]

    operations = [
        migrations.CreateModel(
            name='SlowMovingAssessmentRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('CSV', 'CSV'), ('ODOO', 'Odoo')], max_length=16)),
                ('source_key', models.CharField(max_length=128)),
                ('analysis_as_of', models.DateTimeField()),
                ('source_freshness', models.JSONField(blank=True, default=dict)),
                ('policy_version', models.CharField(max_length=64)),
                ('policy_checksum', models.CharField(max_length=64)),
                ('summary', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('BUILDING', 'Building'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')], db_index=True, default='BUILDING', max_length=16)),
                ('is_current', models.BooleanField(db_index=True, default=False)),
                ('failure_reason', models.CharField(blank=True, default='', max_length=512)),
                ('started_at', models.DateTimeField(default=timezone.now)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('dataset_version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slow_moving_assessment_runs', to='supplyforge.datasetversion')),
                ('integration_connection', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='slow_moving_assessment_runs', to='supplyforge.integrationconnection')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_assessment_runs', to='supplyforge.workspace')),
            ],
            options={
                'db_table': 'slow_moving_assessment_runs',
                'ordering': ['-completed_at', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SlowMovingAlertState',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('CSV', 'CSV'), ('ODOO', 'Odoo')], max_length=16)),
                ('source_key', models.CharField(max_length=128)),
                ('canonical_sku', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('CANDIDATE', 'Awaiting confirmation'), ('OPEN', 'Open'), ('ACKNOWLEDGED', 'Acknowledged'), ('SNOOZED', 'Snoozed'), ('RESOLVED', 'Resolved'), ('DATA_BLOCKED', 'Data blocked')], db_index=True, default='CANDIDATE', max_length=20)),
                ('consecutive_eligible_runs', models.PositiveSmallIntegerField(default=0)),
                ('first_detected_at', models.DateTimeField(default=timezone.now)),
                ('last_detected_at', models.DateTimeField(default=timezone.now)),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
                ('snoozed_until', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolution_note', models.CharField(blank=True, default='', max_length=500)),
                ('feedback', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_assessment_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alert_states', to='supplyforge.slowmovingassessmentrun')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_alert_states', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_alert_states'},
        ),
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='assessment_run',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assessments', to='supplyforge.slowmovingassessmentrun'),
        ),
        migrations.AlterField(
            model_name='slowmovingriskassessment',
            name='risk_probability',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name='slowmovingassessmentrun',
            index=models.Index(fields=['workspace', 'source_type', 'status'], name='slow_run_ws_source_status_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingassessmentrun',
            index=models.Index(fields=['workspace', 'source_key', '-completed_at'], name='slow_run_ws_key_completed_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingassessmentrun',
            index=models.Index(fields=['dataset_version'], name='slow_run_dataset_idx'),
        ),
        migrations.AddConstraint(
            model_name='slowmovingassessmentrun',
            constraint=models.UniqueConstraint(condition=Q(is_current=True), fields=('workspace', 'source_key'), name='slow_moving_one_current_source_run'),
        ),
        migrations.AddConstraint(
            model_name='slowmovingalertstate',
            constraint=models.UniqueConstraint(fields=('workspace', 'source_key', 'canonical_sku'), name='slow_moving_alert_source_sku_uq'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertstate',
            index=models.Index(fields=['workspace', 'status', '-last_detected_at'], name='slow_alert_ws_status_seen_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertstate',
            index=models.Index(fields=['source_key', 'canonical_sku'], name='slow_alert_source_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(fields=['assessment_run', 'risk_class', '-risk_score'], name='risk_run_class_score_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(fields=['assessment_run', '-risk_score', 'sku'], name='risk_run_score_sku_idx'),
        ),
    ]
