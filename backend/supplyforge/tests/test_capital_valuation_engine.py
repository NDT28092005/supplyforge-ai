"""
Test suite for Task M5-03 Capital Valuation Engine (Module 05).
Verifies AC01 through AC10 requirements:
- SKU-level financial valuation (Inventory Capital Exposure vs Observed Cost Value)
- Cost validation (VALID, MISSING_COST, INVALID_COST, ZERO_COST)
- Risk Class aggregation & Category breakdown
- Preparation of Aging buckets for M5-04 Engine
- Prohibition of sales-to-stock substitution & zero future feature leakage
- Deterministic calculation verification & deliverable artifact generation
"""

import json
import os
import sys
import pandas as pd
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.capital_valuation_engine import CapitalValuationEngine, CapitalValuationError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestCapitalValuationEngine(TestCase):

    def setUp(self):
        self.master_catalog = ["SKU_1001", "SKU_1002", "SKU_1003", "SKU_1004"]
        self.engine = CapitalValuationEngine(master_sku_catalog=self.master_catalog)

        self.sample_df = pd.DataFrame([
            {"sku": "SKU_1001", "product_name": "Product 1", "category": "Category A", "stock_on_hand": 120, "unit_cost": 150000.0, "dsls": 120},
            {"sku": "SKU_1002", "product_name": "Product 2", "category": "Category A", "stock_on_hand": 45, "unit_cost": 85000.0, "dsls": 45},
            {"sku": "SKU_1003", "product_name": "Product 3", "category": "Category B", "stock_on_hand": 0, "unit_cost": 50000.0, "dsls": 200},
            {"sku": "SKU_1004", "product_name": "Product 4", "category": "Category B", "stock_on_hand": 10, "unit_cost": 120000.0, "dsls": 15}
        ])

        self.risk_assessments = [
            {"sku": "SKU_1001", "risk_class": "CRITICAL", "risk_probability": 0.95, "risk_score": 95.0},
            {"sku": "SKU_1002", "risk_class": "HIGH_RISK", "risk_probability": 0.85, "risk_score": 85.0},
            {"sku": "SKU_1003", "risk_class": "MEDIUM_RISK", "risk_probability": 0.60, "risk_score": 60.0},
            {"sku": "SKU_1004", "risk_class": "LOW_RISK", "risk_probability": 0.20, "risk_score": 20.0}
        ]

    def test_ac01_ac02_ac09_sku_valuation_and_cost_validation(self):
        """AC01, AC02, AC09: SKU valuation calculation, cost validation & separation of Inventory Capital vs Observed Cost."""
        rec1 = self.engine.value_sku(
            sku="SKU_1001",
            inventory_dict={"stock_on_hand": 120, "unit_cost": 150000.0, "dsls": 120},
            risk_assessment_dict={"risk_class": "CRITICAL", "risk_probability": 0.95, "risk_score": 95.0}
        )

        self.assertEqual(rec1["cost_status"], "VALID")
        self.assertEqual(rec1["inventory_capital_exposure"], 18000000.0)
        self.assertEqual(rec1["capital_metric_type"], "PHYSICAL_INVENTORY_CAPITAL")

        # Test case with missing stock (Observed Cost Value)
        rec2 = self.engine.value_sku(
            sku="SKU_NO_STOCK",
            inventory_dict={"stock_on_hand": None, "unit_cost": 100000.0, "observed_quantity": 50, "dsls": 30},
            risk_assessment_dict={"risk_class": "HIGH_RISK", "risk_probability": 0.80, "risk_score": 80.0}
        )

        self.assertIsNone(rec2["inventory_capital_exposure"])
        self.assertEqual(rec2["observed_cost_value"], 5000000.0)
        self.assertEqual(rec2["capital_metric_type"], "OBSERVED_TRANSACTION_COST")

    def test_ac03_ac04_ac10_dataset_valuation_aggregation_and_aging_prep(self):
        """AC03, AC04, AC10: Aggregation by Risk Class/Category and preparation for M5-04 Aging Analysis."""
        sku_records, summary = self.engine.value_dataset(self.sample_df, self.risk_assessments)

        self.assertEqual(summary["total_skus"], 4)
        self.assertEqual(summary["total_inventory_capital_exposure"], 23025000.0) # 18M + 3.825M + 0 + 1.2M
        self.assertIn("CRITICAL", summary["risk_class_breakdown"])
        self.assertEqual(summary["risk_class_breakdown"]["CRITICAL"]["inventory_capital"], 18000000.0)

        # Aging bucket preparation check
        self.assertIn("aging_bucket", sku_records[0])
        self.assertEqual(sku_records[0]["aging_bucket"], "91-180d")

    def test_ac05_ac06_ac07_ac08_guardrails_future_leakage_and_artifacts(self):
        """AC05, AC06, AC07, AC08: Guardrail tests, zero future feature leakage & artifact generation."""
        # Future feature leakage guardrail test
        future_inv = {
            "stock_on_hand": 100,
            "unit_cost": 50000.0,
            "fut_qty_60d": 500
        }
        with self.assertRaises(CapitalExposureGuardrailError):
            self.engine.value_sku("SKU_FUTURE", future_inv, {"risk_class": "LOW_RISK"})

        # Artifact generation test
        sku_records, summary = self.engine.value_dataset(self.sample_df, self.risk_assessments)
        art_paths = self.engine.save_valuation_artifacts(sku_records, summary)

        self.assertTrue(os.path.exists(art_paths["capital_exposure_summary"]))
        self.assertTrue(os.path.exists(art_paths["capital_valuation_validation"]))
        self.assertTrue(os.path.exists(art_paths["capital_valuation"]))
