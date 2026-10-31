import json
import io
import uuid
from django.test import TestCase, Client
from django.contrib.auth.hashers import make_password
from supplyforge.models import (
    User, Product, SlowMovingRiskAssessment, IngestionSession,
    Workspace, WorkspaceMember, CapitalExposureAnalysisRecord
)


class APIPyramidTests(TestCase):
    """
    Task 3.2: API Layer Tests covering all core REST API endpoints.
    - POST /api/v1/auth/login
    - POST /api/v1/ingestion/upload
    - GET /api/v1/risk/summary
    - GET /api/v1/risk/skus/{sku_id}
    - GET /api/capital-exposure/analyses/{analysis_id}/summary
    - GET /api/v1/decisions
    - POST /api/v1/copilot/chat
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(
            email="test_api@supplyforge.local",
            password_hash=make_password("Test123456"),
            display_name="Test API Merchant",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role="OWNER"
        )
        self.workspace = Workspace.objects.create(
            name="Test API Workspace",
            owner=self.user,
            slug="t_test_api"
        )
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role="OWNER"
        )
        self.product = Product.objects.create(
            id="prod_api_001",
            user_id=str(self.user.id),
            third_party_id="tp_001",
            product_name="API Test Product",
            item_sku="SKU_API_001",
            stock=100,
            cost=50000.0,
            price=100000.0
        )
        self.session = IngestionSession.objects.create(
            id=uuid.uuid4(),
            workspace=self.workspace,
            original_filename="test_dataset.csv",
            status="COMPLETED"
        )
        self.risk_asm = SlowMovingRiskAssessment.objects.create(
            session=self.session,
            sku="SKU_API_001",
            canonical_sku_id="CSKU_SKU_API_001",
            product_name="API Test Product",
            risk_class="CRITICAL",
            risk_score=85.0,
            risk_probability=0.9
        )
        self.cap_analysis = CapitalExposureAnalysisRecord.objects.create(
            analysis_id="default",
            merchant_id=f"workspace:{self.workspace.id}",
            total_skus=1,
            total_inventory_value=5000000.0
        )

        # Obtain login JWT token
        login_resp = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": "test_api@supplyforge.local", "password": "Test123456"}),
            content_type="application/json"
        )
        login_data = json.loads(login_resp.content)
        self.access_token = login_data.get("token") or login_data.get("access_token")
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"} if self.access_token else {}

    def test_post_auth_login(self):
        """Test POST /api/v1/auth/login returns token & user profile."""
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": "test_api@supplyforge.local", "password": "Test123456"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("token", data)
        self.assertIn("user", data)

    def test_post_dataset_upload(self):
        """Test POST /api/v1/ingestion/upload processes file upload."""
        csv_file = io.BytesIO(b"sku,product_name,stock_quantity,unit_cost,selling_price\nSKU_UP_01,Test Item,50,20000,40000\n")
        csv_file.name = "test_upload.csv"
        response = self.client.post('/api/v1/ingestion/upload', {'file': csv_file}, **self.auth_headers)
        self.assertIn(response.status_code, [200, 201])
        data = json.loads(response.content)
        self.assertTrue("sessionId" in data or "session_id" in data)

    def test_get_risk_summary(self):
        """Test GET /api/v1/risk/summary returns global risk breakdown."""
        response = self.client.get('/api/v1/risk/summary', **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue("total_skus" in data or "total_skus_assessed" in data)

    def test_get_risk_sku_detail(self):
        """Test GET /api/v1/risk/skus/{sku_id} returns single SKU risk assessment."""
        response = self.client.get('/api/v1/risk/skus/SKU_API_001', **self.auth_headers)
        self.assertEqual(response.status_code, 200)

    def test_get_capital_exposure_summary(self):
        """Test GET /api/capital-exposure/analyses/{analysis_id}/summary."""
        response = self.client.get('/api/capital-exposure/analyses/default/summary', **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("summary", data)
        self.assertIn("total_skus", data["summary"])

    def test_get_decisions(self):
        """Test GET /api/v1/decisions lists active decisions."""
        response = self.client.get('/api/v1/decisions/', **self.auth_headers)
        self.assertEqual(response.status_code, 200)

    def test_post_copilot_chat(self):
        """Test POST /api/v1/copilot/chat returns grounded AI response."""
        response = self.client.post(
            '/api/v1/copilot/chat',
            data=json.dumps({"message": "Hãy phân tích rủi ro sản phẩm SKU_API_001"}),
            content_type="application/json",
            **self.auth_headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue("answer" in data or "reply" in data)
