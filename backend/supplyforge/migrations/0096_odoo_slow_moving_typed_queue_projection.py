from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0095_slow_moving_typed_queue_projection'),
    ]

    operations = [
        migrations.AddField(
            model_name='integrationoperationalriskassessment',
            name='priority_score',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='integrationoperationalriskassessment',
            name='sellable_stock_quantity',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='integrationoperationalriskassessment',
            name='capital_exposure_vnd',
            field=models.DecimalField(blank=True, db_index=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='integrationoperationalriskassessment',
            name='days_since_last_sale',
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='integrationoperationalriskassessment',
            name='eligibility_status',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddIndex(
            model_name='integrationoperationalriskassessment',
            index=models.Index(
                fields=['snapshot', 'risk_class', '-capital_exposure_vnd', 'external_sku'],
                name='int_op_risk_class_cap_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='integrationoperationalriskassessment',
            index=models.Index(
                fields=['snapshot', 'risk_class', '-days_since_last_sale', 'external_sku'],
                name='int_op_risk_class_dsls_idx',
            ),
        ),
    ]
