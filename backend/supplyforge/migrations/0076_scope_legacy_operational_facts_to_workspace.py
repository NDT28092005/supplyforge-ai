"""Scope legacy operational projections to the workspace that owns them."""

from django.db import migrations, models
import django.db.models.deletion


def backfill_unambiguous_workspace_facts(apps, schema_editor):
    """Attach old facts only where a user resolves to one workspace.

    A user with multiple workspaces is deliberately not backfilled. Assigning
    such rows by owner id would silently expose one business's orders or
    products in another business. Those rows remain available for an explicit
    operator migration/re-import.
    """
    Workspace = apps.get_model('supplyforge', 'Workspace')
    WorkspaceMember = apps.get_model('supplyforge', 'WorkspaceMember')
    Product = apps.get_model('supplyforge', 'Product')
    Order = apps.get_model('supplyforge', 'Order')

    cache = {}

    def workspace_id_for_legacy_user(raw_user_id):
        user_key = str(raw_user_id or '').strip()
        if user_key in cache:
            return cache[user_key]
        try:
            user_id = int(user_key)
        except (TypeError, ValueError):
            cache[user_key] = None
            return None
        workspace_ids = set(
            Workspace.objects.filter(owner_id=user_id).values_list('id', flat=True)
        ) | set(
            WorkspaceMember.objects.filter(user_id=user_id).values_list('workspace_id', flat=True)
        )
        cache[user_key] = workspace_ids.pop() if len(workspace_ids) == 1 else None
        return cache[user_key]

    for model in (Product, Order):
        legacy_user_ids = model.objects.filter(
            workspace__isnull=True,
        ).values_list('user_id', flat=True).distinct().iterator(chunk_size=1_000)
        for raw_user_id in legacy_user_ids:
            workspace_id = workspace_id_for_legacy_user(raw_user_id)
            if workspace_id:
                model.objects.filter(
                    workspace__isnull=True,
                    user_id=raw_user_id,
                ).update(workspace_id=workspace_id)


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0075_tenant_deletion_audit'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='workspace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='orders',
                to='supplyforge.workspace',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='workspace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='products',
                to='supplyforge.workspace',
            ),
        ),
        migrations.RunPython(
            backfill_unambiguous_workspace_facts,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['workspace', 'created_at'], name='order_workspace_created_idx'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['workspace', 'status', 'source_event_at'], name='order_ws_status_event_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['workspace', 'item_sku'], name='product_workspace_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['workspace', 'canonical_sku'], name='product_workspace_csku_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['workspace', 'created_at'], name='product_workspace_created_idx'),
        ),
    ]
