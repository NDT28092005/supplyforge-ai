"""Keep outcome cohorts after Odoo's replace-in-place read model refreshes."""

import django.db.models.deletion
from django.db import migrations, models


def populate_source_assessment_keys(apps, schema_editor):
    """Give existing CSV cohorts a stable key before adding uniqueness."""
    Cohort = apps.get_model('supplyforge', 'SlowMovingOutcomeCohort')
    for cohort in Cohort.objects.filter(source_assessment_key='').exclude(assessment_id=None).iterator():
        cohort.source_assessment_key = f'csv:{cohort.assessment_id}'
        cohort.source_sku = cohort.canonical_sku
        cohort.save(update_fields=['source_assessment_key', 'source_sku'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0082_odoo_priority_score_not_probability'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingassessmentrun',
            name='source_snapshot_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='source_assessment_key',
            field=models.CharField(default='', max_length=192),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='source_sku',
            field=models.CharField(db_index=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='slowmovingoutcomecohort',
            name='assessment',
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='outcome_cohort', to='supplyforge.slowmovingriskassessment',
            ),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='integration_assessment',
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='outcome_cohort', to='supplyforge.integrationoperationalriskassessment',
            ),
        ),
        migrations.RunPython(populate_source_assessment_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='slowmovingoutcomecohort',
            name='source_assessment_key',
            field=models.CharField(max_length=192),
        ),
        migrations.AlterField(
            model_name='slowmovingoutcomecohort',
            name='source_sku',
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AddConstraint(
            model_name='slowmovingoutcomecohort',
            constraint=models.UniqueConstraint(
                fields=('workspace', 'source_key', 'source_assessment_key'),
                name='slow_outcome_source_assessment_uq',
            ),
        ),
    ]
