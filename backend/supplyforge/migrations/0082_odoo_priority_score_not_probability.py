"""Do not persist deterministic Odoo priority scores as probabilities."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0081_slow_moving_accuracy_cohorts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='integrationoperationalriskassessment',
            name='risk_probability',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
