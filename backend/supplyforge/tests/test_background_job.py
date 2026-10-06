import tempfile
import os
from django.test import TestCase
from supplyforge.models import Workspace, BackgroundJob, IngestionSession
from supplyforge.tasks import run_import_pipeline


class BackgroundJobTestCase(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Workspace", slug="test-workspace")
        
        # Create a temporary dummy CSV file for test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".csv", mode="w+", delete=False, encoding="utf-8")
        self.temp_file.write("sku,name,price,quantity\nSKU1,Product 1,100,10\n")
        self.temp_file.close()

        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="test_sales.csv",
            storage_path=self.temp_file.name,
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

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

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
