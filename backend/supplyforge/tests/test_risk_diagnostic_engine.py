import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_diagnostic_engine import RiskDiagnosticEngine


class RiskDiagnosticEngineTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-05 Risk Diagnostic Engine."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Diagnostics WS", slug="test-ws-rd-eng")
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

    def test_diagnose_sku_risks(self):
        """Test 5 deterministic diagnostic rules, metric evidence attachment, and profile generation."""
        df_preds = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'risk_class': 'CRITICAL', 'calibrated_probability': 0.960, 'risk_score': 96.0,
                'sales_velocity_90d': 0.029, 'adi': 5.92, 'cv2': 0.65, 'dsls': 375,
                'promo_rate': 0.25, 'zero_rate_90d': 0.989, 'sales_last_30d': 0, 'active_30d': True
            }
        ])

        engine = RiskDiagnosticEngine(session_id=str(self.session.id))
        result = engine.diagnose_sku_risks(predictions_df=df_preds, session_id=str(self.session.id))

        self.assertEqual(result["status"], "SUCCESS")
        profiles = result["profiles"]
        self.assertEqual(len(profiles), 1)

        p = profiles[0]
        self.assertEqual(p["risk"]["class"], "CRITICAL")
        self.assertEqual(p["risk"]["probability"], 0.960)
        self.assertIn("LOW_SALES_VELOCITY", p["diagnostic_signals_list"])
        self.assertIn("POSSIBLE_OBSOLESCENCE", p["diagnostic_signals_list"])

        diag_map = {d["code"]: d for d in p["diagnostics"]}
        d01_ev = diag_map["LOW_SALES_VELOCITY"]["evidence"]
        self.assertEqual(d01_ev["metric"], "sales_velocity_90d")
        self.assertEqual(d01_ev["value"], 0.029)
