"""
Test suite for Task M5-07 Capital Exposure Aggregation (Module 05).
Verifies AC-01 through AC-10 requirements:
- Aggregation of total inventory value & risk-weighted exposure
- Multi-dimensional portfolio breakdowns (Risk Level, Aging Risk Level, Priority P1-P4)
- 2D Cross-dimensional Risk Class x Aging Risk Level matrix construction
- Exposure share calculation & Top-N concentration KPIs
- Strict mathematical reconciliation checks (SUM(groups) == Total)
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

from src.analytics.capital_exposure_aggregator import CapitalExposureAggregator, CapitalExposureAggregationError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestCapitalExposureAggregation(TestCase):

    def setUp(self):
        self.aggregator = CapitalExposureAggregator()

        self.sample_assessments = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Mother & Baby",
                "inventory_age_days": 210,
                "aging_bucket": "SEVERELY_STALE",
                "aging_risk_level": "CRITICAL_AGING",
                "inventory_value": 20000000.0,
                "capital_exposure": 20000000.0,
                "risk_weighted_exposure": 20000000.0,
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "aging_priority": "P1",
                "aging_flags": ["LONG_AGED_INVENTORY", "CRITICAL_AGING"]
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Mother & Baby",
                "inventory_age_days": 45,
                "aging_bucket": "AGING",
                "aging_risk_level": "AGING",
                "inventory_value": 12000000.0,
                "capital_exposure": 12000000.0,
                "risk_weighted_exposure": 9000000.0,
                "slow_moving_risk_class": "HIGH_RISK",
                "risk_probability": 0.80,
                "aging_priority": "P2",
                "aging_flags": []
            },
            {
                "sku": "SKU_1003",
                "canonical_sku_id": "CSKU_1003",
                "product_name": "Product 3",
                "category": "Toys",
                "inventory_age_days": 15,
                "aging_bucket": "RECENT",
                "aging_risk_level": "FRESH",
                "inventory_value": 5000000.0,
                "capital_exposure": 5000000.0,
                "risk_weighted_exposure": 500000.0,
                "slow_moving_risk_class": "LOW_RISK",
                "risk_probability": 0.10,
                "aging_priority": "P4",
                "aging_flags": []
            }
        ]

    def test_ac01_ac02_ac03_ac04_ac08_totals_and_breakdowns(self):
        """AC-01, AC-02, AC-03, AC-04, AC-08: Aggregates total values and multi-dimensional distributions."""
        summary_payload = self.aggregator.aggregate_portfolio(self.sample_assessments)

        summ = summary_payload["summary"]
        self.assertEqual(summ["sku_count"], 3)
        self.assertEqual(summ["total_inventory_value"], 37000000.0) # 20M + 12M + 5M
        self.assertEqual(summ["total_risk_weighted_exposure"], 29500000.0) # 20M + 9M + 0.5M

        # Risk distribution check
        risk_dist = summary_payload["risk_distribution"]
        self.assertEqual(len(risk_dist), 4)
        self.assertEqual(risk_dist[0]["group"], "CRITICAL")
        self.assertEqual(risk_dist[0]["risk_weighted_exposure"], 20000000.0)

        # Aging distribution check
        aging_dist = summary_payload["aging_distribution"]
        self.assertEqual(len(aging_dist), 4)

        # Priority distribution check
        prio_dist = summary_payload["priority_distribution"]
        self.assertEqual(len(prio_dist), 4)
        self.assertEqual(prio_dist[0]["group"], "P1")
        self.assertEqual(prio_dist[0]["sku_count"], 1)

    def test_ac05_ac06_ac07_matrix_concentration_and_shares(self):
        """AC-05, AC-06, AC-07: 2D Matrix, exposure shares, Top-N SKUs and concentration KPIs."""
        summary_payload = self.aggregator.aggregate_portfolio(self.sample_assessments)

        # 2D Matrix check (4x4 = 16 cells)
        matrix = summary_payload["risk_aging_matrix"]
        self.assertEqual(len(matrix), 16)

        cell_crit_crit = next(c for c in matrix if c["slow_moving_risk"] == "CRITICAL" and c["aging_risk"] == "CRITICAL_AGING")
        self.assertEqual(cell_crit_crit["sku_count"], 1)
        self.assertEqual(cell_crit_crit["risk_weighted_exposure"], 20000000.0)

        # Concentration KPIs
        conc = summary_payload["exposure_concentration"]
        self.assertEqual(conc["top_10_exposure"], 29500000.0)
        self.assertEqual(conc["top_10_exposure_share"], 1.0)

        # Top SKUs check
        top_skus = summary_payload["top_exposure_skus"]
        self.assertEqual(top_skus[0]["sku"], "SKU_1001")
        self.assertEqual(top_skus[0]["risk_weighted_exposure"], 20000000.0)

    def test_ac09_ac10_reconciliation_and_artifacts(self):
        """AC-09, AC-10: Mathematical reconciliation verification & artifact saving."""
        summary_payload = self.aggregator.aggregate_portfolio(self.sample_assessments)

        # Reconciliation check
        rec_status = summary_payload["reconciliation_status"]
        self.assertTrue(rec_status["all_reconciled"])
        self.assertTrue(rec_status["risk_reconciled"])
        self.assertTrue(rec_status["aging_reconciled"])
        self.assertTrue(rec_status["priority_reconciled"])

        # Artifact generation check
        art_paths = self.aggregator.save_aggregation_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["capital_exposure_summary"]))
        self.assertTrue(os.path.exists(art_paths["capital_exposure_by_risk"]))
        self.assertTrue(os.path.exists(art_paths["capital_exposure_by_aging"]))
        self.assertTrue(os.path.exists(art_paths["risk_aging_exposure_matrix"]))
        self.assertTrue(os.path.exists(art_paths["top_exposure_skus"]))
        self.assertTrue(os.path.exists(art_paths["capital_exposure_aggregation_validation"]))
