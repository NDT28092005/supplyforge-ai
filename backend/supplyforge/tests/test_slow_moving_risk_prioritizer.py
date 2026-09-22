import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.slow_moving_risk_prioritizer import SlowMovingRiskPrioritizer, FeatureLeakageError


class SlowMovingRiskPrioritizerTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-07 Slow-Moving Risk Ranking & Prioritization."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Prioritization WS", slug="test-ws-risk-prio")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_prioritize_slow_moving_risk(self):
        """Test hierarchical sorting and Priority Score calculation."""
        df_m206 = pd.DataFrame([
            {'sku': 'SKU_102', 'canonical_sku_id': 'CSKU_102', 'product_name': 'Diaper Moony', 'risk_level': 'HIGH_RISK', 'risk_probability': 0.88, 'slow_moving_signal_score': 0.65, 'dsls': 45},
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'risk_level': 'CRITICAL', 'risk_probability': 0.99, 'slow_moving_signal_score': 0.95, 'dsls': 240}
        ])

        prioritizer = SlowMovingRiskPrioritizer(session_id=str(self.session.id))
        result = prioritizer.prioritize_slow_moving_risk(risk_classifications_m206_df=df_m206, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 2)
        self.assertEqual(result["summary"]["leakageCheckStatus"], "PASSED")
        recs = result["prioritizedQueueRecords"]

        # Rank 1 must be CRITICAL SKU_101
        self.assertEqual(recs[0]["canonical_sku_id"], "CSKU_101")
        self.assertEqual(recs[0]["priority_rank"], 1)
        self.assertEqual(recs[0]["priority_segment"], "P1 — Immediate Attention")

        # Rank 2 must be HIGH_RISK SKU_102
        self.assertEqual(recs[1]["canonical_sku_id"], "CSKU_102")
        self.assertEqual(recs[1]["priority_rank"], 2)
        self.assertEqual(recs[1]["priority_segment"], "P2 — High Attention")

    def test_prioritization_leakage_interception(self):
        """Test that forbidden future columns raise FeatureLeakageError."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'fut_qty_60d': 0}
        ])

        prioritizer = SlowMovingRiskPrioritizer(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            prioritizer.prioritize_slow_moving_risk(risk_classifications_m206_df=df_leak, session_id=str(self.session.id))
