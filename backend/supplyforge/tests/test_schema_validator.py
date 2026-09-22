import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.schema_validator import SchemaValidator


class SchemaValidatorTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — Task 04 Canonical Schema Validation."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Validation WS", slug="test-ws-val")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="test_sales_transactions.csv",
            status="MAPPING",
            column_mapping_json={
                "mappings": [
                    {"source_column": "sku_code", "canonical_field": "sku"},
                    {"source_column": "trans_date", "canonical_field": "date"},
                    {"source_column": "qty", "canonical_field": "quantity"},
                ]
            }
        )

    def test_schema_validation_valid(self):
        """Test schema validation on valid transaction dataset."""
        df = pd.DataFrame({
            "sku_code": ["SKU_101", "SKU_102"],
            "trans_date": ["2025-01-01", "2025-01-20"],
            "qty": [10, 0],
        })

        validator = SchemaValidator(session_id=str(self.session.id))
        report = validator.validate_schema(df, self.session.column_mapping_json)

        self.assertTrue(report["slow_moving_detection_ready"])
        self.assertIn(report["status"], ["VALID", "VALID_WITH_WARNINGS"])
        self.assertTrue(report["quantityValidation"]["zeroSalesIsValid"])

    def test_schema_validation_invalid_missing_sku(self):
        """Test schema validation INVALID status when required field is missing."""
        df = pd.DataFrame({
            "trans_date": ["2025-01-01"],
            "qty": [10],
        })
        invalid_mapping = {
            "mappings": [
                {"source_column": "trans_date", "canonical_field": "date"},
                {"source_column": "qty", "canonical_field": "quantity"},
            ]
        }

        validator = SchemaValidator(session_id=str(self.session.id))
        report = validator.validate_schema(df, invalid_mapping)

        self.assertEqual(report["status"], "INVALID")
        self.assertFalse(report["slow_moving_detection_ready"])
        self.assertIn('Required canonical field "sku" is missing.', report["schema_errors"])
