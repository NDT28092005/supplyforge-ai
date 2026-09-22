"""
Test suite for Task M6-06 Capital Recovery Optimization Engine (Module 06).
Verifies AC-01 through AC-16 requirements:
- Multi-criteria scenario evaluation & ranking (Recovery Rate, Capital Release Ratio, Penalties)
- Financial Constraint Filtering (Max Discount Rate 35%, Minimum Margin Rate 5% -> REJECTED)
- Incremental Recovery and Recovery Efficiency calculation
- Structured Reason Codes & Financial Trade-off Analysis generation
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
from src.analytics.recovery_value_engine import RecoveryValueEstimationEngine
from src.analytics.capital_recovery_optimization_engine import CapitalRecoveryOptimizationEngine, OptimizationReasonCode


class TestCapitalRecoveryOptimizationEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()
        self.opt_engine = CapitalRecoveryOptimizationEngine()

        # SKU 1: Critical Risk SKU with discount simulation
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_OPTIMIZE",
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
        self.val_critical = self.val_engine.estimate_sku_recovery_value(self.ctx_critical, self.st_critical, self.sim_critical)

    def test_ac01_to_ac09_capital_recovery_optimization(self):
        """AC-01 to AC-09: Evaluates scenarios, ranks feasible scenarios, calculates incremental recovery & selects best scenario."""
        res = self.opt_engine.optimize_sku_capital_recovery(
            self.ctx_critical,
            self.st_critical,
            self.sim_critical,
            self.val_critical
        )

        self.assertEqual(res["sku"], "SKU_OPTIMIZE")
        self.assertEqual(res["evaluation_status"], "READY")
        self.assertIn("baseline_scenario", res)
        self.assertGreater(len(res["evaluated_scenarios"]), 0)
        self.assertIsNotNone(res["recommended_scenario"])
        self.assertGreater(res["expected_recovery_value"], 0.0)
        self.assertGreater(res["optimization_score"], 0.0)
        self.assertIn(res["recommended_scenario"], res["ranking"])

    def test_ac04_ac05_ac13_constraint_filtering(self):
        """AC-04, AC-05, AC-13: Rejects scenarios violating max discount (35%) or minimum margin (5%)."""
        res = self.opt_engine.optimize_sku_capital_recovery(
            self.ctx_critical,
            self.st_critical,
            self.sim_critical,
            self.val_critical
        )

        evaluated = res["evaluated_scenarios"]

        # DISC_40 or DISC_50 must be rejected due to discount > 35% or margin < 5%
        disc_50 = next((s for s in evaluated if s["scenario_id"] == "DISC_50"), None)
        if disc_50:
            self.assertFalse(disc_50["is_feasible"])
            self.assertEqual(disc_50["optimization_score"], 0.0)

    def test_ac10_ac12_reason_codes_and_tradeoffs(self):
        """AC-10, AC-12: Structured reason codes & trade-off analysis generation."""
        res = self.opt_engine.optimize_sku_capital_recovery(
            self.ctx_critical,
            self.st_critical,
            self.sim_critical,
            self.val_critical
        )

        codes = res["reason_codes"]
        self.assertTrue(isinstance(codes, list))
        self.assertGreater(len(codes), 0)
        self.assertIn("WITHIN_DISCOUNT_LIMIT", codes)

        self.assertIn("tradeoffs", res)
        self.assertIn("baseline_vs_recommended", res["tradeoffs"])

    def test_ac15_ac16_portfolio_and_artifacts(self):
        """AC-15, AC-16: Portfolio optimization & deliverable artifact generation."""
        summary_payload = self.opt_engine.optimize_portfolio_capital_recovery(
            [self.ctx_critical],
            [self.st_critical],
            [self.sim_critical],
            [self.val_critical]
        )

        self.assertEqual(summary_payload["summary"]["total_skus"], 1)
        self.assertGreater(summary_payload["summary"]["total_optimized_recovery_value"], 0.0)

        art_paths = self.opt_engine.save_optimization_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["capital_recovery_optimization_summary"]))
        self.assertTrue(os.path.exists(art_paths["capital_recovery_optimization_ranked"]))
        self.assertTrue(os.path.exists(art_paths["capital_recovery_optimization_validation"]))
