import io
import os
import tempfile
from django.test import TestCase
from supplyforge.services.csv_validator import CSVFormatValidator, ValidationStatus


class CSVFormatValidatorTestCase(TestCase):
    """Test suite verifying IR-001 CSV File Format Validation requirements."""

    def test_valid_csv(self):
        """CSV hợp lệ -> VALIDATED"""
        content = "sku,product_name,selling_price,quantity,order_date\nSKU001,Sản phẩm A,150000,10,2025-05-14\nSKU002,Sản phẩm B,200000,5,2025-05-15\n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        
        self.assertEqual(result.status, ValidationStatus.VALIDATED)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.headers, ["sku", "product_name", "selling_price", "quantity", "order_date"])
        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.valid_rows_count, 2)

    def test_empty_file(self):
        """File rỗng -> Reject"""
        f = io.BytesIO(b"")
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.REJECT)
        self.assertIn("File rỗng", result.errors[0])

    def test_missing_header(self):
        """Không có header -> Reject"""
        content = " ,  ,  \n ,  ,  \n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.REJECT)
        self.assertIn("Không có header hợp lệ", result.errors[0])

    def test_duplicate_column(self):
        """Duplicate column -> Reject"""
        content = "sku,quantity,sku\nSKU001,10,SKU001\n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.REJECT)
        self.assertIn("cột trùng lặp", result.errors[0])

    def test_missing_required_column(self):
        """Thiếu required column -> Reject"""
        content = "unknown_col1,unknown_col2\nVal1,Val2\n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.REJECT)
        self.assertIn("Thiếu required column", result.errors[0])

    def test_non_csv_binary_file(self):
        """File không phải CSV (binary) -> Reject"""
        binary_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00"
        f = io.BytesIO(binary_content)
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.REJECT)
        self.assertIn("dữ liệu nhị phân", result.errors[0])

    def test_extra_columns(self):
        """Có extra column -> Warning"""
        content = "sku,product_name,quantity,custom_param_1,custom_param_2,custom_param_3,custom_param_4\nSKU001,Item A,10,a,b,c,d\n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        self.assertEqual(result.status, ValidationStatus.WARNING)
        self.assertTrue(any("extra columns" in w for w in result.warnings))

    def test_corrupted_rows_not_silently_ignored(self):
        """Một số row malformed -> Không bị silently bỏ qua, ghi nhận vào corruptedRows"""
        content = "sku,product_name,quantity\nSKU001,Item A,10\nSKU002,Item B\nSKU003,Item C,30,ExtraVal\n"
        f = io.BytesIO(content.encode('utf-8'))
        result = CSVFormatValidator.validate_file(f)
        
        self.assertEqual(result.status, ValidationStatus.WARNING)
        self.assertEqual(len(result.corrupted_rows), 2)
        # Verify line numbers 3 and 4 were flagged
        corrupted_lines = [cr['line_number'] for cr in result.corrupted_rows]
        self.assertIn(3, corrupted_lines)
        self.assertIn(4, corrupted_lines)
        self.assertEqual(result.valid_rows_count, 1)
