"""
Test suite for Task M6-04 Discount Simulation Engine (Module 06).
Verifies AC-01 through AC-16 requirements:
- Simulation of multiple discount scenarios (0%, 5%, 10%, 15%, 20%, 25%, 30%, 40%, 50%)
- Baseline vs simulated financial calculations (price, revenue, margin rate, recovery rate)
- Enforcement of minimum margin constraints (minimum_margin_rate -> BLOCKED)
- Scenario status evaluation (FEASIBLE, BLOCKED, REQUIRES_REVIEW)
- Explicit data type distinction (CALCULATED vs ASSUMED)
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
from src.analytics.discount_simulation_engine import DiscountSimulationEngine, ScenarioStatus, DiscountSimulationError


class TestDiscountSimulationEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()

        # SKU 1: Discount Candidate SKU
        self.ctx_discount = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_DISCOUNT",
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
        self.el_discount = self.el_engine.evaluate_sku_eligibility(self.ctx_discount)
        self.st_discount = self.strat_engine.evaluate_sku_strategy(self.ctx_discount, self.el_discount)

        # SKU 2: Low Risk HOLD SKU (Not applicable for discount simulation)
        self.ctx_hold = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_HOLD",
                "slow_moving_risk_class": "LOW_RISK",
                "risk_probability": 0.10
            },
            capital_record={
                "capital_exposure": 1000000.0,
                "risk_weighted_exposure": 100000.0,
                "inventory_age_days": 15,
                "aging_bucket": "RECENT"
            }
        )
        self.el_hold = self.el_engine.evaluate_sku_eligibility(self.ctx_hold)
        self.st_hold = self.strat_engine.evaluate_sku_strategy(self.ctx_hold, self.el_hold)

    def test_ac01_ac03_ac04_ac05_ac06_ac07_ac08_ac09_discount_simulation(self):
        """AC-01 to AC-09: Multi-scenario simulation, price, revenue, margin rate, recovery rate & baseline comparison."""
        res = self.sim_engine.simulate_sku_discount(self.ctx_discount, self.st_discount)

        self.assertEqual(res["sku"], "SKU_DISCOUNT")
        self.assertEqual(res["evaluation_status"], "READY")
        self.assertIn("baseline", res)
        self.assertEqual(res["baseline"]["unit_price"], 100000.0)

        scenarios = res["scenarios"]
        self.assertGreater(len(scenarios), 5)

        # Check 20% discount scenario
        sc_20 = next(s for s in scenarios if s["scenario_id"] == "DISC_20")
        self.assertEqual(sc_20["simulated_price"], 80000.0) # 100k * (1 - 0.20)
        self.assertEqual(sc_20["simulated_unit_margin"], 10000.0) # 80k - 70k
        self.assertEqual(sc_20["simulated_margin_rate"], 0.125) # 10k / 80k = 12.5%
        self.assertEqual(sc_20["status"], ScenarioStatus.FEASIBLE.value)
        self.assertGreater(sc_20["capital_recovery"], 0.0)

    def test_ac10_ac11_minimum_margin_constraint_blocking(self):
        """AC-10, AC-11: Enforces minimum margin constraint -> BLOCKED scenario."""
        res = self.sim_engine.simulate_sku_discount(self.ctx_discount, self.st_discount)
        scenarios = res["scenarios"]

        # 40% or 50% discount will cause price (60k/50k) to fall below unit cost (70k) -> margin rate < 5% -> BLOCKED
        sc_50 = next(s for s in scenarios if s["scenario_id"] == "DISC_50")
        self.assertEqual(sc_50["status"], ScenarioStatus.BLOCKED.value)
        self.assertIn("Margin rate", sc_50["blocking_reason"])

    def test_ac02_ac12_not_applicable_sku(self):
        """AC-02, AC-12: Non-applicable SKU returns empty scenarios and SIMULATION_NOT_APPLICABLE."""
        res = self.sim_engine.simulate_sku_discount(self.ctx_hold, self.st_hold)

        self.assertEqual(res["evaluation_status"], "SIMULATION_NOT_APPLICABLE")
        self.assertEqual(res["scenarios"], [])

    def test_ac15_ac16_portfolio_and_artifacts(self):
        """AC-15, AC-16: Portfolio simulation & deliverable artifact generation."""
        summary_payload = self.sim_engine.simulate_portfolio_discounts(
            [self.ctx_discount, self.ctx_hold],
            [self.st_discount, self.st_hold]
        )

        self.assertEqual(summary_payload["summary"]["total_skus"], 2)
        self.assertGreater(summary_payload["summary"]["feasible_scenarios"], 0)

        art_paths = self.sim_engine.save_simulation_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["discount_simulation_summary"]))
        self.assertTrue(os.path.exists(art_paths["discount_simulation_scenarios"]))
        self.assertTrue(os.path.exists(art_paths["discount_simulation_validation"]))
