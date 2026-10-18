# Generated for the S3 multipart ingestion contract.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0048_modelversion_alter_user_status_backgroundjob_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ingestionsession',
            name='lake_storage_path',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        migrations.AddField(
            model_name='ingestionsession',
            name='s3_checksum_sha256',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='ingestionsession',
            name='s3_object_etag',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='ingestionsession',
            name='s3_object_key',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        migrations.AddField(
            model_name='ingestionsession',
            name='s3_upload_id',
            field=models.CharField(blank=True, default='', max_length=512),
        ),
        migrations.AddField(
            model_name='ingestionsession',
            name='upload_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
