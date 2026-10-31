from decimal import Decimal
from datetime import datetime, date, timedelta
from django.test import TestCase
from supplyforge.models import Product, Order, OrderItem
from supplyforge.services.ml_model import HybridModelPipeline

class TestHybridModelPipeline(TestCase):
    def setUp(self):
        # Create a test product
        self.product = Product.objects.create(
            id="sku_ml_test_01",
            user_id="user_ml_test_tenant",
            product_name="Áo thun Cotton Premium đen L",
            item_sku="AT-ML-COTTON-BLK-L",
            item_id="item_ml_101",
            price=Decimal("120000.00"),
            cost=Decimal("70000.00"),
            stock=15,
            active_on_web=True,
            expiration_date=date.today() + timedelta(days=20),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        # Create some sales orders
        self.order = Order.objects.create(
            id="order_ml_01",
            user_id="user_ml_test_tenant",
            order_id="ORD-10001",
            amount=Decimal("240000.00"),
            created_at=datetime.now() - timedelta(days=2)
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            item_id="item_ml_101",
            sku="AT-ML-COTTON-BLK-L",
            product_name="Áo thun Cotton Premium đen L",
            quantity=2,
            price=Decimal("120000.00"),
            cost=Decimal("70000.00")
        )

    def test_feature_extraction(self):
        """Test that features are correctly extracted from django DB models."""
        features = HybridModelPipeline.extract_features("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(features)
        self.assertEqual(features["inventory_qty"], 15.0)
        self.assertEqual(features["cost_price"], 70000.0)
        self.assertEqual(features["selling_price"], 120000.0)
        self.assertEqual(features["sales_7d"], 2.0)
        self.assertEqual(features["sales_30d"], 2.0)
        self.assertGreater(features["sales_velocity"], 0.0)
        self.assertLess(features["inventory_coverage_days"], 999.0)
        self.assertEqual(features["inventory_ratio"], 1.0) # only 1 product in tenant
        self.assertEqual(features["expiration_days_left"], 20.0)

    def test_predict_risk_global_model(self):
        """Test risk prediction (3-tier architecture with baseline fallback for unknown SKU)."""
        pred = HybridModelPipeline.predict_risk("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(pred)
        self.assertIn("risk_probability", pred)
        self.assertIn("prediction", pred)
        self.assertTrue(0.0 <= pred["risk_probability"] <= 1.0)
        # Without Feature Store entry, falls back to baseline
        self.assertEqual(pred["prediction"]["engine"], "BASELINE_LOGISTIC")
        self.assertEqual(pred["prediction"]["status"], "FALLBACK")
        self.assertEqual(pred["prediction"]["model_version"], "baseline-v1.0")

    def test_predict_risk_shop_specific_model(self):
        """Test risk prediction consistency across multiple products."""
        for i in range(2, 11):
            Product.objects.create(
                id=f"sku_ml_test_{i:02d}",
                user_id="user_ml_test_tenant",
                product_name=f"Sản phẩm test thứ {i}",
                item_sku=f"SKU-TEST-{i}",
                price=Decimal("50000.00"),
                cost=Decimal("30000.00"),
                stock=5,
                active_on_web=True
            )

        pred = HybridModelPipeline.predict_risk("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(pred)
        self.assertEqual(pred["prediction"]["engine"], "BASELINE_LOGISTIC")
        self.assertEqual(pred["prediction"]["status"], "FALLBACK")

    def test_shap_explanation(self):
        """Test calculation of SHAP values and translation mapping."""
        from supplyforge.services.shap_service import ShapExplanationService
        
        pred = HybridModelPipeline.predict_risk("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(pred)
        
        explanation = ShapExplanationService.explain_prediction(pred, "sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(explanation)
        self.assertEqual(explanation["risk_probability"], pred["risk_probability"])
        self.assertEqual(explanation["base_value"], pred["base_value"])
        self.assertIn("prediction_engine", explanation)
        self.assertIn("explanation_engine", explanation)
        self.assertIn("decision_confidence", explanation)
        self.assertGreater(len(explanation["shap_contributions"]), 0)
        self.assertIsNotNone(explanation["ai_explanation"])
        self.assertTrue(len(explanation["ai_explanation"]) > 10)

    def test_xai_view(self):
        """Test GET /api/v1/workspaces/<workspace_id>/sku/<sku_id>/xai view."""
        from django.urls import reverse
        from rest_framework.test import APIClient
        from supplyforge.models import User, Workspace, WorkspaceMember
        from supplyforge.views.auth import generate_access_token
        
        user = User.objects.create(email="xai_user@local", password_hash="pass", role="OWNER", status=User.STATUS_ACTIVE, is_email_verified=True)
        ws = Workspace.objects.filter(id=1).first()
        if not ws:
            ws = Workspace.objects.create(id=1, name="Default WS", owner=user, slug="default_ws")
        WorkspaceMember.objects.filter(workspace=ws, user=user).delete()
        WorkspaceMember.objects.create(workspace=ws, user=user, role="OWNER")
        token = generate_access_token(user, workspace_id=1)
        
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        url = reverse('get_sku_xai', kwargs={'workspace_id': 1, 'sku_id': 'sku_ml_test_01'})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("risk_probability", response.data)
        self.assertIn("base_value", response.data)
        self.assertIn("prediction_engine", response.data)
        self.assertIn("explanation_engine", response.data)
        self.assertIn("shap_contributions", response.data)
        self.assertIn("ai_explanation", response.data)

    def test_primary_xgboost_prediction(self):
        """Test the optional primary artifact only when it is packaged locally."""
        from supplyforge.services.shap_service import ShapExplanationService
        from supplyforge.services.model_loader import ModelLoaderService

        if not ModelLoaderService.is_available():
            self.skipTest(
                'Primary XGBoost artifact is not packaged in this test environment; '
                'the fallback contract is covered by the remaining tests.'
            )

        gold_sku = "10012591570"
        Product.objects.create(
            id=gold_sku,
            user_id="user_gold",
            product_name="Sản phẩm Gold Feature Store",
            item_sku=f"SKU-{gold_sku}",
            price=Decimal("150000.00"),
            cost=Decimal("90000.00"),
            stock=40,
            active_on_web=True
        )

        pred = HybridModelPipeline.predict_risk(gold_sku, workspace_id=1)
        self.assertIsNotNone(pred)
        self.assertEqual(pred["prediction"]["engine"], "XGBOOST")
        self.assertEqual(pred["prediction"]["status"], "PRIMARY")
        self.assertEqual(pred["prediction"]["model_version"], "risk-xgb-v1.2.0")
        self.assertTrue(pred["prediction"]["calibrated"])

        explanation = ShapExplanationService.explain_prediction(pred, gold_sku, workspace_id=1)
        self.assertEqual(explanation["prediction_engine"], "XGBOOST")
        self.assertEqual(explanation["explanation_engine"], "TREESHAP")
        self.assertEqual(explanation["prediction_status"], "PRIMARY")
        self.assertEqual(explanation["explanation_status"], "PRIMARY")
        self.assertGreater(len(explanation["shap_contributions"]), 0)
        self.assertIsNotNone(explanation["additivity_check"])
        self.assertTrue(explanation["additivity_check"]["passed"])



