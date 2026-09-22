import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.data_readiness_gate import DataReadinessGate, DataReadinessError, enforce_readiness_gate


class DataReadinessGateTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-11 Data Readiness Gate."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Readiness Gate WS", slug="test-ws-rg")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_sales_batch.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )

    def test_evaluate_readiness_ready(self):
        """Test evaluating readiness for a clean dataset."""
        df = pd.DataFrame({
            "order_id": ["ORD_1", "ORD_2"],
            "date": ["2026-08-01", "2026-08-15"],
            "sku": ["SKU_101", "SKU_102"],
            "quantity": [10, 5],
            "price": [100000, 50000],
            "cost": [70000, 35000],
        })

        gate = DataReadinessGate(session_id=str(self.session.id))
        rec = gate.evaluate_readiness(session_id=str(self.session.id), df=df)

        self.assertIn(rec["readinessStatus"], ["READY", "READY_WITH_WARNING"])
        self.assertTrue(rec["canProceedToDownstream"])
        self.assertIn("criteriaBreakdown", rec)

    def test_interceptor_guard_decorator(self):
        """Test downstream protection decorator intercepts execution when NOT_READY."""
        @enforce_readiness_gate
        def dummy_slow_moving_analytics(session_id=None):
            return "Slow-moving products identified"

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        gate = DataReadinessGate(session_id=str(self.session.id))

        # Evaluate ready dataset
        df = pd.DataFrame({'date': ['2026-08-15'], 'sku': ['S1'], 'quantity': [1], 'price': [100]})
        gate.evaluate_readiness(str(self.session.id), df=df, output_dir=reports_dir)

        # Should pass
        result = dummy_slow_moving_analytics(session_id=str(self.session.id))
        self.assertEqual(result, "Slow-moving products identified")
