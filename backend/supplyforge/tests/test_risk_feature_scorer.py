import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_feature_scorer import RiskFeatureScorer, FeatureLeakageError


class RiskFeatureScorerTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-05 Slow-Moving Risk Feature Scoring."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Scoring WS", slug="test-ws-risk-scr")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_compute_risk_scores(self):
        """Test computing 5 groups of risk signals and composite score."""
        df_m204 = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'sales_velocity_30d': 0.005, 'dsls': 240, 'zero_rate_90d': 0.97, 'adi': 4.5, 'cv2': 1.2, 'demand_pattern': 'LUMPY', 'demand_probability': 0.008}
        ])

        scorer = RiskFeatureScorer(session_id=str(self.session.id))
        result = scorer.compute_risk_scores(risk_matrix_df=df_m204, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 1)
        self.assertEqual(result["summary"]["leakageCheckStatus"], "PASSED")
        recs = result["riskScoreRecords"]
        self.assertEqual(recs[0]["slow_moving_score_level"], "HIGH")
        self.assertGreater(recs[0]["slow_moving_signal_score"], 0.70)
        self.assertEqual(recs[0]["low_velocity_flag"], 1)
        self.assertEqual(recs[0]["stale_sales_flag"], 1)

    def test_feature_leakage_interception(self):
        """Test that forbidden columns raise FeatureLeakageError."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'fut_qty_60d': 50}
        ])

        scorer = RiskFeatureScorer(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            scorer.compute_risk_scores(risk_matrix_df=df_leak, session_id=str(self.session.id))
