"""P1 indexes for tenant-scoped lists and time-windowed analytics."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0061_capital_analysis_unique_dataset'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['user_id', 'item_sku'], name='product_user_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['user_id', 'created_at'], name='product_user_created_idx'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['user_id', 'created_at'], name='order_user_created_idx'),
        ),
        migrations.AddIndex(
            model_name='orderitem',
            index=models.Index(fields=['sku'], name='order_item_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='ingestionsession',
            index=models.Index(fields=['workspace', 'created_at'], name='ingest_ws_created_idx'),
        ),
        migrations.AddIndex(
            model_name='ingestionsession',
            index=models.Index(
                fields=['workspace', 'status', 'created_at'],
                name='ingest_ws_status_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='ingestionsession',
            index=models.Index(
                fields=['workspace', 'file_hash', 'status'],
                name='ingest_ws_hash_status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='backgroundjob',
            index=models.Index(
                fields=['workspace', 'status', 'created_at'],
                name='job_ws_status_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(
                fields=['session', 'risk_class', '-risk_score'],
                name='risk_session_class_score_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='slowmovingriskassessment',
            index=models.Index(
                fields=['session', '-risk_score', 'sku'],
                name='risk_session_score_sku_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalexposureitemrecord',
            index=models.Index(
                fields=['analysis', '-risk_weighted_exposure'],
                name='capital_analysis_rwce_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalexposureitemrecord',
            index=models.Index(
                fields=['analysis', 'slow_moving_risk_class', '-risk_weighted_exposure'],
                name='capital_analysis_risk_rwce_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='capitalexposureitemrecord',
            index=models.Index(
                fields=['analysis', 'aging_priority', '-risk_weighted_exposure'],
                name='capital_analysis_prio_rwce_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='datasetversion',
            index=models.Index(fields=['status'], name='dataset_version_status_idx'),
        ),
        migrations.AddIndex(
            model_name='capitalexposureanalysisrecord',
            index=models.Index(
                fields=['dataset_version', 'status'],
                name='capital_analysis_ds_status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='decisionrecord',
            index=models.Index(
                fields=['workspace_id', 'status', 'dataset_version', 'priority_tier'],
                name='decision_ws_stat_ver_pri_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='notificationrecord',
            index=models.Index(
                fields=['workspace_id', 'is_read', 'severity'],
                name='notification_ws_read_sev_idx',
            ),
        ),
    ]
