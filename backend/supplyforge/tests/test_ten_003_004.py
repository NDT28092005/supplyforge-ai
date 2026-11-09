import json
from django.test import TestCase, Client, override_settings
from supplyforge.models import (
    User, Workspace, IngestionSession, ArchivedDataSet, Product,
    SlowMovingRiskAssessment, CapitalExposureAnalysisRecord, DecisionRecord, CopilotConversation
)
from supplyforge.services.tenant_data_deletion import TenantDataDeletionService
from supplyforge.views.auth import get_or_create_user_tenant, generate_access_token


class Ten003And004TestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create Owner User & Tenant
        self.owner = User.objects.create(
            email="owner_ten003@shop.com",
            display_name="Owner TEN-003",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant = get_or_create_user_tenant(self.owner)

        # Create Viewer User
        self.viewer = User.objects.create(
            email="viewer_ten003@shop.com",
            display_name="Viewer TEN-003",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_VIEWER
        )

    def test_ten_003_tenant_context_endpoint(self):
        """TEN-003: Every request identifies user, tenant, role, and permissions."""
        token = generate_access_token(self.owner, workspace_id=self.tenant.id)
        response = self.client.get(
            '/api/v1/tenant/context?workspaceId=1',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "ACTIVE")
        context = data["tenant_context"]
        self.assertIn("workspace_id", context)
        self.assertIn("tenant_id", context)
        self.assertIn("role", context)
        self.assertIn("permissions", context)

    def test_ten_004_7_layer_data_deletion_policy(self):
        """TEN-004: Purges all 7 layers of tenant data cleanly."""
        ws_id = self.tenant.id

        # Populate 7 layers of test data
        session = IngestionSession.objects.create(workspace=self.tenant, status='COMPLETED')
        owner_id = str(self.owner.id)
        dataset = ArchivedDataSet.objects.create(
            user_id=owner_id,
            product_count=10,
            order_count=5,
            snapshot_json={'workspace_id': ws_id},
        )
        product = Product.objects.create(
            id=f'p_{ws_id}_01',
            user_id=owner_id,
            workspace=self.tenant,
            product_name='Product 1',
            price=100,
        )
        risk = SlowMovingRiskAssessment.objects.create(session=session, sku='SKU-001', risk_score=85.0, risk_probability=0.85)
        capital = CapitalExposureAnalysisRecord.objects.create(merchant_id=owner_id, total_inventory_value=1000)
        decision = DecisionRecord.objects.create(decision_id=f'dec_{ws_id}', workspace_id=ws_id, sku='SKU-001', action_type='DISCOUNT')
        copilot_conv = CopilotConversation.objects.create(tenant_id=f'T{ws_id:03d}', merchant_id=owner_id)

        # Execute 7-layer data deletion policy
        purge_result = TenantDataDeletionService.purge_tenant_data(workspace_id=ws_id)
        self.assertEqual(purge_result["status"], "SUCCESS")
        self.assertEqual(purge_result["policy"], "TEN-004_WORKSPACE_SCOPED_PURGE_POLICY")

        # Verify all 7 layers are deleted
        self.assertEqual(IngestionSession.objects.filter(workspace=self.tenant).count(), 0)
        self.assertEqual(ArchivedDataSet.objects.filter(user_id=owner_id).count(), 0)
        self.assertEqual(Product.objects.filter(user_id=owner_id).count(), 0)
        self.assertEqual(SlowMovingRiskAssessment.objects.filter(session__workspace=self.tenant).count(), 0)
        self.assertEqual(CapitalExposureAnalysisRecord.objects.filter(merchant_id=owner_id).count(), 0)
        self.assertEqual(DecisionRecord.objects.filter(sku='SKU-001').count(), 0)
        self.assertEqual(CopilotConversation.objects.filter(merchant_id=owner_id).count(), 0)

    def test_ten_004_purge_never_touches_another_workspace(self):
        """Regression: scoped tenant deletion must preserve every B resource."""
        other_owner = User.objects.create(
            email='owner_other_tenant@shop.com', display_name='Owner B',
            status=User.STATUS_ACTIVE, is_email_verified=True, role=User.ROLE_OWNER,
        )
        other_workspace = get_or_create_user_tenant(other_owner)
        session_a = IngestionSession.objects.create(workspace=self.tenant, status='COMPLETED')
        session_b = IngestionSession.objects.create(workspace=other_workspace, status='COMPLETED')
        Product.objects.create(
            id='product-a', user_id=str(self.owner.id), workspace=self.tenant,
            product_name='A', price=100,
        )
        Product.objects.create(
            id='product-b', user_id=str(other_owner.id), workspace=other_workspace,
            product_name='B', price=100,
        )
        DecisionRecord.objects.create(decision_id='decision-a', workspace_id=self.tenant.id, sku='SKU-A')
        DecisionRecord.objects.create(decision_id='decision-b', workspace_id=other_workspace.id, sku='SKU-B')
        SlowMovingRiskAssessment.objects.create(session=session_a, sku='SKU-A', risk_score=80, risk_probability=.8)
        SlowMovingRiskAssessment.objects.create(session=session_b, sku='SKU-B', risk_score=70, risk_probability=.7)

        TenantDataDeletionService.purge_tenant_data(self.tenant.id, user_id=self.owner.id)

        self.assertFalse(IngestionSession.objects.filter(id=session_a.id).exists())
        self.assertFalse(Product.objects.filter(id='product-a').exists())
        self.assertFalse(DecisionRecord.objects.filter(decision_id='decision-a').exists())
        self.assertTrue(IngestionSession.objects.filter(id=session_b.id).exists())
        self.assertTrue(Product.objects.filter(id='product-b').exists())
        self.assertTrue(DecisionRecord.objects.filter(decision_id='decision-b').exists())
        self.assertTrue(SlowMovingRiskAssessment.objects.filter(session=session_b).exists())

    def test_ten_004_legacy_route_is_disabled_by_default(self):
        token = generate_access_token(self.owner, workspace_id=self.tenant.id)
        response = self.client.post('/api/v1/tenant/delete-data', **{'HTTP_AUTHORIZATION': f'Bearer {token}'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'TENANT_DELETION_DISABLED')

    @override_settings(TENANT_DATA_DELETION_ENABLED=True)
    def test_ten_004_requires_preview_and_single_use_confirmation(self):
        token = generate_access_token(self.owner, workspace_id=self.tenant.id)
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}
        preview = self.client.post('/api/v1/tenant/delete-data/preview', **headers)
        self.assertEqual(preview.status_code, 200)
        payload = preview.json()
        confirmed = self.client.post(
            '/api/v1/tenant/delete-data/confirm',
            data=json.dumps({
                'confirmationToken': payload['confirmationToken'],
                'confirmation': self.tenant.slug,
            }),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(confirmed.status_code, 200)
        duplicate = self.client.post(
            '/api/v1/tenant/delete-data/confirm',
            data=json.dumps({
                'confirmationToken': payload['confirmationToken'],
                'confirmation': self.tenant.slug,
            }),
            content_type='application/json',
            **headers,
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_ten_004_deletion_rbac_protection(self):
        """TEN-004: Non-admin/owner roles (e.g. VIEWER) are denied from purging tenant data (HTTP 403)."""
        from django.test import RequestFactory
        from supplyforge.middleware import TenantIsolationMiddleware
        from supplyforge.views.ingestion import clear_data

        rf = RequestFactory()
        token = generate_access_token(self.viewer, workspace_id=self.tenant.id)
        request = rf.post(
            '/api/v1/tenant/delete-data',
            data=json.dumps({"workspaceId": self.tenant.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token}'
        )
        middleware = TenantIsolationMiddleware(clear_data)
        response = middleware(request)
        response.render()

        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data["code"], "PERMISSION_DENIED")
