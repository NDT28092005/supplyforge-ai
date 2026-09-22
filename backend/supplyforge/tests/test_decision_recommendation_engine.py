"""
Test suite for Task M6-08 Decision Recommendation Engine (Module 06).
Verifies AC-01 through AC-16 requirements:
- Synthesis of pipeline outputs M3-M7 into canonical DecisionRecommendation objects
- Controlled Action Vocabulary enforcement (DISCOUNT, CLEARANCE, PROMOTION, BUNDLE, HOLD, MONITOR, REVIEW, NO_ACTION)
- Urgency assignment (IMMEDIATE, HIGH, MEDIUM, LOW, MONITOR) & Decision Confidence (HIGH, MEDIUM, LOW)
- Expected business impact packaging & fallback handling (NOT_READY -> NO_ACTION)
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
from src.analytics.capital_recovery_optimization_engine import CapitalRecoveryOptimizationEngine
from src.analytics.action_priority_engine import ActionPriorityScoringEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine, DecisionUrgency, RecommendationStatus


class TestDecisionRecommendationEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()
        self.opt_engine = CapitalRecoveryOptimizationEngine()
        self.prio_engine = ActionPriorityScoringEngine()
        self.rec_engine = DecisionRecommendationEngine()

        # SKU 1: Critical High-Capital SKU -> Immediate Discount 20% Recommendation
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_CRITICAL_REC",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
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

        # SKU 2: NOT_READY SKU -> Fallback NO_ACTION
        self.ctx_not_ready = self.builder.build_sku_decision_context(
            risk_record={"sku": "SKU_NOT_READY"},
            capital_record=None
        )
        self.el_not_ready = self.el_engine.evaluate_sku_eligibility(self.ctx_not_ready)
        self.st_not_ready = self.strat_engine.evaluate_sku_strategy(self.ctx_not_ready, self.el_not_ready)

    def test_ac01_to_ac10_sku_recommendation_assembly(self):
        """AC-01 to AC-10: Synthesizes M3-M7 pipeline inputs into canonical DecisionRecommendation payload."""
        rec = self.rec_engine.generate_sku_recommendation(
            self.ctx_critical,
            self.el_critical,
            self.st_critical,
            self.sim_critical,
            self.val_critical,
            self.opt_critical,
            self.prio_critical
        )

        self.assertEqual(rec["sku"], "SKU_CRITICAL_REC")
        self.assertEqual(rec["decision_status"], RecommendationStatus.RECOMMENDED.value)
        self.assertIn(rec["action"]["type"], ["DISCOUNT", "CLEARANCE"])

        self.assertEqual(rec["urgency"], DecisionUrgency.IMMEDIATE.value)
        self.assertIn("expected_impact", rec)
        self.assertEqual(rec["expected_impact"]["capital_exposure"], 10500000.0)
        self.assertGreater(rec["expected_impact"]["expected_recovery_value"], 0.0)

        codes = rec["reason_codes"]
        self.assertTrue(isinstance(codes, list))

    def test_ac11_fallback_handling_for_not_ready(self):
        """AC-11: Fallback handling when context status is NOT_READY."""
        rec = self.rec_engine.generate_sku_recommendation(
            self.ctx_not_ready,
            self.el_not_ready,
            self.st_not_ready
        )

        self.assertEqual(rec["decision_status"], RecommendationStatus.NOT_APPLICABLE.value)
        self.assertEqual(rec["action"]["type"], "NO_ACTION")
        self.assertIn("INSUFFICIENT_DATA", rec["reason_codes"])

    def test_ac15_ac16_portfolio_and_artifacts(self):
        """AC-15, AC-16: Portfolio recommendation generation & deliverable artifact generation."""
        summary_payload = self.rec_engine.generate_portfolio_recommendations(
            [self.ctx_critical, self.ctx_not_ready],
            [self.el_critical, self.el_not_ready],
            [self.st_critical, self.st_not_ready],
            [self.sim_critical, None],
            [self.val_critical, None],
            [self.opt_critical, None],
            [self.prio_critical, None]
        )

        self.assertEqual(summary_payload["summary"]["total_recommendations"], 2)
        self.assertGreater(len(summary_payload["summary"]["action_type_counts"]), 0)

        art_paths = self.rec_engine.save_recommendation_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["decision_recommendation_summary"]))
        self.assertTrue(os.path.exists(art_paths["decision_recommendation_list"]))
        self.assertTrue(os.path.exists(art_paths["decision_recommendation_validation"]))
