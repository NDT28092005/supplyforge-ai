import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.feature_snapshot_engine import FeatureSnapshotEngine


class FeatureSnapshotEngineTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-09 Feature Snapshot & Downstream Handoff."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Feature Snapshot WS", slug="test-ws-feat-snap")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        contract_dir = os.path.join(PROJECT_ROOT, "contracts")
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(contract_dir, exist_ok=True)

    def test_create_feature_snapshot_and_contract(self):
        """Test feature snapshot creation, checksum generation, lineage tracing, and downstream contract export."""
        df_val = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'sales_velocity_30d': 0.005, 'dsls': 240, 'zero_rate_90d': 0.97, 'adi': 4.5, 'cv2': 1.2}
        ])

        engine = FeatureSnapshotEngine(session_id=str(self.session.id))
        result = engine.create_feature_snapshot_and_contract(validated_feature_matrix_df=df_val, dataset_version="v1.0", session_id=str(self.session.id))

        self.assertEqual(result["featureVersion"], "M2-FEATURE-v1.0")
        self.assertEqual(result["contractVersion"], "risk_model_feature_contract_v1")
        self.assertEqual(result["status"], "FROZEN")
        self.assertTrue(result["checksum"].startswith("sha256:"))

        contract = result["contract"]
        self.assertEqual(contract["contract_status"], "ACTIVE_HANDOVER")
        self.assertNotIn("fut_qty_60d", contract["allowed_features"])
