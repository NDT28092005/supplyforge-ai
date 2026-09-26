import io
from django.test import TestCase
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.models import Product, Order, OrderItem


class DuplicateAndOverlapTestCase(TestCase):
    """Test suite verifying IR-005 Duplicate Detection, IR-006 Partial Overlap, and IR-007 Re-import requirements."""

    def test_ir005_duplicate_detection(self):
        """IR-005: Importing identical record twice must skip duplicate and report metrics correctly."""
        user_id = 'user_ir005_test'
        csv_1 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD001,SKU001,Sản phẩm 1,150000,10,2026-07-01\n"
        )
        res_1 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_1.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        self.assertEqual(res_1["status"], "DATA_READY")
        self.assertEqual(res_1["rows_received"], 1)
        self.assertEqual(res_1["new_rows"], 1)
        self.assertEqual(res_1["duplicate_rows"], 0)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 1)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 1)

        # Import identical record again
        res_2 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_1.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', force_reset=False
        )

        self.assertEqual(res_2["status"], "DATA_READY")
        self.assertEqual(res_2["rows_received"], 1)
        self.assertEqual(res_2["new_rows"], 0)
        self.assertEqual(res_2["duplicate_rows"], 1)
        # Verify DB does NOT create duplicate ORD001 or OrderItem
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 1)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 1)

    def test_ir006_partial_overlap(self):
        """IR-006: Importing file with overlapping date range must segment overlap, skip existing keys, insert new ones."""
        user_id = 'user_ir006_test'

        # Existing dataset: 2026-01-01 -> 2026-06-30
        csv_existing = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-001,SKU-A,Sản phẩm A,100000,2,2026-01-15\n"
            "ORD-002,SKU-B,Sản phẩm B,200000,1,2026-06-20\n"
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_existing.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        # New file: 2026-06-15 -> 2026-07-15 (Partial overlap 2026-06-15 -> 2026-06-30)
        csv_new = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-002,SKU-B,Sản phẩm B,200000,1,2026-06-20\n"  # Duplicate record in overlap zone
            "ORD-003,SKU-C,Sản phẩm C,300000,5,2026-07-10\n"  # New record
        )
        res_overlap = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_new.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', force_reset=False
        )

        self.assertEqual(res_overlap["status"], "DATA_READY")
        self.assertTrue(res_overlap["overlap_detected"])
        self.assertEqual(res_overlap["rows_received"], 2)
        self.assertEqual(res_overlap["new_rows"], 1)
        self.assertEqual(res_overlap["duplicate_rows"], 1)

        temp_range = res_overlap["temporal_range"]
        self.assertEqual(temp_range["existing_start"], "2026-01-15")
        self.assertEqual(temp_range["existing_end"], "2026-06-20")
        self.assertEqual(temp_range["incoming_start"], "2026-06-20")
        self.assertEqual(temp_range["incoming_end"], "2026-07-10")
        self.assertTrue(temp_range["overlap_detected"])
        self.assertEqual(temp_range["overlap_start"], "2026-06-20")
        self.assertEqual(temp_range["overlap_end"], "2026-06-20")

        # Database state: ORD-001, ORD-002, ORD-003 exist (total 3 orders, total 3 items)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 3)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 3)

    def test_ir007_reimport_same_file(self):
        """IR-007: Re-importing exact same file twice must result in 0 inserted, 100% duplicate on run #2."""
        user_id = 'user_ir007_test'

        rows = ["order_id,sku,product_name,selling_price,quantity,order_date"]
        for i in range(1, 101):
            rows.append(f"ORD-{i:03d},SKU-{i:03d},Sản phẩm {i},100000,1,2026-05-01")
        csv_content = "\n".join(rows) + "\n"

        # Import #1
        res_1 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_content.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )

        self.assertEqual(res_1["status"], "DATA_READY")
        self.assertEqual(res_1["rows_received"], 100)
        self.assertEqual(res_1["new_rows"], 100)
        self.assertEqual(res_1["duplicate_rows"], 0)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 100)

        # Import #2 (Same file uploaded second time)
        res_2 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_content.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', force_reset=False
        )

        self.assertEqual(res_2["status"], "DATA_READY")
        self.assertEqual(res_2["rows_received"], 100)
        self.assertEqual(res_2["new_rows"], 0)
        self.assertEqual(res_2["duplicate_rows"], 100)

        # Total database records must remain strictly 100 (NOT 200)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 100)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 100)

    def test_ir008_data_correction_upsert(self):
        """IR-008: Data correction re-import must upsert canonical Order/OrderItem and log versioned audit trail."""
        user_id = 'user_ir008_test'

        # Import #1: ORD001 with price = 100,000
        csv_1 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD001,SKU001,Sản phẩm 1,100000,1,2026-07-01\n"
        )
        res_1 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_1.encode('utf-8')), {}, user_id, session_type='INITIAL', force_reset=True
        )
        self.assertEqual(res_1["status"], "DATA_READY")
        self.assertEqual(res_1["new_rows"], 1)

        order_1 = Order.objects.get(user_id=user_id, order_id='ORD001')
        self.assertEqual(order_1.amount, 100000)

        # Import #2: Merchant re-uploads corrected file with ORD001 price = 120,000
        csv_2 = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD001,SKU001,Sản phẩm 1,120000,1,2026-07-01\n"
        )
        res_2 = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_2.encode('utf-8')), {}, user_id, session_type='INCREMENTAL', force_reset=False
        )

        self.assertEqual(res_2["status"], "DATA_READY")
        self.assertEqual(res_2["new_rows"], 0)
        self.assertEqual(res_2["duplicate_rows"], 0)
        self.assertEqual(res_2["updated_rows"], 1)
        self.assertEqual(len(res_2["data_corrections"]), 1)

        audit_entry = res_2["data_corrections"][0]
        self.assertEqual(audit_entry["order_id"], "ORD001")
        self.assertEqual(audit_entry["sku"], "SKU001")
        self.assertEqual(audit_entry["old_values"]["price"], 100000.0)
        self.assertEqual(audit_entry["new_values"]["price"], 120000.0)

        # Verify DB order amount was updated to 120,000 and total orders remained 1
        order_updated = Order.objects.get(user_id=user_id, order_id='ORD001')
        self.assertEqual(order_updated.amount, 120000)
        self.assertEqual(Order.objects.filter(user_id=user_id).count(), 1)
        self.assertEqual(OrderItem.objects.filter(order__user_id=user_id).count(), 1)

