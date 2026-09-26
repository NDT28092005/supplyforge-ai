import io
from django.test import TestCase
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.models import Product, Order


class InitialImportTestCase(TestCase):
    """Test suite verifying IR-003 Initial Import requirements and acceptance criteria."""

    def test_initial_import_success_metrics(self):
        """Verify initial import returns DATA_READY status and exact metric fields."""
        csv_content = (
            "order_id,sku,product_name,selling_price,quantity,order_date,extra_col_1,extra_col_2,extra_col_3,extra_col_4\n"
            "ORD-101,SKU-001,Sản phẩm 1,150000,10,2025-05-14,a,b,c,d\n"
            "ORD-102,SKU-002,Sản phẩm 2,200000,5,2025-05-15,a,b,c,d\n"
            "ORD-101,SKU-001,Sản phẩm 1,150000,10,2025-05-14,a,b,c,d\n"  # Duplicate row
        )
        f = io.BytesIO(csv_content.encode('utf-8'))
        
        result = DynamicFileImportService.process_batch_import(f, {}, 'user_test_001', session_type='INITIAL', force_reset=True)

        self.assertEqual(result["status"], "DATA_READY")
        self.assertEqual(result["rows_received"], 3)
        self.assertEqual(result["rows_valid"], 2)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(result["rows_rejected"], 0)
        self.assertGreaterEqual(result["warnings"], 1)

    def test_initial_import_database_persistence(self):
        """Verify products and orders are saved to DB."""
        csv_content = (
            "order_id,sku,product_name,selling_price,quantity,order_date\n"
            "ORD-201,SKU-100,Áo Thun Nam,199000,5,2025-05-14\n"
        )
        f = io.BytesIO(csv_content.encode('utf-8'))
        DynamicFileImportService.process_batch_import(f, {}, 'user_test_002', session_type='INITIAL', force_reset=True)

        products = Product.objects.filter(user_id='user_test_002')
        orders = Order.objects.filter(user_id='user_test_002')

        self.assertEqual(products.count(), 1)
        self.assertEqual(products.first().item_sku, "SKU-100")
        self.assertEqual(orders.count(), 1)
