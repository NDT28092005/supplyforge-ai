# Generated for cancellable lake ingestion versions.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0050_datasetversion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='datasetversion',
            name='status',
            field=models.CharField(
                choices=[
                    ('BUILDING', 'Building'),
                    ('ACTIVE', 'Active'),
                    ('SUPERSEDED', 'Superseded'),
                    ('FAILED', 'Failed'),
                    ('CANCELLED', 'Cancelled'),
                ],
                default='BUILDING',
                max_length=20,
            ),
        ),
    ]
