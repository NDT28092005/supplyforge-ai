"""Keep the approved execution parameters with each action-plan audit trail."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0072_temporal_promotion_and_action_observation'),
    ]

    operations = [
        migrations.AddField(
            model_name='actionplanrecord',
            name='action_parameters',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='strategy_override_reason',
            field=models.TextField(blank=True, default=''),
        ),
    ]
