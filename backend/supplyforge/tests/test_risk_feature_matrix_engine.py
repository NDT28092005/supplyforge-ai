import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine, FeatureLeakageError


class RiskFeatureMatrixEngineTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-04 Slow-Moving Risk Feature Engineering."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Matrix WS", slug="test-ws-risk-mat")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_build_risk_feature_matrix(self):
        """Test building Risk Feature Matrix with 7 feature categories."""
        df_m203 = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'sales_velocity_30d': 0.5, 'sales_last_7d': 1.0, 'sales_last_30d': 15.0, 'sales_last_90d': 45.0, 'dsls': 10, 'zero_rate_90d': 0.3, 'adi': 1.2, 'cv2': 0.3, 'demand_pattern': 'SMOOTH'}
        ])

        engine = RiskFeatureMatrixEngine(session_id=str(self.session.id))
        result = engine.build_risk_feature_matrix(risk_features_m203_df=df_m203, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 1)
        self.assertEqual(result["summary"]["leakageAudit"]["status"], "PASSED")
        recs = result["riskFeatureMatrixRecords"]
        self.assertEqual(recs[0]["demand_pattern"], "SMOOTH")
        self.assertEqual(recs[0]["lumpy_flag"], 0)
        self.assertEqual(recs[0]["intermittent_flag"], 0)

    def test_temporal_leakage_interception(self):
        """Test that forbidden columns raise FeatureLeakageError."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'future_velocity': 12.5}
        ])

        engine = RiskFeatureMatrixEngine(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            engine.build_risk_feature_matrix(risk_features_m203_df=df_leak, session_id=str(self.session.id))
