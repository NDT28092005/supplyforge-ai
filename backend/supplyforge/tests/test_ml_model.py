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
        """Test risk prediction on Onboarding stage (should use Global model)."""
        pred = HybridModelPipeline.predict_risk("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(pred)
        self.assertEqual(pred["base_value"], 0.35)
        self.assertEqual(pred["model_version"], "v1.2.0-global")
        self.assertTrue(0.0 <= pred["risk_probability"] <= 1.0)

    def test_predict_risk_shop_specific_model(self):
        """Test shop-specific model prediction trigger when tenant has >= 10 products."""
        # Create 9 more products to reach >= 10 products
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
        self.assertEqual(pred["model_version"], "v2.0.1-shop-user_ml_test_tenant")

    def test_shap_explanation(self):
        """Test calculation of SHAP values and translation mapping."""
        from supplyforge.services.shap_service import ShapExplanationService
        
        pred = HybridModelPipeline.predict_risk("sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(pred)
        
        explanation = ShapExplanationService.explain_prediction(pred, "sku_ml_test_01", workspace_id=1)
        self.assertIsNotNone(explanation)
        self.assertEqual(explanation["risk_probability"], pred["risk_probability"])
        self.assertEqual(explanation["base_value"], pred["base_value"])
        self.assertEqual(explanation["model_version"], pred["model_version"])
        self.assertGreater(len(explanation["shap_contributions"]), 0)
        self.assertIsNotNone(explanation["ai_explanation"])
        self.assertTrue(len(explanation["ai_explanation"]) > 10)

        # Verify that contributions sum up to probability difference (risk - base)
        shaps_sum = sum(c["shap_value"] for c in explanation["shap_contributions"])
        expected_diff = pred["risk_probability"] - pred["base_value"]
        self.assertAlmostEqual(shaps_sum, expected_diff, places=2)

    def test_xai_view(self):
        """Test GET /api/v1/workspaces/<workspace_id>/sku/<sku_id>/xai view."""
        from django.urls import reverse
        from rest_framework.test import APIClient
        client = APIClient()
        url = reverse('get_sku_xai', kwargs={'workspace_id': 1, 'sku_id': 'sku_ml_test_01'})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("risk_probability", response.data)
        self.assertIn("base_value", response.data)
        self.assertIn("model_version", response.data)
        self.assertIn("shap_contributions", response.data)
        self.assertIn("ai_explanation", response.data)


