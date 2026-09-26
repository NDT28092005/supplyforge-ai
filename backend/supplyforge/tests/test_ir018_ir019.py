import io
import json
from django.test import TestCase, Client
from supplyforge.models import IngestionSession, Product, Order, Workspace
from supplyforge.services.concurrency_manager import ImportConcurrencyManager
from supplyforge.services.dataset_consistency import DatasetConsistencyValidator
from supplyforge.services.ingestion import DynamicFileImportService


class ConcurrentImportAndDatasetConsistencyTestCase(TestCase):
    """
    Test suite verifying:
    - IR-018 Concurrent Import: Option 2 Queueing Strategy (QUEUED) & Option 1 Reject Strategy (IMPORT_ALREADY_RUNNING).
    - IR-019 Dataset Consistency: Post-import SKU count, row checksum, date range, and null/duplicate checks.
    """

    def setUp(self):
        self.client = Client()
        self.user_id = 'test_merchant_ir018_ir019'
        self.workspace, _ = Workspace.objects.get_or_create(id=1, defaults={'name': 'Test Workspace'})

    def test_ir018_concurrent_import_queue_strategy(self):
        """Test IR-018: Simultaneous uploads queue second upload (QUEUED status) and dequeue when active finishes."""
        # Active processing session A
        session_a = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="file_A.csv",
            status="PROCESSING"
        )

        # Session B uploaded while session A is PROCESSING
        session_b = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="file_B.csv",
            status="UPLOADING"
        )

        # Evaluate concurrency for Session B (Queue Policy)
        res_b = ImportConcurrencyManager.evaluate_and_register_session(session_b, policy='queue')
        self.assertEqual(res_b["status"], "QUEUED")
        self.assertEqual(res_b["activeSessionId"], str(session_a.id))

        session_b.refresh_from_db()
        self.assertEqual(session_b.status, "QUEUED")

        # Session A completes processing → dequeue next session
        session_a.status = 'COMPLETED'
        session_a.save()

        dequeued = ImportConcurrencyManager.dequeue_next_session(self.workspace.id)
        self.assertIsNotNone(dequeued)
        self.assertEqual(dequeued.id, session_b.id)
        self.assertEqual(dequeued.status, "PROCESSING")

    def test_ir018_concurrent_import_reject_strategy(self):
        """Test IR-018 Option 1: Reject concurrent upload with IMPORT_ALREADY_RUNNING error code."""
        IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="running_file.csv",
            status="PROCESSING"
        )

        session_concurrent = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="rejected_file.csv",
            status="UPLOADING"
        )

        res_reject = ImportConcurrencyManager.evaluate_and_register_session(session_concurrent, policy='reject')
        self.assertEqual(res_reject["status"], "REJECTED")
        self.assertEqual(res_reject["error_code"], "IMPORT_ALREADY_RUNNING")

        session_concurrent.refresh_from_db()
        self.assertEqual(session_concurrent.status, "FAILED")

    def test_ir019_dataset_consistency_validation(self):
        """Test IR-019: Post-import dataset consistency validation (before SKU + new SKU == after SKU)."""
        user_id = "user_consistency_test_99"

        # 1. Initial Import (2 SKUs)
        csv_1 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-001,SKU-A,Product A,100000,2,2026-05-01\n"
            "ORD-002,SKU-B,Product B,200000,1,2026-05-02\n"
        )
        res_1 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_1.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        self.assertEqual(res_1["status"], "DATA_READY")
        self.assertIn("dataset_consistency", res_1)
        c_1 = res_1["dataset_consistency"]
        self.assertEqual(c_1["status"], "CONSISTENT")
        self.assertTrue(c_1["sku_count_check"]["matched"])
        self.assertEqual(c_1["sku_count_check"]["after_sku_count"], 2)

        # 2. Incremental Import (1 new SKU-C, 1 existing SKU-A)
        session_inc = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="inc_file.csv",
            status="PROCESSING"
        )

        csv_2 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-003,SKU-C,Product C,300000,5,2026-06-01\n"
            "ORD-001,SKU-A,Product A,100000,2,2026-05-01\n"  # Duplicate order line
        )
        res_2 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_2.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', session_id=session_inc.id
        )

        self.assertEqual(res_2["status"], "DATA_READY")
        c_2 = res_2["dataset_consistency"]
        self.assertEqual(c_2["status"], "CONSISTENT")
        self.assertTrue(c_2["sku_count_check"]["matched"])

        # Validate math: before_sku_count (2) + new_sku_count (1) == after_sku_count (3)
        self.assertEqual(c_2["sku_count_check"]["before_sku_count"], 2)
        self.assertEqual(c_2["sku_count_check"]["new_sku_count"], 1)
        self.assertEqual(c_2["sku_count_check"]["after_sku_count"], 3)
        self.assertTrue(c_2["row_count_check"]["checksum_matched"])

        # Check session DB record
        session_inc.refresh_from_db()
        self.assertEqual(session_inc.dataset_consistency_status, "CONSISTENT")
        self.assertIsNotNone(session_inc.dataset_consistency_json)
