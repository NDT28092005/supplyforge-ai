"""
Test suite for Task M5-08 Financial Impact Analysis (Module 05).
Verifies AC-01 through AC-12 requirements:
- Calculation of total capital locked & risk-weighted exposure integration
- Opportunity cost calculation (CE * AnnualRate * AgingDays / 365.0)
- Multi-dimensional financial impact aggregations (Risk Class, Aging Bucket)
- 2D Risk Class x Aging Risk Level financial matrix construction
- SKU-level financial priority assignment (P1, P2, P3, P4)
- Concentration KPIs (Top-10 Capital Exposure & Top-10 Opportunity Cost Share)
- Financial reconciliation verification & deliverable artifact generation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.financial_impact_engine import FinancialImpactEngine, FinancialImpactError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestFinancialImpactEngine(TestCase):

    def setUp(self):
        self.engine = FinancialImpactEngine(default_opportunity_rate=0.12)

        self.sample_assessments = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Mother & Baby",
                "capital_exposure": 20000000.0,
                "inventory_value": 20000000.0,
                "risk_weighted_exposure": 20000000.0,
                "inventory_age_days": 210,
                "aging_risk_level": "CRITICAL_AGING",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "aging_priority": "P1"
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Mother & Baby",
                "capital_exposure": 12000000.0,
                "inventory_value": 12000000.0,
                "risk_weighted_exposure": 9000000.0,
                "inventory_age_days": 45,
                "aging_risk_level": "AGING",
                "slow_moving_risk_class": "HIGH_RISK",
                "risk_probability": 0.80,
                "aging_priority": "P2"
            },
            {
                "sku": "SKU_1003",
                "canonical_sku_id": "CSKU_1003",
                "product_name": "Product 3",
                "category": "Toys",
                "capital_exposure": 2000000.0,
                "inventory_value": 2000000.0,
                "risk_weighted_exposure": 200000.0,
                "inventory_age_days": 15,
                "aging_risk_level": "FRESH",
                "slow_moving_risk_class": "LOW_RISK",
                "risk_probability": 0.10,
                "aging_priority": "P4"
            }
        ]

    def test_ac01_ac02_ac03_ac07_opportunity_cost_and_sku_financial_impact(self):
        """AC-01, AC-02, AC-03, AC-07: Opportunity cost calculation & SKU-level financial priority."""
        rec1 = self.engine.evaluate_sku_financial_impact(self.sample_assessments[0])

        self.assertEqual(rec1["capital_locked"], 20000000.0)
        self.assertEqual(rec1["risk_weighted_exposure"], 20000000.0)
        # Opp cost = 20M * 0.12 * (210 / 365) = 1,380,821.92
        self.assertEqual(rec1["estimated_opportunity_cost"], 1380821.92)
        self.assertEqual(rec1["financial_impact_priority"], "P1")

        rec3 = self.engine.evaluate_sku_financial_impact(self.sample_assessments[2])
        self.assertEqual(rec3["financial_impact_priority"], "P4")

    def test_ac04_ac05_ac06_ac08_ac10_portfolio_aggregations_and_concentration(self):
        """AC-04, AC-05, AC-06, AC-08, AC-10: Multi-dimensional aggregations, matrix & concentration KPIs."""
        summary_payload = self.engine.evaluate_portfolio_financial_impact(self.sample_assessments)

        summ = summary_payload["summary"]
        self.assertEqual(summ["sku_count"], 3)
        self.assertEqual(summ["total_inventory_value"], 34000000.0) # 20M + 12M + 2M
        self.assertEqual(summ["total_risk_weighted_exposure"], 29200000.0) # 20M + 9M + 0.2M
        self.assertGreater(summ["total_opportunity_cost"], 0.0)

        # Risk breakdown check
        risk_imp = summary_payload["financial_impact_by_risk"]
        self.assertEqual(len(risk_imp), 4)

        # Aging breakdown check
        aging_imp = summary_payload["financial_impact_by_aging"]
        self.assertEqual(len(aging_imp), 4)

        # Matrix check (16 cells)
        matrix = summary_payload["financial_impact_matrix"]
        self.assertEqual(len(matrix), 16)

        # Concentration check
        conc = summary_payload["financial_concentration"]
        self.assertEqual(conc["top_10_capital_exposure"], 34000000.0)

    def test_ac09_ac11_ac12_reconciliation_and_artifacts(self):
        """AC-09, AC-11, AC-12: Reconciliation verification & artifact saving."""
        summary_payload = self.engine.evaluate_portfolio_financial_impact(self.sample_assessments)

        # Reconciliation check
        rec_status = summary_payload["reconciliation_status"]
        self.assertTrue(rec_status["all_reconciled"])
        self.assertTrue(rec_status["inventory_reconciled"])
        self.assertTrue(rec_status["opportunity_cost_reconciled"])

        # Save artifacts check
        art_paths = self.engine.save_financial_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["financial_impact_summary"]))
        self.assertTrue(os.path.exists(art_paths["financial_impact_by_risk"]))
        self.assertTrue(os.path.exists(art_paths["financial_impact_by_aging"]))
        self.assertTrue(os.path.exists(art_paths["opportunity_cost_summary"]))
        self.assertTrue(os.path.exists(art_paths["financial_impact_matrix"]))
        self.assertTrue(os.path.exists(art_paths["top_financial_exposure_skus"]))
        self.assertTrue(os.path.exists(art_paths["financial_impact_validation"]))
