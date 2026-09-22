import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.data_readiness_gate import DataReadinessGate
from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer


class SlowMovingFeatureEngineerTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-01 Slow-Moving Risk Feature Engineering."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Feature Engineer WS", slug="test-ws-fe")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        gate = DataReadinessGate(session_id=str(self.session.id))
        gate.evaluate_readiness(str(self.session.id), output_dir=reports_dir)

    def test_compute_sku_features(self):
        """Test calculating SKU demand features as of decision date t0."""
        df = pd.DataFrame({
            "order_id": ["ORD_1", "ORD_2", "ORD_3"],
            "date": ["2026-08-01", "2026-08-05", "2026-08-10"],
            "sku": ["SKU_101", "SKU_101", "SKU_102"],
            "canonical_sku_id": ["CSKU_101", "CSKU_101", "CSKU_102"],
            "product_name": ["Product 101", "Product 101", "Product 102"],
            "quantity": [10, 5, 2],
            "price": [100000, 100000, 50000],
            "cost": [70000, 70000, 35000],
        })

        engineer = SlowMovingFeatureEngineer(session_id=str(self.session.id))
        result = engineer.compute_sku_features(df=df, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 2)
        self.assertEqual(len(result["featureMatrix"]), 2)
        self.assertEqual(result["qualityReport"]["status"], "PASSED")
        self.assertIn("sales_velocity_30d", result["featureMatrix"][0])
        self.assertIn("dsls", result["featureMatrix"][0])
        self.assertIn("adi", result["featureMatrix"][0])
        self.assertIn("demand_pattern_candidate", result["featureMatrix"][0])
