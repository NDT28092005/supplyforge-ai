import io
import uuid
from unittest.mock import patch
from django.test import TestCase, Client
from supplyforge.models import IngestionSession, Product, Order, Workspace
from supplyforge.services.ingestion import DynamicFileImportService


class ImportCancellationAndRecoveryTestCase(TestCase):
    """
    Test suite verifying:
    - IR-014 Import Cancellation: stop processing, release resources, mark job CANCELLED, zero half-valid rows.
    - IR-015 Failed Import Recovery: atomic staging/transaction rollback ensures CANONICAL dataset remains unchanged on error.
    """

    def setUp(self):
        self.client = Client()
        self.user_id = 'test_user_ir014_ir015'
        self.workspace, _ = Workspace.objects.get_or_create(id=1, defaults={'name': 'Test Workspace'})

    def test_ir014_import_cancellation(self):
        """Test IR-014: Cancel import endpoint stops processing, marks job CANCELLED, and reports 0 progress."""
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            status='PROCESSING',
            original_filename='large_mistake_file.csv',
            total_rows=500000
        )

        response = self.client.post(f'/api/v2/ingestion/sessions/{session.id}/cancel')
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data['status'], 'CANCELLED')

        # Verify DB state
        session.refresh_from_db()
        self.assertEqual(session.status, 'CANCELLED')

        # Verify progress endpoint returns CANCELLED
        progress_res = self.client.get(f'/api/v2/ingestion/sessions/{session.id}/progress')
        self.assertEqual(progress_res.status_code, 200)
        p_data = progress_res.json()
        self.assertEqual(p_data['status'], 'CANCELLED')
        self.assertEqual(p_data['overallProgress'], 0)

        # Verify canonical DB has no partial records
        self.assertEqual(Product.objects.filter(user_id=self.user_id).count(), 0)
        self.assertEqual(Order.objects.filter(user_id=self.user_id).count(), 0)

    def test_ir015_failed_import_recovery_transaction_rollback(self):
        """Test IR-015: Failed batch processing rolls back transaction completely, keeping CANONICAL data unchanged."""
        # Initial canonical data (1 product, 1 order)
        initial_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-INIT-01,SKU-CANONICAL-1,Initial Product,150000,2,2026-01-01\n"
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(initial_csv.encode('utf-8')), {}, self.user_id, session_type='INITIAL', force_reset=True
        )

        initial_prod_count = Product.objects.filter(user_id=self.user_id).count()
        initial_order_count = Order.objects.filter(user_id=self.user_id).count()
        self.assertEqual(initial_prod_count, 1)
        self.assertEqual(initial_order_count, 1)

        # Attempt to import batch that raises an unexpected DB / process error midway
        failing_csv = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-FAIL-01,SKU-FAIL-1,Fail Product 1,200000,1,2026-02-01\n"
            "ORD-FAIL-02,SKU-FAIL-2,Fail Product 2,300000,3,2026-02-02\n"
        )

        with patch('supplyforge.models.Order.objects.bulk_create', side_effect=RuntimeError("Simulated Database Failure midway")):
            with self.assertRaises(RuntimeError):
                DynamicFileImportService.process_batch_import(
                    io.BytesIO(failing_csv.encode('utf-8')), {}, self.user_id, session_type='INCREMENTAL', force_reset=False
                )

        # Verify canonical DB data was unchanged (STAGING discarded via @transaction.atomic rollback)
        self.assertEqual(Product.objects.filter(user_id=self.user_id).count(), initial_prod_count)
        self.assertEqual(Order.objects.filter(user_id=self.user_id).count(), initial_order_count)
        self.assertFalse(Product.objects.filter(user_id=self.user_id, item_sku='SKU-FAIL-1').exists())
        self.assertFalse(Product.objects.filter(user_id=self.user_id, item_sku='SKU-FAIL-2').exists())
