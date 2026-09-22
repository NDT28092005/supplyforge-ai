import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.risk_feature_assembler import RiskFeatureAssembler, FeatureLeakageError


class RiskFeatureAssemblerTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-03 Slow-Moving Risk Feature Assembly."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Risk Assembly WS", slug="test-ws-risk-asm")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_assemble_risk_features(self):
        """Test assembling M2-01 and M2-02 features into Risk Feature Matrix."""
        df_m201 = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'sales_velocity_30d': 0.5, 'dsls': 10, 'zero_rate_90d': 0.3, 'adi': 1.2, 'cv2': 0.3}
        ])
        df_m202 = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'demand_pattern': 'SMOOTH'}
        ])

        assembler = RiskFeatureAssembler(session_id=str(self.session.id))
        result = assembler.assemble_risk_features(features_m201_df=df_m201, patterns_m202_df=df_m202, session_id=str(self.session.id))

        self.assertEqual(result["totalSkus"], 1)
        self.assertEqual(result["summary"]["leakageCheckStatus"], "PASSED")
        recs = result["riskFeatureRecords"]
        self.assertEqual(recs[0]["demand_pattern"], "SMOOTH")
        self.assertEqual(recs[0]["is_smooth"], 1)
        self.assertEqual(recs[0]["is_lumpy"], 0)

    def test_feature_leakage_interception(self):
        """Test that forbidden columns raise FeatureLeakageError."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'fut_qty_60d': 500}
        ])

        assembler = RiskFeatureAssembler(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            assembler.assemble_risk_features(features_m201_df=df_leak, patterns_m202_df=None, session_id=str(self.session.id))
