from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0089_decision_and_procurement_portfolio_runs'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='decisionrecord',
            index=models.Index(
                fields=['workspace_id', 'status', 'priority_score', 'created_at', 'decision_id'],
                name='decision_cursor_priority_idx',
            ),
        ),
    ]
