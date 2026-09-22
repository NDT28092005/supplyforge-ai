import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.demand_pattern_classifier import DemandPatternClassifier


class DemandPatternClassifierTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-02 Demand Pattern Classification."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Pattern WS", slug="test-ws-pattern")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_classify_demand_patterns(self):
        """Test classifying SKU demand patterns according to Syntetos-Boylan matrix."""
        features_df = pd.DataFrame([
            {'sku': 'SKU_MILK', 'canonical_sku_id': 'CSKU_MILK', 'product_name': 'Milk 900g', 'adi': 1.1, 'cv2': 0.3, 'zero_rate_90d': 0.1, 'sales_velocity_90d': 5.0},
            {'sku': 'SKU_DIAPER', 'canonical_sku_id': 'CSKU_DIAPER', 'product_name': 'Moony Diaper', 'adi': 2.5, 'cv2': 0.8, 'zero_rate_90d': 0.8, 'sales_velocity_90d': 0.2},
        ])

        classifier = DemandPatternClassifier(session_id=str(self.session.id))
        result = classifier.classify_demand_patterns(features_df=features_df, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 2)
        recs = result["demandPatternRecords"]
        self.assertEqual(recs[0]["demand_pattern"], "SMOOTH")
        self.assertEqual(recs[1]["demand_pattern"], "LUMPY")
        self.assertIn("SMOOTH_DEMAND", recs[0]["demand_signals"])
        self.assertIn("LUMPY_DEMAND", recs[1]["demand_signals"])
        self.assertIn("Academic Boundary Notice", result["summary"]["academicNotice"])
