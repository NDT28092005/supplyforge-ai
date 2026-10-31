import os
import io
import json
from unittest.mock import patch
from django.test import TestCase, Client
from supplyforge.models import IngestionSession, Product, Order, User, Workspace, WorkspaceMember
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.views.auth import generate_access_token


class RawProcessedSeparationAndLineageTestCase(TestCase):
    """
    Test suite verifying:
    - IR-016 Raw / Processed Data Separation: Raw files stored under /raw remain untouched on processing failure.
      Processed canonical snapshots stored under /processed.
    - IR-017 Import Lineage: Every record can trace back to record -> import_id -> file -> merchant -> timestamp.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(
            email='ir016-owner@example.test', display_name='IR016 Owner',
            status=User.STATUS_ACTIVE, is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.user_id = str(self.user.id)
        self.workspace = Workspace.objects.create(name='Test Workspace', slug='ir016-workspace', owner=self.user)
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.user, role=User.ROLE_OWNER)
        self.client.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {generate_access_token(self.user, self.workspace.id)}'
        )

    def test_ir016_raw_processed_data_separation(self):
        """Verify files are saved under /raw and processed output exported under /processed without raw overwrite."""
        raw_dir = StreamingCSVProfiler.get_raw_upload_dir()
        processed_dir = StreamingCSVProfiler.get_processed_upload_dir()
        self.assertTrue(raw_dir.endswith(os.path.join('uploads', 'ingestion', 'raw')))
        self.assertTrue(processed_dir.endswith(os.path.join('uploads', 'ingestion', 'processed')))

        # Create session with raw storage file
        csv_data = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-LINEAGE-01,SKU-LINEAGE-1,Lineage Product,250000,3,2026-04-10\n"
        )
        dummy_raw_path = os.path.join(raw_dir, "test_raw_input.csv")
        with open(dummy_raw_path, 'w', encoding='utf-8') as f:
            f.write(csv_data)

        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="orders_july.csv",
            status="PROCESSING",
            raw_storage_path=dummy_raw_path,
            storage_path=dummy_raw_path
        )

        res = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_data.encode('utf-8')), {}, self.user_id, session_id=session.id
        )
        self.assertEqual(res["status"], "DATA_READY")

        # Verify raw file remains intact
        self.assertTrue(os.path.exists(dummy_raw_path))
        with open(dummy_raw_path, 'r', encoding='utf-8') as rf:
            self.assertEqual(rf.read(), csv_data)

        # Verify processed snapshot exported in /processed directory
        session.refresh_from_db()
        self.assertTrue(bool(session.processed_storage_path))
        self.assertTrue(os.path.exists(session.processed_storage_path))
        with open(session.processed_storage_path, 'r', encoding='utf-8') as pf:
            proc_payload = json.load(pf)
            self.assertIn("import_id", proc_payload)
            self.assertEqual(proc_payload["original_filename"], "orders_july.csv")
            self.assertIn("SKU-LINEAGE-1", proc_payload["canonical_skus"])

    def test_ir016_raw_preservation_on_failure(self):
        """Verify raw input file is NEVER overwritten or deleted if processing fails."""
        raw_dir = StreamingCSVProfiler.get_raw_upload_dir()
        dummy_raw_path = os.path.join(raw_dir, "failing_raw_input.csv")
        raw_content = "corrupted_order_data_stream\n"
        with open(dummy_raw_path, 'w', encoding='utf-8') as f:
            f.write(raw_content)

        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="corrupted.csv",
            status="PROCESSING",
            raw_storage_path=dummy_raw_path
        )

        with patch('supplyforge.models.Product.objects.bulk_create', side_effect=RuntimeError("Simulated Pipeline Error")):
            with self.assertRaises(RuntimeError):
                DynamicFileImportService.process_batch_import(
                    io.BytesIO("order_id,sku,product_name,selling_price,quantity,order_date\nORD-1,SKU-1,P,10,1,2026-01-01\n".encode('utf-8')),
                    {}, self.user_id, session_id=session.id
                )

        # Ensure raw file remains 100% intact on failure for audit & debugging
        self.assertTrue(os.path.exists(dummy_raw_path))
        with open(dummy_raw_path, 'r', encoding='utf-8') as rf:
            self.assertEqual(rf.read(), raw_content)

    def test_ir017_import_lineage_tracing(self):
        """Verify IR-017: Record lineage tracing API returns record -> import_id -> file -> merchant -> timestamp."""
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="sales_q3_report.csv",
            status="PROCESSING",
            ingestion_id="IMP-20260922-001"
        )

        csv_content = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-TRACE-99,SKU-TRACE-99,Trace Product,990000,1,2026-09-22\n"
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_content.encode('utf-8')), {}, self.user_id, session_id=session.id
        )

        # Query SKU Lineage API
        sku_res = self.client.get(f'/api/v2/ingestion/lineage/SKU-TRACE-99?userId={self.user_id}')
        self.assertEqual(sku_res.status_code, 200)
        sku_data = sku_res.json()

        self.assertEqual(sku_data["record_id"], "SKU-TRACE-99")
        self.assertEqual(sku_data["record_type"], "product")
        self.assertEqual(sku_data["import_id"], "IMP-20260922-001")
        self.assertEqual(sku_data["file"], "sales_q3_report.csv")
        self.assertEqual(sku_data["merchant"], self.user_id)
        self.assertIn("lineage", sku_data)
        self.assertIn("import_history", sku_data)

        # Query Order Lineage API
        order_res = self.client.get(f'/api/v2/ingestion/lineage/ORD-TRACE-99?userId={self.user_id}')
        self.assertEqual(order_res.status_code, 200)
        ord_data = order_res.json()

        self.assertEqual(ord_data["record_id"], "ORD-TRACE-99")
        self.assertEqual(ord_data["record_type"], "order")
        self.assertEqual(ord_data["import_id"], "IMP-20260922-001")
        self.assertEqual(ord_data["file"], "sales_q3_report.csv")
