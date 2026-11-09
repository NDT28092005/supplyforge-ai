from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0090_decision_cursor_priority_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='decisionrecord',
            name='projection_status',
            field=models.CharField(db_index=True, default='LEGACY_UNVERIFIED', max_length=32),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='evidence_state',
            field=models.CharField(db_index=True, default='LEGACY_UNVERIFIED', max_length=32),
        ),
        migrations.AddIndex(
            model_name='decisionrecord',
            index=models.Index(
                fields=['workspace_id', 'status', 'projection_status', 'priority_score'],
                name='decision_queue_projection_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='decisionrecord',
            index=models.Index(
                fields=['workspace_id', 'status', 'evidence_state'],
                name='decision_queue_evidence_idx',
            ),
        ),
    ]
