import io
from django.test import TestCase
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.models import Product, Order, ArchivedDataSet


class IncrementalImportTestCase(TestCase):
    """Test suite verifying IR-004 Incremental Import requirements and Archival Backup clear_data."""

    def test_incremental_import_pipeline(self):
        """Test initial import followed by incremental import appending new records and preserving old data."""
        user_id = 'user_incremental_test_001'

        # 1. Initial Import (2026-01-01 -> 2026-06-30)
        csv_1 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-001,SKU-A,Sản phẩm A,100000,2,2026-01-15\n"
            "ORD-002,SKU-B,Sản phẩm B,200000,1,2026-03-20\n"
        )
        res_1 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_1.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        self.assertEqual(res_1["status"], "DATA_READY")
        self.assertEqual(res_1["import_type"], "INITIAL")
        self.assertEqual(Product.objects.filter(user_id=user_id).count(), 2)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 2)

        # 2. Incremental Import (2026-07-01 -> 2026-07-31)
        csv_2 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-003,SKU-A,Sản phẩm A,100000,5,2026-07-10\n"
            "ORD-004,SKU-C,Sản phẩm C,500000,1,2026-07-25\n"
            "ORD-001,SKU-A,Sản phẩm A,100000,2,2026-01-15\n"  # Duplicate of old order ORD-001
        )
        res_2 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_2.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', force_reset=False
        )

        self.assertEqual(res_2["status"], "DATA_READY")
        self.assertEqual(res_2["import_type"], "INCREMENTAL")
        self.assertTrue(res_2["schema_matched"])
        self.assertEqual(res_2["duplicate_rows"], 1)

        # Verify old data is preserved and new records appended
        self.assertEqual(Product.objects.filter(user_id=user_id).count(), 3)  # SKU-A, SKU-B, SKU-C
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 4)    # ORD-001, ORD-002, ORD-003, ORD-004

    def test_clear_data_archival_backup(self):
        """Verify clear_data archives active products and orders in ArchivedDataSet before resetting."""
        user_id = 'user_clear_test_002'

        csv_content = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-999,SKU-X,Sản phẩm X,990000,1,2026-05-01\n"
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_content.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        self.assertEqual(Product.objects.filter(user_id=user_id).count(), 1)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 1)

        # Trigger clear_data
        DynamicFileImportService.clear_data(user_id)

        # Active products & orders should be reset for UI visualization
        self.assertEqual(Product.objects.filter(user_id=user_id).count(), 0)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 0)

        # Backup snapshot should be safely stored in ArchivedDataSet for AI training
        archived_records = ArchivedDataSet.objects.filter(user_id=user_id)
        self.assertEqual(archived_records.count(), 1)
        archive = archived_records.first()
        self.assertEqual(archive.product_count, 1)
        self.assertEqual(archive.order_count, 1)
        self.assertIn("products", archive.snapshot_json)
        self.assertIn("orders", archive.snapshot_json)
