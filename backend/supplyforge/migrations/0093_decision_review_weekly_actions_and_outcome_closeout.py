import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0092_action_plan_override_reason_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='actionplanrecord',
            name='outcome_review_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='outcome_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='DecisionReviewRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workspace_id', models.IntegerField(db_index=True)),
                ('status', models.CharField(choices=[('READY', 'Đủ điều kiện thực thi'), ('NEEDS_RECHECK', 'Cần xem lại'), ('DATA_NEEDED', 'Cần bổ sung dữ liệu')], db_index=True, max_length=24)),
                ('baseline_snapshot_json', models.JSONField(blank=True, default=dict)),
                ('current_snapshot_json', models.JSONField(blank=True, default=dict)),
                ('changes_json', models.JSONField(blank=True, default=list)),
                ('summary', models.CharField(blank=True, default='', max_length=500)),
                ('reviewed_by', models.CharField(blank=True, default='', max_length=128)),
                ('review_note', models.TextField(blank=True, default='')),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('decision', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='review_records', to='supplyforge.decisionrecord')),
            ],
            options={
                'db_table': 'decision_review_records',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='decisionreviewrecord',
            index=models.Index(fields=['workspace_id', 'decision', 'created_at'], name='decision_review_ws_dec_at_idx'),
        ),
        migrations.AddIndex(
            model_name='decisionreviewrecord',
            index=models.Index(fields=['workspace_id', 'status', 'created_at'], name='decision_review_ws_stat_at_idx'),
        ),
        migrations.CreateModel(
            name='WeeklyActionRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workspace_id', models.IntegerField(db_index=True)),
                ('week_start', models.DateField(db_index=True)),
                ('week_end', models.DateField(db_index=True)),
                ('source_snapshot_json', models.JSONField(blank=True, default=dict)),
                ('created_by', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('portfolio_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='weekly_action_runs', to='supplyforge.decisionportfoliorun')),
            ],
            options={
                'db_table': 'weekly_action_runs',
                'ordering': ['-week_start', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='weeklyactionrun',
            index=models.Index(fields=['workspace_id', 'week_start', 'created_at'], name='weekly_action_ws_week_at_idx'),
        ),
        migrations.CreateModel(
            name='WeeklyActionItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision_id_snapshot', models.CharField(db_index=True, max_length=128)),
                ('sku', models.CharField(db_index=True, max_length=128)),
                ('strategy', models.CharField(blank=True, default='', max_length=64)),
                ('state', models.CharField(choices=[('READY', 'Sẵn sàng xử lý'), ('NEEDS_OWNER', 'Cần giao người phụ trách'), ('BLOCKED', 'Đang bị chặn'), ('DEFERRED', 'Chưa làm trong kỳ này')], db_index=True, max_length=24)),
                ('owner_label', models.CharField(blank=True, default='', max_length=128)),
                ('due_date', models.DateField(blank=True, db_index=True, null=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('reasons_json', models.JSONField(blank=True, default=list)),
                ('next_step', models.CharField(blank=True, default='', max_length=500)),
                ('source_item_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('decision', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='weekly_action_items', to='supplyforge.decisionrecord')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='weekly_action_items', to='supplyforge.user')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='supplyforge.weeklyactionrun')),
            ],
            options={
                'db_table': 'weekly_action_items',
                'ordering': ['sort_order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='weeklyactionitem',
            constraint=models.UniqueConstraint(fields=('run', 'decision_id_snapshot'), name='weekly_action_run_decision_uq'),
        ),
        migrations.AddIndex(
            model_name='weeklyactionitem',
            index=models.Index(fields=['run', 'state', 'sort_order'], name='weekly_action_run_state_idx'),
        ),
        migrations.AddIndex(
            model_name='weeklyactionitem',
            index=models.Index(fields=['owner', 'due_date', 'state'], name='weekly_action_owner_due_idx'),
        ),
    ]
