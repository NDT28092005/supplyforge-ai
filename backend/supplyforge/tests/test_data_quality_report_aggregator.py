import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.data_quality_report_aggregator import DataQualityReportAggregator


class DataQualityReportAggregatorTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-10 Data Quality Report UI."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Quality Report WS", slug="test-ws-qr")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )

    def test_consolidated_report_generation(self):
        """Test generating consolidated report payload and readiness status."""
        df = pd.DataFrame({
            "order_id": ["ORD_1", "ORD_2"],
            "trans_date": ["2026-08-01", "2026-08-15"],
            "sku": ["SKU_101", "SKU_102"],
            "quantity": [10, 5],
            "price": [100000, 50000],
            "cost": [70000, 35000],
        })

        aggregator = DataQualityReportAggregator(session_id=str(self.session.id))
        report = aggregator.generate_consolidated_report(session_id=str(self.session.id), df=df)

        self.assertIn("overview", report)
        self.assertIn("analysisReadiness", report)
        self.assertIn("dimensions", report)
        self.assertIn("validationGrid", report)

    def test_export_artifacts(self):
        """Test exporter creates 6 standard artifacts in reports/."""
        aggregator = DataQualityReportAggregator(session_id=str(self.session.id))
        report = aggregator.generate_consolidated_report(session_id=str(self.session.id))

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        artifacts = aggregator.export_artifacts(report, output_dir=reports_dir)

        self.assertTrue(os.path.exists(artifacts["data_quality_dashboard"]))
        self.assertTrue(os.path.exists(artifacts["validation_status"]))
        self.assertTrue(os.path.exists(artifacts["field_quality_report"]))
        self.assertTrue(os.path.exists(artifacts["quality_issue_list"]))
        self.assertTrue(os.path.exists(artifacts["analysis_readiness_status"]))
        self.assertTrue(os.path.exists(artifacts["quality_trend"]))
