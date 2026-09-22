import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.analytics.module02_acceptance_engine import Module02AcceptanceEngine


class Module02AcceptanceEngineTestCase(TestCase):
    """Test suite for Module 02 Analytics — M2-10 Risk Dashboard UI & Module 02 Acceptance."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Module02 Acceptance WS", slug="test-ws-m2-acc")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        os.makedirs(reports_dir, exist_ok=True)

    def test_run_module02_acceptance(self):
        """Test 18-criteria acceptance protocol and release summary generation."""
        df_risk = pd.DataFrame([
            {'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'risk_level': 'CRITICAL', 'sales_velocity_30d': 0.005, 'dsls': 240, 'zero_rate_90d': 0.97},
            {'sku': 'SKU_102', 'canonical_sku_id': 'CSKU_102', 'product_name': 'Diaper Moony', 'risk_level': 'LOW_RISK', 'sales_velocity_30d': 2.0, 'dsls': 2, 'zero_rate_90d': 0.25}
        ])

        engine = Module02AcceptanceEngine(session_id=str(self.session.id))
        result = engine.run_module02_acceptance(risk_dataset_df=df_risk, session_id=str(self.session.id))

        self.assertEqual(result["status"], "✅ MODULE 02 ACCEPTED")
        cert = result["certificate"]
        self.assertEqual(cert["status"], "✅ MODULE 02 ACCEPTED")
        self.assertEqual(cert["temporal_leakage_count"], 0)
        self.assertEqual(cert["summary_metrics"]["totalSkus"], 2)
        self.assertEqual(cert["summary_metrics"]["criticalRisk"], 1)
        self.assertEqual(cert["summary_metrics"]["lowRisk"], 1)
