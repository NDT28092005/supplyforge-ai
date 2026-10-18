# Generated for versioned lake metadata.

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0049_ingestionsession_s3_multipart_metadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='DatasetVersion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version_number', models.PositiveIntegerField()),
                ('version_label', models.CharField(max_length=64)),
                ('import_type', models.CharField(max_length=20)),
                ('status', models.CharField(choices=[('BUILDING', 'Building'), ('ACTIVE', 'Active'), ('SUPERSEDED', 'Superseded'), ('FAILED', 'Failed')], default='BUILDING', max_length=20)),
                ('raw_storage_path', models.CharField(blank=True, default='', max_length=1024)),
                ('bronze_storage_path', models.CharField(blank=True, default='', max_length=1024)),
                ('silver_storage_path', models.CharField(blank=True, default='', max_length=1024)),
                ('gold_storage_path', models.CharField(blank=True, default='', max_length=1024)),
                ('source_checksum', models.CharField(blank=True, default='', max_length=128)),
                ('manifest_json', models.JSONField(blank=True, default=dict)),
                ('row_count', models.BigIntegerField(default=0)),
                ('valid_row_count', models.BigIntegerField(default=0)),
                ('rejected_row_count', models.BigIntegerField(default=0)),
                ('data_as_of', models.DateTimeField(blank=True, null=True)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('superseded_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('ingestion_session', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='dataset_version_record', to='supplyforge.ingestionsession')),
                ('parent_version', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='child_versions', to='supplyforge.datasetversion')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dataset_versions', to='supplyforge.workspace')),
            ],
            options={
                'db_table': 'dataset_versions',
                'ordering': ['-version_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='datasetversion',
            constraint=models.UniqueConstraint(fields=('workspace', 'version_number'), name='dataset_version_workspace_number_unique'),
        ),
        migrations.AddIndex(
            model_name='datasetversion',
            index=models.Index(fields=['workspace', 'status'], name='dataset_ver_workspa_65e541_idx'),
        ),
        migrations.AddIndex(
            model_name='datasetversion',
            index=models.Index(fields=['workspace', 'created_at'], name='dataset_ver_workspa_9f5783_idx'),
        ),
    ]
