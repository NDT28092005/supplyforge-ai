"""Add accountable assignment and sales outcome evidence to action plans."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0064_action_plan_operational_queue'),
    ]

    operations = [
        migrations.AddField(
            model_name='actionplanrecord',
            name='assignee_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_action_plans',
                to='supplyforge.user',
            ),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='expected_sales_value',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='actionplanrecord',
            name='actual_sales_value',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
