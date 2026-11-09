from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0087_decision_operational_lineage'),
    ]

    operations = [
        migrations.CreateModel(
            name='ActionPlanScopeLock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('workspace_id', models.IntegerField(db_index=True)),
                ('sku', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'action_plan_scope_locks'},
        ),
        migrations.AddConstraint(
            model_name='actionplanscopelock',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'sku'), name='action_plan_scope_lock_uq'),
        ),
    ]
