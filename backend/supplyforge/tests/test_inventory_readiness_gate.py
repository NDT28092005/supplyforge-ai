"""
Test suite for Task M5-02 Inventory Data Readiness (Module 05).
Verifies AC-01 through AC-14 requirements:
- Dataset & field availability detection
- Stock & Cost completeness validation
- Invalid stock (< 0) & cost (<= 0) value detection
- SKU Catalog Mapping validation (MATCHED / UNMATCHED)
- Inventory Freshness validation (FRESH, AGING, STALE, OUTDATED)
- Valuation Readiness determination & downstream calculation protection (BLOCKING invalid SKUs)
- Prohibition of inferring stock from sales history
- Preservation of Risk Detection independent of inventory readiness
- Generation of auditable SKU readiness reasons & deliverable reports
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

from src.analytics.inventory_readiness_gate import InventoryReadinessGate, InventoryReadinessError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestInventoryReadinessGate(TestCase):

    def setUp(self):
        self.master_catalog = [f"SKU_{1000+i}" for i in range(20)]
        self.gate = InventoryReadinessGate(master_sku_catalog=self.master_catalog)

        self.sample_df = pd.DataFrame([
            {"sku": "SKU_1001", "stock_on_hand": 120, "unit_cost": 150000.0, "inventory_date": "2026-08-20"},
            {"sku": "SKU_1002", "stock_on_hand": 45, "unit_cost": 85000.0, "inventory_date": "2026-08-20"},
            {"sku": "SKU_1003", "stock_on_hand": 0, "unit_cost": 50000.0, "inventory_date": "2026-08-20"},
            {"sku": "SKU_1004", "stock_on_hand": 10, "unit_cost": 120000.0, "inventory_date": "2026-08-20"}
        ])

    def test_ac01_ac02_ac03_ac04_dataset_field_validation_and_completeness(self):
        """AC-01, AC-02, AC-03, AC-04: Dataset detection, required field check & completeness calculation."""
        report = self.gate.evaluate_dataset_readiness(self.sample_df)

        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["total_skus"], 4)
        self.assertEqual(report["stock_completeness"], 1.0)
        self.assertEqual(report["cost_completeness"], 1.0)
        self.assertEqual(report["eligible_skus"], 4)
        self.assertEqual(report["excluded_skus"], 0)

    def test_ac05_ac06_ac07_invalid_values_mapping_and_freshness(self):
        """AC-05, AC-06, AC-07: Detect invalid stock/cost, check SKU mapping and freshness."""
        invalid_df = pd.DataFrame([
            {"sku": "SKU_1001", "stock_on_hand": -10, "unit_cost": 150000.0, "inventory_date": "2026-08-20"},
            {"sku": "SKU_1002", "stock_on_hand": 50, "unit_cost": 0.0, "inventory_date": "2026-08-20"},
            {"sku": "SKU_UNKNOWN", "stock_on_hand": 20, "unit_cost": 10000.0, "inventory_date": "2025-01-01"}
        ])

        report = self.gate.evaluate_dataset_readiness(invalid_df)

        self.assertEqual(report["status"], "NOT_READY")
        self.assertEqual(report["eligible_skus"], 0)
        self.assertEqual(report["excluded_skus"], 3)

        # SKU-level auditable reasons check
        sku_details = report["sku_readiness_details"]
        self.assertIn("Invalid negative stock_on_hand: -10.0", sku_details[0]["reasons"])
        self.assertIn("Invalid non-positive unit_cost: 0.0", sku_details[1]["reasons"])
        self.assertEqual(sku_details[2]["sku_mapping_status"], "UNMATCHED")
        self.assertEqual(sku_details[2]["freshness_status"], "OUTDATED")

    def test_ac08_ac09_ac10_ac11_readiness_states_and_downstream_blocking(self):
        """AC-08, AC-09, AC-10, AC-11: Dataset/SKU-level readiness states and blocking ineligible SKUs."""
        # 10 SKUs, 9 eligible, 1 missing stock -> 90% stock completeness -> READY_WITH_WARNING
        rows = [
            {"sku": f"SKU_{1000+i}", "stock_on_hand": 10 * (i + 1), "unit_cost": 50000.0, "inventory_date": "2026-08-20"}
            for i in range(9)
        ]
        rows.append({"sku": "SKU_1009", "stock_on_hand": None, "unit_cost": 50000.0, "inventory_date": "2026-08-20"})
        warning_df = pd.DataFrame(rows)

        report = self.gate.evaluate_dataset_readiness(warning_df)
        self.assertEqual(report["status"], "READY_WITH_WARNING")
        self.assertEqual(report["eligible_skus"], 9)
        self.assertEqual(report["excluded_skus"], 1)

        sku9_status = report["sku_readiness_details"][9]
        self.assertFalse(sku9_status["valuation_ready"])
        self.assertEqual(sku9_status["capital_exposure_status"], "NOT_AVAILABLE")

    def test_ac12_ac13_ac14_no_sales_substitution_and_risk_preservation(self):
        """AC-12, AC-13, AC-14: Prohibition of sales substitution, preservation of Risk Detection & auditable reasons."""
        # AC-12 Guardrail test
        invalid_inventory = {
            "sku": "SKU_NO_STOCK",
            "stock_on_hand": None,
            "past_total_sold": 300,
            "inferred_stock_from_sales": True
        }
        with self.assertRaises(CapitalExposureGuardrailError):
            self.gate.evaluate_sku_readiness("SKU_NO_STOCK", invalid_inventory)

        # AC-13 Risk preservation check
        res = self.gate.evaluate_sku_readiness(
            sku="SKU_1001",
            inventory_dict={"stock_on_hand": None, "unit_cost": None},
            risk_class="CRITICAL"
        )
        self.assertEqual(res["risk_class"], "CRITICAL")
        self.assertEqual(res["capital_exposure_status"], "NOT_AVAILABLE")
        self.assertIn("stock_on_hand is missing", res["reasons"])

    def test_save_readiness_artifacts(self):
        """Test artifact saving in reports/capital/ directory."""
        report = self.gate.evaluate_dataset_readiness(self.sample_df)
        art_paths = self.gate.save_readiness_artifacts(report)

        self.assertTrue(os.path.exists(art_paths["inventory_readiness"]))
        self.assertTrue(os.path.exists(art_paths["inventory_field_quality"]))
        self.assertTrue(os.path.exists(art_paths["inventory_mapping_status"]))
        self.assertTrue(os.path.exists(art_paths["inventory_freshness"]))
        self.assertTrue(os.path.exists(art_paths["inventory_readiness_by_sku"]))
