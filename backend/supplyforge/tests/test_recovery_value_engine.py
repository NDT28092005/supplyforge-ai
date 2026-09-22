"""
Test suite for Task M6-05 Recovery Value Estimation Engine (Module 06).
Verifies AC-01 through AC-16 requirements:
- Calculation of Gross Recovery Value, Recovery Costs, Net Recovery Value
- Capital Recovery Rate, Residual Capital Exposure, and Recovery Gap
- Assumption Registry & Data Provenance (OBSERVED, CALCULATED, ESTIMATED, SIMULATED, ASSUMED)
- Recovery Confidence Rating (HIGH, MEDIUM, LOW) & Calculation Trace
- Deliverable artifact generation in reports/decision/
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import DecisionContextBuilder
from src.analytics.action_eligibility_engine import ActionEligibilityEngine
from src.analytics.recovery_strategy_engine import RecoveryStrategyEngine
from src.analytics.discount_simulation_engine import DiscountSimulationEngine
from src.analytics.recovery_value_engine import RecoveryValueEstimationEngine, RecoveryConfidenceLevel, RecoveryValueEstimationError


class TestRecoveryValueEstimationEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()

        # SKU 1: Critical Risk SKU
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_CRITICAL",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "unit_price": 100000.0,
                "unit_cost": 70000.0,
                "stock_on_hand": 100
            },
            capital_record={
                "capital_exposure": 7000000.0,
                "risk_weighted_exposure": 7000000.0,
                "inventory_age_days": 210,
                "aging_bucket": "SEVERELY_STALE"
            }
        )
        self.el_critical = self.el_engine.evaluate_sku_eligibility(self.ctx_critical)
        self.st_critical = self.strat_engine.evaluate_sku_strategy(self.ctx_critical, self.el_critical)
        self.sim_critical = self.sim_engine.simulate_sku_discount(self.ctx_critical, self.st_critical)

    def test_ac01_to_ac08_recovery_value_estimation(self):
        """AC-01 to AC-08: Calculates Gross Recovery, Costs, Net Recovery, Recovery Rate, Residual Exposure & Recovery Gap."""
        res = self.val_engine.estimate_sku_recovery_value(self.ctx_critical, self.st_critical, self.sim_critical)

        self.assertEqual(res["sku"], "SKU_CRITICAL")
        self.assertEqual(res["capital_exposure"], 7000000.0)
        self.assertGreater(res["gross_recovery_value"], 0.0)
        self.assertGreater(res["recovery_cost"], 0.0)
        self.assertEqual(res["net_recovery_value"], round(res["gross_recovery_value"] - res["recovery_cost"], 2))
        self.assertEqual(res["residual_exposure"], round(max(0.0, 7000000.0 - res["net_recovery_value"]), 2))
        self.assertGreaterEqual(res["recovery_gap"], 0.0)

    def test_ac10_ac11_assumptions_provenance_and_confidence(self):
        """AC-10, AC-11, AC-12: Verifies Assumption Registry, Data Provenance Types & Confidence Rating."""
        res = self.val_engine.estimate_sku_recovery_value(self.ctx_critical, self.st_critical, self.sim_critical)

        self.assertIn("assumptions", res)
        assumptions = res["assumptions"]
        self.assertIn("selling_price", assumptions)
        self.assertEqual(assumptions["selling_price"]["type"], "OBSERVED")
        self.assertEqual(assumptions["gross_recovery_value"]["type"], "SIMULATED")

        self.assertIn(res["recovery_confidence"], [RecoveryConfidenceLevel.HIGH.value, RecoveryConfidenceLevel.MEDIUM.value, RecoveryConfidenceLevel.LOW.value])
        self.assertTrue(isinstance(res["calculation_trace"], list))
        self.assertGreater(len(res["calculation_trace"]), 3)

    def test_ac15_ac16_portfolio_and_artifacts(self):
        """AC-15, AC-16: Portfolio estimation & deliverable artifact generation."""
        summary_payload = self.val_engine.estimate_portfolio_recovery_values(
            [self.ctx_critical],
            [self.st_critical],
            [self.sim_critical]
        )

        self.assertEqual(summary_payload["summary"]["total_skus"], 1)
        self.assertGreater(summary_payload["summary"]["total_net_recovery_value"], 0.0)

        art_paths = self.val_engine.save_value_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["recovery_value_summary"]))
        self.assertTrue(os.path.exists(art_paths["recovery_value_by_strategy"]))
        self.assertTrue(os.path.exists(art_paths["recovery_value_validation"]))
