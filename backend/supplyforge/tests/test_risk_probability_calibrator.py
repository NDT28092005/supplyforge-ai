import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_probability_calibrator import RiskProbabilityCalibrator


class RiskProbabilityCalibratorTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-04 Risk Probability Calibration."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Calibration WS", slug="test-ws-pc-eng")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        models_dir = os.path.join(PROJECT_ROOT, "models")
        data_dir = os.path.join(PROJECT_ROOT, "data", "processed")
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(models_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

    def test_benchmark_and_calibrate(self):
        """Test probability calibration benchmarking across 4 methods, ECE/Brier calculation, and artifact generation."""
        df_preds = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'risk_class': 'CRITICAL',
                'critical_probability': 0.990, 'high_risk_probability': 0.008,
                'medium_risk_probability': 0.001, 'low_risk_probability': 0.001
            }
        ])

        calibrator = RiskProbabilityCalibrator(session_id=str(self.session.id))
        result = calibrator.benchmark_and_calibrate(predictions_df=df_preds, session_id=str(self.session.id))

        self.assertEqual(result["status"], "SUCCESS")
        summary = result["summary"]
        self.assertIn("optimalCalibrationMethod", summary)
        self.assertIn("optimalECE", summary)

        cal_preds = result["calibratedPredictions"]
        self.assertEqual(len(cal_preds), 1)
        p = cal_preds[0]
        self.assertEqual(p["calibration_status"], "CALIBRATED")
        self.assertIn("confidence_level", p)
