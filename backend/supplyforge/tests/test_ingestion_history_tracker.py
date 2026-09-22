import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models import IngestionSession, Workspace
from src.ingestion.ingestion_history_tracker import IngestionHistoryTracker


class IngestionHistoryTrackerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-09 Ingestion History."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test History WS", slug="test-ws-hist")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_august_batch.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )

    def test_record_ingestion_event(self):
        """Test recording ingestion events and generating unique ingestion_id."""
        tracker = IngestionHistoryTracker(session_id=str(self.session.id))
        res = tracker.record_ingestion_event(
            session_id=str(self.session.id),
            stage="COMPLETED",
            status="COMPLETED",
            filename=self.session.original_filename,
            stats={'totalRecords': 500, 'inserted': 450, 'duplicatesSkipped': 50},
            version_info={'currentVersion': 'v1.0'}
        )

        self.assertTrue(res["ingestionId"].startswith("ING-"))
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["sessionRecord"]["statistics"]["totalRecords"], 500)

    def test_export_artifacts(self):
        """Test exporter creates 6 standard artifacts in reports/."""
        tracker = IngestionHistoryTracker(session_id=str(self.session.id))
        res = tracker.record_ingestion_event(
            session_id=str(self.session.id),
            stage="COMPLETED",
            status="COMPLETED",
            filename=self.session.original_filename
        )

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        artifacts = tracker.export_artifacts(
            history_list=[res["sessionRecord"]],
            proc_logs=[],
            statistics=res["sessionRecord"]["statistics"],
            error_logs=[],
            ver_history=[],
            audit_logs=[],
            output_dir=reports_dir
        )

        self.assertTrue(os.path.exists(artifacts["ingestion_history"]))
        self.assertTrue(os.path.exists(artifacts["ingestion_processing_log"]))
        self.assertTrue(os.path.exists(artifacts["ingestion_statistics"]))
        self.assertTrue(os.path.exists(artifacts["ingestion_error_log"]))
        self.assertTrue(os.path.exists(artifacts["dataset_version_history"]))
        self.assertTrue(os.path.exists(artifacts["ingestion_audit_log"]))
