import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_classification_engine import RiskClassificationEngine


class RiskClassificationEngineTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-03 Risk Classification."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Classification WS", slug="test-ws-rc-eng")
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

    def test_classify_sku_risks(self):
        """Test Argmax classification, severity mapping, confidence calculation, and ambiguity detection."""
        df_scored = pd.DataFrame([
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'risk_score': 99.0,
                'critical_probability': 0.990, 'high_risk_probability': 0.008,
                'medium_risk_probability': 0.001, 'low_risk_probability': 0.001
            },
            {
                'sku': 'SKU_102', 'canonical_sku_id': 'CSKU_102', 'product_name': 'Diaper Moony',
                'risk_score': 41.0,
                'critical_probability': 0.410, 'high_risk_probability': 0.390,
                'medium_risk_probability': 0.120, 'low_risk_probability': 0.080
            }
        ])

        engine = RiskClassificationEngine(session_id=str(self.session.id))
        result = engine.classify_sku_risks(scored_df=df_scored, ambiguity_threshold=0.10, session_id=str(self.session.id))

        self.assertEqual(result["status"], "SUCCESS")
        cls_records = result["classifications"]
        self.assertEqual(len(cls_records), 2)

        c1 = cls_records[0]
        self.assertEqual(c1["risk_class"], "CRITICAL")
        self.assertEqual(c1["severity"], "SEVERE")
        self.assertEqual(c1["classification_status"], "CONFIDENT")

        c2 = cls_records[1]
        self.assertEqual(c2["risk_class"], "CRITICAL")
        self.assertEqual(c2["prob_margin"], 0.02)
        self.assertEqual(c2["classification_status"], "AMBIGUOUS")
