import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_scoring_engine import RiskScoringEngine


class RiskScoringEngineTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-02 Risk Scoring Engine."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Scoring WS", slug="test-ws-rs-eng")
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

    def test_calculate_risk_scores(self):
        """Test normalized risk scoring (0-100), priority mapping, and 4-rule score consistency audit."""
        df_preds = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'risk_class': 'CRITICAL', 'risk_probability': 0.990,
                'critical_probability': 0.990, 'high_risk_probability': 0.008,
                'medium_risk_probability': 0.001, 'low_risk_probability': 0.001
            }
        ])

        engine = RiskScoringEngine(session_id=str(self.session.id))
        result = engine.calculate_risk_scores(predictions_df=df_preds, session_id=str(self.session.id))

        self.assertEqual(result["status"], "SUCCESS")
        scores = result["scores"]
        self.assertEqual(len(scores), 1)
        s = scores[0]
        self.assertEqual(s["risk_score"], 99.0)
        self.assertEqual(s["risk_priority"], "P0")
        self.assertEqual(s["scoring_status"], "VALID")
