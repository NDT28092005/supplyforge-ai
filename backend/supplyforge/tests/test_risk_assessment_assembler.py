import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_assessment_assembler import RiskAssessmentAssembler


class RiskAssessmentAssemblerTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-06 Risk Assessment Assembly."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Assessment WS", slug="test-ws-ra-eng")
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

    def test_assemble_risk_assessments(self):
        """Test assembly of 5 information groups, signal prioritization, lineage metadata, and status validation."""
        df_preds = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'category': 'Milk',
                'risk_class': 'CRITICAL', 'calibrated_probability': 0.960, 'risk_score': 96.0,
                'sales_velocity_90d': 0.029, 'zero_rate_90d': 0.989, 'dsls': 375, 'adi': 5.92, 'cv2': 0.65,
                'demand_probability': 0.004, 'forecast_7d': 0.02, 'forecast_trend': -0.4, 'expected_demand_daily': 0.01,
                'decision_cutoff': '2025-10-16', 'model_version': 'xgboost_v1', 'calibration_version': 'calibration_v1',
                'diagnostic_rule_version': 'rules_v1', 'dataset_version': 'v1.3'
            }
        ])
        df_diags = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101',
                'diagnostic_signals_list': ['LUMPY_DEMAND', 'POSSIBLE_OBSOLESCENCE', 'LOW_SALES_VELOCITY']
            }
        ])

        assembler = RiskAssessmentAssembler(session_id=str(self.session.id))
        result = assembler.assemble_risk_assessments(
            predictions_df=df_preds,
            diagnostics_df=df_diags,
            session_id=str(self.session.id)
        )

        self.assertEqual(result["status"], "SUCCESS")
        assessments = result["assessments"]
        self.assertEqual(len(assessments), 1)

        a = assessments[0]
        self.assertEqual(a["assessment"]["risk_class"], "CRITICAL")
        self.assertEqual(a["assessment"]["risk_probability"], 0.960)
        self.assertEqual(a["assessment_status"], "COMPLETE")
        self.assertEqual(a["primary_signals"][0], "POSSIBLE_OBSOLESCENCE")
        self.assertEqual(a["primary_signals"][1], "LOW_SALES_VELOCITY")
        self.assertEqual(a["metadata"]["model_version"], "xgboost_v1")
