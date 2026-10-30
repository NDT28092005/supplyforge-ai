"""Operational action-queue fields, tenant scope, and immutable event trail."""

from datetime import timedelta

from django.db import migrations, models


def backfill_due_dates(apps, schema_editor):
    ActionPlan = apps.get_model('supplyforge', 'ActionPlanRecord')
    for plan in ActionPlan.objects.filter(due_date__isnull=True).iterator():
        plan.due_date = plan.start_date + timedelta(days=max(1, plan.duration_days or 1))
        plan.save(update_fields=['due_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0063_ingestionsession_archived_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='actionplanrecord',
            name='workspace_id',
            field=models.IntegerField(db_index=True, default=1),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='due_date',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='outcome_notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='actionplanrecord',
            name='decision_id',
            field=models.CharField(blank=True, db_index=True, max_length=128, null=True),
        ),
        migrations.CreateModel(
            name='ActionPlanEventRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(db_index=True, max_length=64)),
                ('old_status', models.CharField(blank=True, max_length=32, null=True)),
                ('new_status', models.CharField(blank=True, max_length=32, null=True)),
                ('actor', models.CharField(default='system', max_length=128)),
                ('notes', models.TextField(blank=True, default='')),
                ('metadata', models.JSONField(default=dict)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('plan', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='events', to='supplyforge.actionplanrecord')),
            ],
            options={
                'db_table': 'action_plan_events',
                'ordering': ['timestamp'],
            },
        ),
        migrations.RunPython(backfill_due_dates, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='actionplanrecord',
            index=models.Index(fields=['workspace_id', 'status', 'due_date'], name='action_plan_ws_status_due_idx'),
        ),
        migrations.AddIndex(
            model_name='actionplanrecord',
            index=models.Index(fields=['workspace_id', 'sku'], name='action_plan_ws_sku_idx'),
        ),
    ]
