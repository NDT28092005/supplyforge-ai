import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier, FeatureLeakageError


class SlowMovingRiskClassifierTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-06 Slow-Moving Risk Classification."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Class WS", slug="test-ws-risk-cls")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_classify_slow_moving_risk(self):
        """Test classifying 4 risk classes and class probability matrix."""
        df_m205 = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'slow_moving_signal_score': 0.95, 'dsls': 240, 'zero_rate': 0.97, 'sales_velocity_30d': 0.005}
        ])

        classifier = SlowMovingRiskClassifier(session_id=str(self.session.id))
        result = classifier.classify_slow_moving_risk(risk_scores_m205_df=df_m205, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 1)
        self.assertEqual(result["summary"]["leakageCheckStatus"], "PASSED")
        recs = result["riskClassificationRecords"]
        self.assertEqual(recs[0]["risk_level"], "CRITICAL")
        self.assertEqual(recs[0]["risk_confidence"], "HIGH")
        self.assertGreater(recs[0]["critical_probability"], 0.80)

    def test_inference_feature_leakage_interception(self):
        """Test that forbidden future columns raise FeatureLeakageError at inference time."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'fut_qty_60d': 10}
        ])

        classifier = SlowMovingRiskClassifier(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            classifier.classify_slow_moving_risk(risk_scores_m205_df=df_leak, session_id=str(self.session.id))
