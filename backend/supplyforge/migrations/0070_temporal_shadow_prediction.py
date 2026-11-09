"""Persist matureable SHADOW/CANARY temporal demand-risk prediction cohorts."""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0069_temporal_demand_contract_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='TemporalShadowPrediction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('model_version', models.CharField(db_index=True, max_length=128)),
                ('serving_state', models.CharField(max_length=16)),
                ('operating_mode', models.CharField(default='balanced', max_length=64)),
                ('feature_schema_version', models.CharField(max_length=64)),
                ('ground_truth_schema_version', models.CharField(blank=True, default='', max_length=128)),
                ('ground_truth_thresholds_json', models.JSONField(blank=True, default=dict)),
                ('decision_cutoff', models.DateTimeField()),
                ('outcome_observation_ends_at', models.DateTimeField(db_index=True)),
                ('predicted_risk_class', models.CharField(max_length=20)),
                ('high_risk_probability', models.FloatField()),
                ('raw_high_risk_probability', models.FloatField()),
                ('class_probabilities_json', models.JSONField(blank=True, default=dict)),
                ('feature_vector_json', models.JSONField(blank=True, default=dict)),
                ('source_lineage_json', models.JSONField(blank=True, default=dict)),
                ('actual_risk_class', models.CharField(blank=True, max_length=20, null=True)),
                ('actual_future_fulfilled_quantity', models.FloatField(blank=True, null=True)),
                ('outcome_observed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='temporal_shadow_predictions', to='supplyforge.workspace')),
            ],
            options={'db_table': 'temporal_shadow_predictions'},
        ),
        migrations.AddConstraint(
            model_name='temporalshadowprediction',
            constraint=models.UniqueConstraint(fields=('workspace', 'canonical_sku', 'model_version', 'decision_cutoff'), name='temporal_shadow_prediction_unique'),
        ),
        migrations.AddIndex(
            model_name='temporalshadowprediction',
            index=models.Index(fields=['workspace', 'model_version', 'outcome_observation_ends_at'], name='temporal_shadow_maturity_idx'),
        ),
        migrations.AddIndex(
            model_name='temporalshadowprediction',
            index=models.Index(fields=['workspace', 'model_version', 'decision_cutoff'], name='temporal_shadow_cohort_idx'),
        ),
    ]
