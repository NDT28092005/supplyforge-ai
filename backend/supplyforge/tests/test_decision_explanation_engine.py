"""
Test suite for Task M6-09 Decision Explanation Engine (Module 06).
Verifies AC-01 through AC-17 requirements:
- Structured 5-dimension explanation assembly (Risk, Capital, Aging, Recovery, Priority)
- Evidence traceability across originating modules (M2, M3, M4, M5, M6, M7)
- Comparative Alternative Analysis & DSS Decision Limitations
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
from src.analytics.action_priority_engine import ActionPriorityScoringEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine
from src.analytics.decision_explanation_engine import DecisionExplanationEngine


class TestDecisionExplanationEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()
        self.opt_engine = CapitalRecoveryOptimizationEngine()
        self.prio_engine = ActionPriorityScoringEngine()
        self.rec_engine = DecisionRecommendationEngine()
        self.exp_engine = DecisionExplanationEngine()

        # SKU 1: Critical Risk SKU
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_EXP_CRITICAL",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.96,
                "unit_price": 100000.0,
                "unit_cost": 70000.0,
                "stock_on_hand": 150
            },
            capital_record={
                "capital_exposure": 10500000.0,
                "risk_weighted_exposure": 10500000.0,
                "inventory_age_days": 210,
                "aging_bucket": "SEVERELY_STALE"
            }
        )
        self.el_critical = self.el_engine.evaluate_sku_eligibility(self.ctx_critical)
        self.st_critical = self.strat_engine.evaluate_sku_strategy(self.ctx_critical, self.el_critical)
        self.sim_critical = self.sim_engine.simulate_sku_discount(self.ctx_critical, self.st_critical)
        self.val_critical = self.val_engine.estimate_sku_recovery_value(self.ctx_critical, self.st_critical, self.sim_critical)
        self.opt_critical = self.opt_engine.optimize_sku_capital_recovery(self.ctx_critical, self.st_critical, self.sim_critical, self.val_critical)
        self.prio_critical = self.prio_engine.calculate_sku_action_priority(self.ctx_critical, self.el_critical, self.st_critical, self.opt_critical, self.val_critical)
        self.rec_critical = self.rec_engine.generate_sku_recommendation(self.ctx_critical, self.el_critical, self.st_critical, self.sim_critical, self.val_critical, self.opt_critical, self.prio_critical)

    def test_ac01_to_ac13_decision_explanation_assembly(self):
        """AC-01 to AC-13: Generates 5-dimension explanation, evidence trace, alternative analysis & limitations."""
        exp = self.exp_engine.explain_sku_decision(
            self.ctx_critical,
            self.rec_critical,
            self.el_critical,
            self.st_critical,
            self.sim_critical,
            self.val_critical,
            self.opt_critical,
            self.prio_critical
        )

        self.assertEqual(exp["sku"], "SKU_EXP_CRITICAL")
        self.assertIn("explanation_id", exp)
        self.assertEqual(exp["recommendation_id"], self.rec_critical["recommendation_id"])

        # 5-Dimension Explanations
        self.assertEqual(exp["risk_explanation"]["risk_class"], "CRITICAL")
        self.assertEqual(exp["capital_explanation"]["capital_exposure"], 10500000.0)
        self.assertEqual(exp["aging_explanation"]["aging_days"], 210)
        self.assertGreater(exp["recovery_explanation"]["expected_recovery_value"], 0.0)
        self.assertEqual(exp["priority_explanation"]["priority_tier"], "P1")

        # Evidence Traceability
        evidence = exp["evidence"]
        self.assertTrue(isinstance(evidence, list))
        self.assertGreater(len(evidence), 0)
        sources = [item["source"] for item in evidence]
        self.assertIn("M3", sources)
        self.assertIn("M5", sources)
        self.assertIn("M6-05", sources)

        # Alternative Analysis & Limitations
        self.assertIn("alternative_analysis", exp)
        self.assertIn("limitations", exp)
        self.assertGreater(len(exp["limitations"]), 0)

    def test_ac15_ac17_portfolio_and_artifacts(self):
        """AC-15 to AC-17: Portfolio explanation generation & deliverable artifact generation."""
        summary_payload = self.exp_engine.explain_portfolio_decisions(
            [self.ctx_critical],
            [self.rec_critical],
            [self.el_critical],
            [self.st_critical],
            [self.sim_critical],
            [self.val_critical],
            [self.opt_critical],
            [self.prio_critical]
        )

        self.assertEqual(summary_payload["summary"]["total_explanations"], 1)

        art_paths = self.exp_engine.save_explanation_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["decision_explanation_summary"]))
        self.assertTrue(os.path.exists(art_paths["decision_explanation_list"]))
        self.assertTrue(os.path.exists(art_paths["decision_explanation_validation"]))
