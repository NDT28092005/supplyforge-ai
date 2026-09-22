import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models import IngestionSession, Workspace
from src.ingestion.column_mapper import ColumnMapper


class ColumnMapperTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — Task 03 Column Mapping."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Mapping WS", slug="test-ws-mapping")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_vietnam_sample.csv",
            status="PROFILED",
            headers_json=["Mã SKU", "Tên SP", "SLBH", "Giá bán", "Giá vốn", "Ngày đặt"],
            preview_rows_json=[["SKU001", "Bình sữa 250ml", "10", "180000", "120000", "2025-05-14"]],
        )

    def test_auto_column_mapping(self):
        """Test automatic 3-level mapping on Vietnamese column headers."""
        headers = self.session.headers_json
        sample_rows = self.session.preview_rows_json

        mapper = ColumnMapper(session_id=str(self.session.id))
        result = mapper.map_columns(headers, sample_rows)

        self.assertTrue(result['requiredFieldsCheck']['allPassed'])
        self.assertIn(result['mappingStatus'], ['AUTO_ACCEPTED', 'NEEDS_REVIEW'])

        # Verify canonical fields
        mapped_dict = {m['source_column']: m['canonical_field'] for m in result['mappings']}
        self.assertEqual(mapped_dict['Mã SKU'], 'sku')
        self.assertEqual(mapped_dict['SLBH'], 'quantity')
        self.assertEqual(mapped_dict['Ngày đặt'], 'date')

    def test_blocked_status_when_missing_required(self):
        """Test BLOCKED mapping status when required fields are missing."""
        headers = ["Tên SP", "Giá bán", "Giá vốn"]  # Missing SKU, Date, Quantity
        mapper = ColumnMapper(session_id=str(self.session.id))
        result = mapper.map_columns(headers)

        self.assertEqual(result['mappingStatus'], 'BLOCKED')
        self.assertIsNotNone(result['blockingReason'])
        self.assertFalse(result['requiredFieldsCheck']['allPassed'])
