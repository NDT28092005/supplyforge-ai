import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace
from src.ingestion.sku_normalizer import SkuNormalizer


class SkuNormalizerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — DAT-06 SKU Normalization."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Normalization WS", slug="test-ws-norm")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_variants.csv",
            status="PROFILED",
            column_mapping_json={
                "mappings": [
                    {"source_column": "sku_code", "canonical_field": "sku"},
                    {"source_column": "p_name", "canonical_field": "product_name"},
                    {"source_column": "qty", "canonical_field": "quantity"},
                ]
            }
        )

    def test_sku_normalization_success(self):
        """Test SKU normalization pipeline and canonical identity resolution."""
        df = pd.DataFrame({
            "sku_code": ["SKU_101", "SKU_101_ALT", "SKU_102_400G", "SKU_102_900G"],
            "p_name": [
                "Bình Sữa 250ml Avent",
                "binh sua 250 ml avent",  # should match SKU_101
                "Sữa Bột Abbott 400g",
                "Sữa Bột Abbott 900g",    # distinct variant 400g vs 900g
            ],
            "qty": [10, 5, 20, 15],
        })

        normalizer = SkuNormalizer(session_id=str(self.session.id))
        summary = normalizer.normalize_dataset(df, self.session.column_mapping_json)

        self.assertEqual(summary["totalOriginalSkus"], 4)
        self.assertLess(summary["totalCanonicalSkus"], 4)  # 2 variants merged
        self.assertGreaterEqual(summary["autoMergedCount"], 1)

    def test_export_artifacts(self):
        """Test exporter creates 5 standard artifacts in reports/."""
        df = pd.DataFrame({
            "sku_code": ["SKU_201"],
            "p_name": ["Tã Quần L 54"],
            "qty": [12],
        })

        normalizer = SkuNormalizer(session_id=str(self.session.id))
        summary = normalizer.normalize_dataset(df, self.session.column_mapping_json)

        reports_dir = os.path.join(PROJECT_ROOT, "reports")
        artifacts = normalizer.export_artifacts(summary, output_dir=reports_dir)

        self.assertTrue(os.path.exists(artifacts["normalized_dataset_csv"]))
        self.assertTrue(os.path.exists(artifacts["sku_master"]))
        self.assertTrue(os.path.exists(artifacts["sku_mapping"]))
        self.assertTrue(os.path.exists(artifacts["sku_match_candidates"]))
        self.assertTrue(os.path.exists(artifacts["sku_merge_audit_log"]))
