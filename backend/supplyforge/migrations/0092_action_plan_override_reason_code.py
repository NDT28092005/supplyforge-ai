from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0091_decision_typed_projection_queue'),
    ]

    operations = [
        migrations.AddField(
            model_name='actionplanrecord',
            name='strategy_override_reason_code',
            field=models.CharField(blank=True, db_index=True, default='', max_length=48),
        ),
    ]
