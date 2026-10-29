from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0062_p1_query_path_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ingestionsession',
            name='status',
            field=models.CharField(
                choices=[
                    ('UPLOADING', 'Uploading'),
                    ('PROFILING', 'Profiling'),
                    ('PROFILED', 'Profiled'),
                    ('MAPPING', 'Column Mapping'),
                    ('QUEUED', 'Queued'),
                    ('PROCESSING', 'Processing'),
                    ('COMPLETED', 'Completed'),
                    ('FAILED', 'Failed'),
                    ('CANCELLED', 'Cancelled'),
                    ('ARCHIVED', 'Archived'),
                ],
                default='UPLOADING',
                max_length=20,
            ),
        ),
    ]
