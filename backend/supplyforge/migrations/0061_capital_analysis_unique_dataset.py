from django.db import migrations, models
from django.db.models import Count


def remove_duplicate_analyses(apps, schema_editor):
    Analysis = apps.get_model('supplyforge', 'CapitalExposureAnalysisRecord')
    Item = apps.get_model('supplyforge', 'CapitalExposureItemRecord')
    duplicate_keys = (
        Analysis.objects.values('merchant_id', 'dataset_version')
        .annotate(total=Count('analysis_id'))
        .filter(total__gt=1)
    )
    for key in duplicate_keys.iterator():
        duplicate_ids = list(
            Analysis.objects.filter(
                merchant_id=key['merchant_id'],
                dataset_version=key['dataset_version'],
            )
            .order_by('-created_at')
            .values_list('analysis_id', flat=True)[1:]
        )
        if duplicate_ids:
            Item.objects.filter(analysis_id__in=duplicate_ids).delete()
            Analysis.objects.filter(analysis_id__in=duplicate_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0053_decisionrecord_workspace_id'),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_analyses, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='capitalexposureanalysisrecord',
            constraint=models.UniqueConstraint(
                fields=('merchant_id', 'dataset_version'),
                name='capital_analysis_merchant_dataset_unique',
            ),
        ),
    ]
