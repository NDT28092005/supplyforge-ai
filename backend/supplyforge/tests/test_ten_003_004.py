import json
from django.test import TestCase, Client
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
        dataset = ArchivedDataSet.objects.create(user_id=str(ws_id), product_count=10, order_count=5)
        product = Product.objects.create(id=f'p_{ws_id}_01', user_id=str(ws_id), product_name='Product 1', price=100)
        risk = SlowMovingRiskAssessment.objects.create(session=session, sku='SKU-001', risk_score=85.0, risk_probability=0.85)
        capital = CapitalExposureAnalysisRecord.objects.create(merchant_id=str(ws_id), total_inventory_value=1000)
        decision = DecisionRecord.objects.create(decision_id=f'dec_{ws_id}', sku='SKU-001', action_type='DISCOUNT')
        copilot_conv = CopilotConversation.objects.create(tenant_id=f'T{ws_id:03d}', merchant_id=str(ws_id))

        # Execute 7-layer data deletion policy
        purge_result = TenantDataDeletionService.purge_tenant_data(workspace_id=ws_id)
        self.assertEqual(purge_result["status"], "SUCCESS")
        self.assertEqual(purge_result["policy"], "TEN-004_7_LAYER_PURGE_POLICY")

        # Verify all 7 layers are deleted
        self.assertEqual(IngestionSession.objects.filter(workspace=self.tenant).count(), 0)
        self.assertEqual(ArchivedDataSet.objects.filter(user_id=str(ws_id)).count(), 0)
        self.assertEqual(Product.objects.filter(user_id=str(ws_id)).count(), 0)
        self.assertEqual(SlowMovingRiskAssessment.objects.filter(session__workspace=self.tenant).count(), 0)
        self.assertEqual(CapitalExposureAnalysisRecord.objects.filter(merchant_id=str(ws_id)).count(), 0)
        self.assertEqual(DecisionRecord.objects.filter(sku='SKU-001').count(), 0)
        self.assertEqual(CopilotConversation.objects.filter(merchant_id=str(ws_id)).count(), 0)

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
