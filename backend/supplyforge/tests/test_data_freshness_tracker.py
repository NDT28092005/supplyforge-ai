import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.data_freshness_tracker import DataFreshnessTracker


class DataFreshnessTrackerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-08 Data Freshness Tracking."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Freshness WS", slug="test-ws-fresh")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_august_fresh.csv",
            status="MAPPED",
            column_mapping_json={
                "mappings": [
                    {"source_column": "sku_code", "canonical_field": "sku"},
                    {"source_column": "trans_date", "canonical_field": "date"},
                    {"source_column": "qty", "canonical_field": "quantity"},
                ]
            }
        )

    def test_freshness_evaluation_success(self):
        """Test freshness days calculation and FRESH/STALE status classification."""
        df = pd.DataFrame({
            "sku_code": ["SKU_101", "SKU_102"],
            "trans_date": ["2026-08-01", "2026-08-15"],
            "qty": [10, 5],
        })

        tracker = DataFreshnessTracker(session_id=str(self.session.id))
        status_res = tracker.evaluate_freshness(
            df=df,
            mapping_result=self.session.column_mapping_json,
            current_date="2026-08-16"
        )

        self.assertEqual(status_res["freshnessStatus"], "FRESH")
        self.assertEqual(status_res["freshnessDays"], 1)
        self.assertTrue(status_res["decisionGuard"]["canRunCurrentAnalysis"])

    def test_export_artifacts(self):
        """Test exporter creates 4 standard artifacts in reports/."""
        df = pd.DataFrame({
            "sku_code": ["SKU_201"],
            "trans_date": ["2026-08-10"],
            "qty": [15],
        })

        tracker = DataFreshnessTracker(session_id=str(self.session.id))
        status_res = tracker.evaluate_freshness(df, mapping_result=self.session.column_mapping_json, current_date="2026-08-16")

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        artifacts = tracker.export_artifacts(status_res, output_dir=reports_dir)

        self.assertTrue(os.path.exists(artifacts["data_freshness_status"]))
        self.assertTrue(os.path.exists(artifacts["dataset_coverage_report"]))
        self.assertTrue(os.path.exists(artifacts["freshness_alerts"]))
        self.assertTrue(os.path.exists(artifacts["sku_freshness_report_csv"]))
