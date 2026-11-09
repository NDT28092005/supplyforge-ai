"""Align persisted decision statuses with the recommendation policy states."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0073_action_plan_execution_parameters'),
    ]

    operations = [
        migrations.AlterField(
            model_name='decisionrecord',
            name='status',
            field=models.CharField(
                choices=[
                    ('GENERATED', 'GENERATED'),
                    ('RECOMMENDED', 'RECOMMENDED'),
                    ('NEEDS_REVIEW', 'NEEDS_REVIEW'),
                    ('MONITOR', 'MONITOR'),
                    ('NOT_APPLICABLE', 'NOT_APPLICABLE'),
                    ('REVIEWED', 'REVIEWED'),
                    ('ACCEPTED', 'ACCEPTED'),
                    ('REJECTED', 'REJECTED'),
                    ('EXECUTED', 'EXECUTED'),
                    ('COMPLETED', 'COMPLETED'),
                    ('CANCELLED', 'CANCELLED'),
                ],
                db_index=True,
                default='GENERATED',
                max_length=32,
            ),
        ),
    ]
