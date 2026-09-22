import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.feature_readiness_gate import FeatureReadinessGate, FeatureLeakageError


class FeatureReadinessGateTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-08 Feature Validation & Readiness Gate."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Feature Gate WS", slug="test-ws-feat-gate")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_validate_and_freeze_feature_matrix(self):
        """Test 8-protocol validation and Readiness Certificate issuance."""
        df_full = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'sales_velocity_30d': 0.005, 'dsls': 240, 'zero_rate_90d': 0.97, 'adi': 4.5, 'cv2': 1.2}
        ])

        gate = FeatureReadinessGate(session_id=str(self.session.id))
        result = gate.validate_and_freeze_feature_matrix(full_feature_matrix_df=df_full, session_id=str(self.session.id))

        self.assertEqual(result["status"], "READY")
        cert = result["certificate"]
        self.assertEqual(cert["status"], "READY")
        self.assertEqual(cert["temporal_leakage_count"], 0)
        self.assertEqual(cert["downstream_status"], "READY FOR RISK MODEL / DSS")

    def test_leakage_blocks_feature_readiness_gate(self):
        """Test that forbidden future columns block the readiness gate."""
        df_leak = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'fut_qty_60d': 15}
        ])

        gate = FeatureReadinessGate(session_id=str(self.session.id))
        with self.assertRaises(FeatureLeakageError):
            gate.validate_and_freeze_feature_matrix(full_feature_matrix_df=df_leak, session_id=str(self.session.id))
