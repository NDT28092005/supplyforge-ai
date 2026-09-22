import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_model_inference_engine import RiskModelInferenceEngine


class RiskModelInferenceEngineTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-01 Risk Model Integration."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Model Inference WS", slug="test-ws-rm-inf")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        data_dir = os.path.join(PROJECT_ROOT, "data", "processed")
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

    def test_run_risk_model_inference(self):
        """Test XGBoost risk model inference, probability output, and zero-leakage enforcement."""
        df_snapshot = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'sales_velocity_30d': 0.005, 'sales_velocity_90d': 0.04, 'sales_velocity_full': 0.03,
                'sales_last_30d': 0, 'past_total_sold': 50, 'zero_rate_90d': 0.97, 'zero_rate_full': 0.90,
                'adi': 4.5, 'cv2': 1.2, 'dsls': 240, 'forecast_7d': 0.1, 'forecast_14d': 0.2, 'forecast_30d': 0.5,
                'forecast_trend': -0.5, 'demand_probability': 0.008, 'expected_demand_daily': 0.01
            }
        ])

        engine = RiskModelInferenceEngine(session_id=str(self.session.id))
        result = engine.run_risk_model_inference(feature_snapshot_df=df_snapshot, session_id=str(self.session.id))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["modelVersion"], "xgboost_exp03_v1")
        self.assertEqual(result["experimentVersion"], "EXP-03")
        self.assertEqual(result["featureSchemaVersion"], "M2-FEATURE-v1.0")

        preds = result["predictions"]
        self.assertEqual(len(preds), 1)
        p = preds[0]
        self.assertIn(p["risk_class"], ['CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK'])
        self.assertEqual(round(p["critical_probability"] + p["high_risk_probability"] + p["medium_risk_probability"] + p["low_risk_probability"], 2), 1.0)
