from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0094_slow_moving_alert_trust_context'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='priority_score',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='sellable_stock_quantity',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='capital_exposure_vnd',
            field=models.DecimalField(blank=True, db_index=True, decimal_places=2, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='days_since_last_sale',
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingriskassessment',
            name='eligibility_status',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(fields=['assessment_run', 'risk_class', '-capital_exposure_vnd', 'sku'], name='risk_run_class_cap_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(fields=['assessment_run', 'risk_class', '-days_since_last_sale', 'sku'], name='risk_run_class_dsls_sku_idx'),
        ),
    ]
