"""Freeze rule and governed-candidate diagnostics on outcome cohorts."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0085_slow_moving_quality_confounders'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='rule_snapshot_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='segment_json',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='slowmovingoutcomecohort',
            name='model_diagnostic_json',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
