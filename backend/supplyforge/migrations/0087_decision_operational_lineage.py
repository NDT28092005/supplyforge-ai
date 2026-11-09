from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0086_slow_moving_model_shadow_diagnostics'),
    ]

    operations = [
        migrations.AddField(
            model_name='decisionrecord',
            name='analysis_as_of',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='assessment_run',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='decisions', to='supplyforge.slowmovingassessmentrun'),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='decision_evidence_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='source_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='source_scope_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='source_snapshot_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='superseded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='decisionrecord',
            name='superseded_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='superseded_decisions', to='supplyforge.decisionrecord'),
        ),
        migrations.AlterField(
            model_name='decisionrecord',
            name='status',
            field=models.CharField(choices=[('GENERATED', 'GENERATED'), ('RECOMMENDED', 'RECOMMENDED'), ('NEEDS_REVIEW', 'NEEDS_REVIEW'), ('MONITOR', 'MONITOR'), ('NOT_APPLICABLE', 'NOT_APPLICABLE'), ('REVIEWED', 'REVIEWED'), ('ACCEPTED', 'ACCEPTED'), ('REJECTED', 'REJECTED'), ('EXECUTED', 'EXECUTED'), ('COMPLETED', 'COMPLETED'), ('CANCELLED', 'CANCELLED'), ('SUPERSEDED', 'SUPERSEDED')], db_index=True, default='GENERATED', max_length=32),
        ),
        migrations.AddIndex(
            model_name='decisionrecord',
            index=models.Index(fields=['workspace_id', 'source_key', 'status', 'sku'], name='decision_ws_src_status_sku'),
        ),
        migrations.AddConstraint(
            model_name='decisionrecord',
            constraint=models.UniqueConstraint(condition=Q(('assessment_run__isnull', False)), fields=('assessment_run', 'sku'), name='decision_assessment_run_sku_uq'),
        ),
    ]
