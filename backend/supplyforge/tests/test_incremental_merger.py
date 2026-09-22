import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.incremental_merger import IncrementalMerger


class IncrementalMergerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-07 Incremental Upload & Dataset Merge."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Incremental WS", slug="test-ws-inc")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_august_batch.csv",
            status="MAPPED",
            column_mapping_json={
                "mappings": [
                    {"source_column": "sku_code", "canonical_field": "sku"},
                    {"source_column": "trans_date", "canonical_field": "date"},
                    {"source_column": "qty", "canonical_field": "quantity"},
                ]
            }
        )

    def test_incremental_merge_success(self):
        """Test incremental merge time overlap detection and record insert/skip."""
        df_batch1 = pd.DataFrame({
            "sku_code": ["SKU_101", "SKU_102"],
            "trans_date": ["2026-07-01", "2026-07-15"],
            "qty": [10, 5],
        })

        merger = IncrementalMerger(session_id=str(self.session.id))
        report1 = merger.merge_incremental_upload(df_batch1, mapping_result=self.session.column_mapping_json)

        self.assertEqual(report1["summary"]["inserted"], 2)
        self.assertEqual(report1["versionInfo"]["currentVersion"], "v1.0")

        df_batch2 = pd.DataFrame({
            "sku_code": ["SKU_101", "SKU_103"],
            "trans_date": ["2026-07-01", "2026-08-01"],  # 1 duplicate, 1 new period
            "qty": [10, 15],
        })

        report2 = merger.merge_incremental_upload(df_batch2, existing_df=merger._last_final_df, mapping_result=self.session.column_mapping_json)
        self.assertEqual(report2["summary"]["inserted"], 1)
        self.assertEqual(report2["summary"]["duplicatesSkipped"], 1)
        self.assertEqual(report2["versionInfo"]["currentVersion"], "v1.1")

    def test_export_artifacts(self):
        """Test exporter creates 8 standard artifacts in reports/."""
        df = pd.DataFrame({
            "sku_code": ["SKU_201"],
            "trans_date": ["2026-08-01"],
            "qty": [20],
        })

        merger = IncrementalMerger(session_id=str(self.session.id))
        report = merger.merge_incremental_upload(df, mapping_result=self.session.column_mapping_json)

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        artifacts = merger.export_artifacts(report, output_dir=reports_dir)

        self.assertTrue(os.path.exists(artifacts["incremental_dataset_csv"]))
        self.assertTrue(os.path.exists(artifacts["dataset_version"]))
        self.assertTrue(os.path.exists(artifacts["upload_metadata"]))
        self.assertTrue(os.path.exists(artifacts["merge_report"]))
        self.assertTrue(os.path.exists(artifacts["duplicate_records"]))
        self.assertTrue(os.path.exists(artifacts["updated_records"]))
        self.assertTrue(os.path.exists(artifacts["rejected_records"]))
        self.assertTrue(os.path.exists(artifacts["dataset_audit_log"]))
