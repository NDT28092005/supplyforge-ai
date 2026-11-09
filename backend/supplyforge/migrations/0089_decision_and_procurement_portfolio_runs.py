import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0088_action_plan_scope_lock'),
    ]

    operations = [
        migrations.CreateModel(
            name='DecisionPortfolioRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workspace_id', models.IntegerField(db_index=True)),
                ('policy_version', models.CharField(max_length=64)),
                ('policy_checksum', models.CharField(max_length=64)),
                ('input_config_json', models.JSONField(blank=True, default=dict)),
                ('input_decision_ids_json', models.JSONField(blank=True, default=list)),
                ('result_snapshot_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'decision_portfolio_runs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='decisionportfoliorun',
            index=models.Index(fields=['workspace_id', 'created_at'], name='decision_portfolio_ws_at_idx'),
        ),
        migrations.CreateModel(
            name='ProcurementPortfolioRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('horizon_days', models.PositiveIntegerField(default=90)),
                ('input_lineage_json', models.JSONField(blank=True, default=dict)),
                ('result_snapshot_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='procurement_portfolio_runs', to='supplyforge.workspace')),
            ],
            options={
                'db_table': 'procurement_portfolio_runs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='procurementportfoliorun',
            index=models.Index(fields=['workspace', 'created_at'], name='procure_portfolio_ws_at_idx'),
        ),
    ]
