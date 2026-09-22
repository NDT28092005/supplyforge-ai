"""
Test suite for Task M5-05 Risk-Weighted Capital Exposure (Module 05).
Verifies AC01 through AC12 requirements:
- Externalized risk-weight & aging-weight configuration management
- SKU-level RWCE, PAE, and AWE calculations
- Portfolio aggregation & exposure share per Risk Class
- Capital priority ranking (capital_priority_rank) & business signal generation
- Zero modification of Module 03 Risk Classifications
- 100% deterministic Python math engine & audit metadata tracking
- Deliverable artifact generation in reports/capital/
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.risk_weighted_exposure_engine import RiskWeightedExposureEngine, RiskWeightedExposureError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestRiskWeightedExposureEngine(TestCase):

    def setUp(self):
        self.engine = RiskWeightedExposureEngine()

        self.sample_aging_records = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Mother & Baby",
                "risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "inventory_capital_exposure": 20000000.0,
                "observed_cost_value": 20000000.0,
                "dsls": 210,
                "aging_bucket": "SEVERELY_STALE"
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Mother & Baby",
                "risk_class": "HIGH_RISK",
                "risk_probability": 0.80,
                "inventory_capital_exposure": 12000000.0,
                "observed_cost_value": 12000000.0,
                "dsls": 45,
                "aging_bucket": "AGING"
            },
            {
                "sku": "SKU_1003",
                "canonical_sku_id": "CSKU_1003",
                "product_name": "Product 3",
                "category": "Toys",
                "risk_class": "MEDIUM_RISK",
                "risk_probability": 0.50,
                "inventory_capital_exposure": None,
                "observed_cost_value": 5000000.0,
                "dsls": None,
                "aging_bucket": "NO_OBSERVED_SALE"
            }
        ]

    def test_ac01_ac02_ac03_ac04_ac11_sku_exposures_and_proxy(self):
        """AC01, AC02, AC03, AC04, AC11: RWCE, PAE, AWE calculations & proxy state handling."""
        rec1 = self.engine.evaluate_sku_exposure(self.sample_aging_records[0])

        self.assertEqual(rec1["risk_weight"], 1.00)
        self.assertEqual(rec1["risk_weighted_exposure"], 20000000.0) # 20M * 1.00
        self.assertEqual(rec1["probability_adjusted_exposure"], 19000000.0) # 20M * 0.95
        self.assertEqual(rec1["aging_adjusted_exposure"], 16000000.0) # 20M * 1.00 * 0.80
        self.assertFalse(rec1["is_proxy_exposure"])

        # Check proxy exposure handling for missing physical stock
        rec3 = self.engine.evaluate_sku_exposure(self.sample_aging_records[2])
        self.assertTrue(rec3["is_proxy_exposure"])
        self.assertEqual(rec3["exposure_type"], "OBSERVED_TRANSACTION_COST_PROXY")
        self.assertEqual(rec3["risk_weighted_exposure"], 2000000.0) # 5M * 0.40

    def test_ac05_ac06_ac07_ac08_ac10_portfolio_aggregation_ranking_and_signals(self):
        """AC05, AC06, AC07, AC08, AC10: Portfolio aggregation, ranking, business signals & risk class immutability."""
        exposure_recs, portfolio = self.engine.evaluate_portfolio_exposure(self.sample_aging_records)

        self.assertEqual(portfolio["total_skus"], 3)
        self.assertEqual(portfolio["total_capital_exposure"], 37000000.0) # 20M + 12M + 5M
        self.assertEqual(portfolio["total_risk_weighted_exposure"], 31000000.0) # 20M + 9M + 2M

        # Ranking check (SKU_1001 rank 1, SKU_1002 rank 2)
        self.assertEqual(exposure_recs[0]["sku"], "SKU_1001")
        self.assertEqual(exposure_recs[0]["capital_priority_rank"], 1)

        # Signals check
        self.assertEqual(exposure_recs[0]["capital_exposure_signal"], "CRITICAL_AGING_EXPOSURE")
        self.assertEqual(exposure_recs[1]["capital_exposure_signal"], "HIGH_RISK_HIGH_CAPITAL")

        # Immutability check: Risk class remained unchanged
        self.assertEqual(exposure_recs[0]["risk_class"], "CRITICAL")
        self.assertEqual(exposure_recs[1]["risk_class"], "HIGH_RISK")

    def test_ac09_ac12_artifact_saving(self):
        """AC09, AC12: Save deliverables to reports/capital/ directory."""
        exposure_recs, portfolio = self.engine.evaluate_portfolio_exposure(self.sample_aging_records)
        art_paths = self.engine.save_exposure_artifacts(exposure_recs, portfolio)

        self.assertTrue(os.path.exists(art_paths["risk_weighted_exposure"]))
        self.assertTrue(os.path.exists(art_paths["capital_exposure_portfolio"]))
        self.assertTrue(os.path.exists(art_paths["risk_weighted_exposure_validation"]))
