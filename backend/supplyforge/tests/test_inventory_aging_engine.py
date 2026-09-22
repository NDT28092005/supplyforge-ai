"""
Test suite for Task M5-04 Inventory Aging Engine (Module 05).
Verifies AC01 through AC10 requirements:
- DSLS calculation at decision cutoff t0 & temporal integrity (t <= t0)
- Centralized configuration-driven Aging Bucket classification & severity
- Handling edge cases (unobserved sales -> NO_OBSERVED_SALE)
- Risk Class x Aging Bucket Matrix construction & aging priority (HIGH vs NORMAL)
- Association of aging with capital valuation metrics from M5-03
- Dataset aging statistics (mean, median, P75, P90, max DSLS) & deliverable artifact generation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.inventory_aging_engine import InventoryAgingEngine, InventoryAgingError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestInventoryAgingEngine(TestCase):

    def setUp(self):
        self.engine = InventoryAgingEngine()
        self.sample_valuation_records = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Category A",
                "unit_cost": 150000.0,
                "stock_on_hand": 120,
                "inventory_capital_exposure": 18000000.0,
                "observed_cost_value": 18000000.0,
                "risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "last_sale_date": "2026-01-15" # DSLS ~ 219d -> SEVERELY_STALE
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Category A",
                "unit_cost": 85000.0,
                "stock_on_hand": 45,
                "inventory_capital_exposure": 3825000.0,
                "observed_cost_value": 3825000.0,
                "risk_class": "HIGH_RISK",
                "risk_probability": 0.85,
                "last_sale_date": "2026-07-20" # DSLS ~ 33d -> AGING
            },
            {
                "sku": "SKU_1003",
                "canonical_sku_id": "CSKU_1003",
                "product_name": "Product 3",
                "category": "Category B",
                "unit_cost": 50000.0,
                "stock_on_hand": None,
                "inventory_capital_exposure": None,
                "observed_cost_value": 2500000.0,
                "risk_class": "MEDIUM_RISK",
                "risk_probability": 0.60,
                "last_sale_date": None # NO_OBSERVED_SALE
            }
        ]

    def test_ac01_ac03_ac04_ac05_dsls_and_bucket_classification(self):
        """AC01, AC03, AC04, AC05: DSLS calculation, bucket classification & unobserved sale handling."""
        rec1 = self.engine.analyze_sku_aging(
            valuation_record=self.sample_valuation_records[0],
            last_sale_date="2026-01-15",
            analysis_date="2026-08-22"
        )
        self.assertEqual(rec1["dsls"], 219)
        self.assertEqual(rec1["aging_bucket"], "SEVERELY_STALE")
        self.assertEqual(rec1["aging_priority"], "HIGH")

        # Edge case: No observed sale
        rec3 = self.engine.analyze_sku_aging(
            valuation_record=self.sample_valuation_records[2],
            last_sale_date=None,
            analysis_date="2026-08-22"
        )
        self.assertIsNone(rec3["dsls"])
        self.assertEqual(rec3["aging_bucket"], "NO_OBSERVED_SALE")
        self.assertEqual(rec3["aging_status"], "NO_OBSERVED_SALE")

    def test_ac02_temporal_integrity_guardrail(self):
        """AC02: Strict temporal integrity enforcement (t <= t0)."""
        future_record = self.sample_valuation_records[0]

        with self.assertRaises(CapitalExposureGuardrailError):
            self.engine.analyze_sku_aging(
                valuation_record=future_record,
                last_sale_date="2027-01-01",
                analysis_date="2026-08-22"
            )

    def test_ac06_ac07_ac08_ac09_ac10_matrix_statistics_and_artifacts(self):
        """AC06, AC07, AC08, AC09, AC10: Risk x Aging Matrix, aging statistics & artifact saving."""
        aging_records, matrix, summary = self.engine.analyze_dataset_aging(
            valuation_records=self.sample_valuation_records,
            analysis_date="2026-08-22"
        )

        self.assertEqual(summary["total_skus"], 3)
        self.assertEqual(summary["skus_with_valid_dsls"], 2)
        self.assertEqual(summary["unobserved_sale_skus"], 1)

        # Check Risk x Aging Matrix
        self.assertIn("CRITICAL", matrix)
        self.assertEqual(matrix["CRITICAL"]["SEVERELY_STALE"]["sku_count"], 1)

        # Check Aging Statistics
        stats = summary["dsls_statistics"]
        self.assertIsNotNone(stats["mean_dsls"])

        # Save artifacts
        art_paths = self.engine.save_aging_artifacts(aging_records, matrix, summary)
        self.assertTrue(os.path.exists(art_paths["aging_distribution"]))
        self.assertTrue(os.path.exists(art_paths["risk_aging_matrix"]))
        self.assertTrue(os.path.exists(art_paths["capital_aging_summary"]))
        self.assertTrue(os.path.exists(art_paths["inventory_aging_validation"]))
        self.assertTrue(os.path.exists(art_paths["inventory_aging"]))
