import io
from django.test import TestCase
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.models import ArchivedDataSet, Order, OrderItem, Product


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

    def test_initial_import_replaces_operational_data_and_retains_training_snapshot(self):
        """INITIAL must replace only this user's active data while retaining lineage."""
        user_id = 'user_replace_dataset_001'
        other_user_id = 'user_other_tenant_001'
        old_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "OLD-001,OLD-SKU,Hàng cũ,100000,2,2026-01-10\n"
        )
        new_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "NEW-001,NEW-SKU,Hàng mới,200000,1,2026-02-10\n"
        )
        other_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "OTHER-001,OTHER-SKU,Hàng tenant khác,50000,1,2026-02-01\n"
        )

        DynamicFileImportService.process_batch_import(
            io.BytesIO(old_csv.encode('utf-8')), {}, user_id, session_type='INITIAL'
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(other_csv.encode('utf-8')), {}, other_user_id, session_type='INITIAL'
        )

        result = DynamicFileImportService.process_batch_import(
            io.BytesIO(new_csv.encode('utf-8')), {}, user_id, session_type='INITIAL'
        )

        self.assertEqual(result['import_type'], 'INITIAL')
        self.assertEqual(list(Order.objects.filter(user_id=user_id).values_list('order_id', flat=True)), ['NEW-001'])
        self.assertEqual(list(Product.objects.filter(user_id=user_id).values_list('item_sku', flat=True)), ['NEW-SKU'])
        self.assertEqual(Order.objects.filter(user_id=other_user_id).count(), 1)

        archive = ArchivedDataSet.objects.filter(user_id=user_id).latest('archived_at')
        self.assertEqual(archive.reason, 'INITIAL_IMPORT_REPLACED')
        self.assertEqual(archive.snapshot_json['orders'][0]['order_id'], 'OLD-001')
        self.assertEqual(len(archive.snapshot_json['order_items']), 1)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 1)

    def test_invalid_initial_import_preserves_current_operational_data(self):
        """A malformed replacement must not leave the operational dataset empty."""
        user_id = 'user_invalid_replacement_001'
        valid_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "OLD-001,OLD-SKU,Hàng cũ,100000,2,2026-01-10\n"
        )
        invalid_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "INVALID-001,INVALID-SKU,Hàng lỗi,100000,0,2026-02-10\n"
        )

        DynamicFileImportService.process_batch_import(
            io.BytesIO(valid_csv.encode('utf-8')), {}, user_id, session_type='INITIAL'
        )

        with self.assertRaisesMessage(ValueError, 'Không có dòng dữ liệu hợp lệ'):
            DynamicFileImportService.process_batch_import(
                io.BytesIO(invalid_csv.encode('utf-8')), {}, user_id, session_type='INITIAL'
            )

        self.assertEqual(
            list(Order.objects.filter(user_id=user_id).values_list('order_id', flat=True)),
            ['OLD-001'],
        )
        self.assertFalse(ArchivedDataSet.objects.filter(user_id=user_id).exists())
