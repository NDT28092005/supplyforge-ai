"""Regression coverage for workspace-scoped legacy order and product projections."""

import io

from django.test import TestCase

from supplyforge.models import IngestionSession, Order, Product, User, Workspace
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products


class WorkspaceOperationalFactIsolationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='workspace-isolation@example.test',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER,
        )
        self.workspace_a = Workspace.objects.create(
            name='Workspace A', slug='workspace-operational-a', owner=self.owner,
        )
        self.workspace_b = Workspace.objects.create(
            name='Workspace B', slug='workspace-operational-b', owner=self.owner,
        )

    def _import(self, workspace, sku):
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename=f'{sku}.csv',
            status='COMPLETED',
        )
        payload = (
            'order_id,item_sku,product_name,quantity,price,cost,order_date\n'
            f'ORDER-SHARED,{sku},{sku} product,2,150000,100000,2026-10-29\n'
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=session.id,
            workspace_id=workspace.id,
            run_post_import_hooks=False,
        )
        return session

    def test_same_owner_workspaces_do_not_share_or_clear_operational_facts(self):
        session_a = self._import(self.workspace_a, 'SKU-A')
        self._import(self.workspace_b, 'SKU-B')

        self.assertEqual(Order.objects.filter(workspace=self.workspace_a).count(), 1)
        self.assertEqual(Order.objects.filter(workspace=self.workspace_b).count(), 1)
        self.assertEqual(Product.objects.filter(workspace=self.workspace_a).count(), 1)
        self.assertEqual(Product.objects.filter(workspace=self.workspace_b).count(), 1)

        _auto_populate_assessments_from_products(str(session_a.id))
        self.assertEqual(
            list(session_a.risk_assessments.values_list('sku', flat=True)),
            ['SKU-A'],
        )

        DynamicFileImportService.clear_data(
            str(self.owner.id),
            workspace_id=self.workspace_a.id,
        )

        self.assertFalse(Order.objects.filter(workspace=self.workspace_a).exists())
        self.assertFalse(Product.objects.filter(workspace=self.workspace_a).exists())
        self.assertTrue(Order.objects.filter(workspace=self.workspace_b).exists())
        self.assertTrue(Product.objects.filter(workspace=self.workspace_b).exists())
