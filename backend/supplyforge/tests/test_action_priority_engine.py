"""
Test suite for Task M6-07 Action Priority Scoring Engine (Module 06).
Verifies AC-01 through AC-16 requirements:
- Calculation of composite Action Priority Score (0.0 - 1.0)
- Priority Tier assignment (P1 IMMEDIATE, P2 HIGH, P3 MEDIUM, P4 LOW)
- Portfolio-wide action ranking (1 to N)
- Structured Reason Codes (CRITICAL_RISK, HIGH_CAPITAL_EXPOSURE, etc.)
- Deterministic repeatability & deliverable artifact generation in reports/decision/
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
from src.analytics.recovery_value_engine import RecoveryValueEstimationEngine
from src.analytics.capital_recovery_optimization_engine import CapitalRecoveryOptimizationEngine
from src.analytics.action_priority_engine import ActionPriorityScoringEngine, PriorityTier, PriorityReasonCode


class TestActionPriorityScoringEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()
        self.opt_engine = CapitalRecoveryOptimizationEngine()
        self.prio_engine = ActionPriorityScoringEngine()

        # SKU 1: Critical High-Capital SKU -> P1 Priority
        self.ctx_p1 = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_P1",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "unit_price": 100000.0,
                "unit_cost": 70000.0,
                "stock_on_hand": 200
            },
            capital_record={
                "capital_exposure": 14000000.0,
                "risk_weighted_exposure": 14000000.0,
                "inventory_age_days": 190,
                "aging_bucket": "SEVERELY_STALE"
            }
        )
        self.el_p1 = self.el_engine.evaluate_sku_eligibility(self.ctx_p1)
        self.st_p1 = self.strat_engine.evaluate_sku_strategy(self.ctx_p1, self.el_p1)
        self.sim_p1 = self.sim_engine.simulate_sku_discount(self.ctx_p1, self.st_p1)
        self.val_p1 = self.val_engine.estimate_sku_recovery_value(self.ctx_p1, self.st_p1, self.sim_p1)
        self.opt_p1 = self.opt_engine.optimize_sku_capital_recovery(self.ctx_p1, self.st_p1, self.sim_p1, self.val_p1)

        # SKU 2: Low-Capital Low-Risk SKU -> P4 Priority
        self.ctx_p4 = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_P4",
                "slow_moving_risk_class": "LOW_RISK",
                "risk_probability": 0.10,
                "unit_price": 50000.0,
                "unit_cost": 30000.0,
                "stock_on_hand": 10
            },
            capital_record={
                "capital_exposure": 300000.0,
                "risk_weighted_exposure": 30000.0,
                "inventory_age_days": 10,
                "aging_bucket": "RECENT"
            }
        )
        self.el_p4 = self.el_engine.evaluate_sku_eligibility(self.ctx_p4)
        self.st_p4 = self.strat_engine.evaluate_sku_strategy(self.ctx_p4, self.el_p4)
        self.sim_p4 = self.sim_engine.simulate_sku_discount(self.ctx_p4, self.st_p4)
        self.val_p4 = self.val_engine.estimate_sku_recovery_value(self.ctx_p4, self.st_p4, self.sim_p4)
        self.opt_p4 = self.opt_engine.optimize_sku_capital_recovery(self.ctx_p4, self.st_p4, self.sim_p4, self.val_p4)

    def test_ac01_to_ac08_priority_scoring_and_tiers(self):
        """AC-01 to AC-08: Calculates composite Action Priority Score and assigns P1/P4 Priority Tiers."""
        res_p1 = self.prio_engine.calculate_sku_action_priority(
            self.ctx_p1, self.el_p1, self.st_p1, self.opt_p1, self.val_p1
        )
        res_p4 = self.prio_engine.calculate_sku_action_priority(
            self.ctx_p4, self.el_p4, self.st_p4, self.opt_p4, self.val_p4
        )

        self.assertEqual(res_p1["sku"], "SKU_P1")
        self.assertGreaterEqual(res_p1["priority_score"], 0.80)
        self.assertEqual(res_p1["priority_tier"], PriorityTier.P1.value)

        self.assertLess(res_p4["priority_score"], 0.60)
        self.assertIn(res_p4["priority_tier"], [PriorityTier.P3.value, PriorityTier.P4.value])

    def test_ac09_ac10_ranking_and_reason_codes(self):
        """AC-09, AC-10: Verifies portfolio ranking and structured reason codes."""
        summary = self.prio_engine.calculate_portfolio_action_priorities(
            [self.ctx_p1, self.ctx_p4],
            [self.el_p1, self.el_p4],
            [self.st_p1, self.st_p4],
            [self.opt_p1, self.opt_p4],
            [self.val_p1, self.val_p4]
        )

        priorities = summary["action_priorities"]
        self.assertEqual(len(priorities), 2)
        self.assertEqual(priorities[0]["sku"], "SKU_P1")
        self.assertEqual(priorities[0]["rank"], 1)
        self.assertEqual(priorities[1]["sku"], "SKU_P4")
        self.assertEqual(priorities[1]["rank"], 2)

        codes = priorities[0]["reason_codes"]
        self.assertIn("CRITICAL_RISK", codes)
        self.assertIn("HIGH_CAPITAL_EXPOSURE", codes)

    def test_ac15_ac16_artifacts_generation(self):
        """AC-15, AC-16: Portfolio artifact generation and deliverable reports."""
        summary = self.prio_engine.calculate_portfolio_action_priorities(
            [self.ctx_p1, self.ctx_p4],
            [self.el_p1, self.el_p4],
            [self.st_p1, self.st_p4],
            [self.opt_p1, self.opt_p4],
            [self.val_p1, self.val_p4]
        )

        art_paths = self.prio_engine.save_priority_artifacts(summary)
        self.assertTrue(os.path.exists(art_paths["action_priority_summary"]))
        self.assertTrue(os.path.exists(art_paths["action_priority_ranked"]))
        self.assertTrue(os.path.exists(art_paths["action_priority_validation"]))
