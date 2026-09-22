import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.data_quality_validator import DataQualityValidator


class DataQualityValidatorTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-05 Data Quality Validation."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Quality WS", slug="test-ws-qual")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_daily_sales.csv",
            status="MAPPING",
            column_mapping_json={
                "mappings": [
                    {"source_column": "sku_code", "canonical_field": "sku"},
                    {"source_column": "trans_date", "canonical_field": "date"},
                    {"source_column": "quantity_sold", "canonical_field": "quantity"},
                ]
            }
        )

    def test_data_quality_validation_success(self):
        """Test deterministic data quality score calculation and zero-sales preservation."""
        df = pd.DataFrame({
            "sku_code": ["SKU_1001", "SKU_1001", "SKU_1002"],
            "trans_date": ["2025-01-01", "2025-01-08", "2025-01-15"],
            "quantity_sold": [10, 0, 5],  # includes zero-sales
        })

        validator = DataQualityValidator(session_id=str(self.session.id))
        report = validator.validate_quality(df, self.session.column_mapping_json)

        self.assertGreaterEqual(report["datasetQualityScore"], 80.0)
        self.assertIn(report["qualityStatus"], ["EXCELLENT", "GOOD"])
        self.assertTrue(report["slowMovingDetectionReady"])
        self.assertTrue(report["invalidValues"]["details"]["quantity"]["zeroSalesIsValid"])
        self.assertEqual(report["invalidValues"]["details"]["quantity"]["zeroSalesCount"], 1)

    def test_export_reports(self):
        """Test report exporter outputs json and parquet/csv files in reports/."""
        df = pd.DataFrame({
            "sku_code": ["SKU_1001"],
            "trans_date": ["2025-01-01"],
            "quantity_sold": [15],
        })

        validator = DataQualityValidator(session_id=str(self.session.id))
        report = validator.validate_quality(df, self.session.column_mapping_json)

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        generated_files = validator.export_reports(report, output_dir=reports_dir)

        self.assertTrue(os.path.exists(generated_files["data_quality_report"]))
        self.assertTrue(os.path.exists(generated_files["data_quality_summary"]))
        self.assertTrue(os.path.exists(generated_files["sku_quality_profile_csv"]))
