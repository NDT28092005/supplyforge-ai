from django.test import TestCase
from supplyforge.models import Workspace, BackgroundJob, IngestionSession
from supplyforge.tasks import run_import_pipeline


class BackgroundJobTestCase(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Workspace", slug="test-workspace")
        
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="test_sales.csv",
            storage_path="/virtual/test_sales.csv",
            file_size_bytes=100,
            status="QUEUED"
        )
        self.job = BackgroundJob.objects.create(
            workspace=self.workspace,
            job_type="CSV_IMPORT",
            ingestion_session=self.session,
            status="PENDING",
            progress_pct=0
        )

    def test_job_creation(self):
        self.assertEqual(self.job.status, "PENDING")
        self.assertEqual(self.job.workspace, self.workspace)
        self.assertEqual(self.job.job_type, "CSV_IMPORT")

    def test_cancellation_request(self):
        self.job.status = "CANCEL_REQUESTED"
        self.job.save()

        res = run_import_pipeline(str(self.job.id))
        self.assertTrue(res.get("cancelled"))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "CANCELLED")
