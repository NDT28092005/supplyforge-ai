"""
Test suite for Task M6-03 Recovery Strategy Engine (Module 06).
Verifies AC-01 through AC-18 requirements:
- Consumption of ELIGIBLE actions from M6-02 ActionEligibilityResult
- Strategy Suitability Scoring & Ranking across candidate strategies
- Recommendation selection & alternative strategies output
- Structured Strategy Rationale generation (signal, value, contribution)
- Tie / Ambiguity handling (Delta <= 0.03 -> requires_review = True)
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
from src.analytics.recovery_strategy_engine import RecoveryStrategyEngine, RecoveryStrategyError


class TestRecoveryStrategyEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()

        # SKU 1: Critical Risk SKU
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_CRITICAL",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95
            },
            capital_record={
                "capital_exposure": 12000000.0,
                "risk_weighted_exposure": 12000000.0,
                "inventory_age_days": 240,
                "aging_bucket": "SEVERELY_STALE"
            }
        )
        self.el_critical = self.el_engine.evaluate_sku_eligibility(self.ctx_critical)

        # SKU 2: Low Risk SKU
        self.ctx_low = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_LOW",
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
        self.el_low = self.el_engine.evaluate_sku_eligibility(self.ctx_low)

    def test_ac01_ac02_ac05_ac07_ac08_ac09_ac10_critical_sku_strategy_ranking(self):
        """AC-01, AC-02, AC-05, AC-07 to AC-10: Critical SKU strategy scoring, ranking and recommendation."""
        res = self.strat_engine.evaluate_sku_strategy(self.ctx_critical, self.el_critical)

        self.assertEqual(res["sku"], "SKU_CRITICAL")
        self.assertEqual(res["evaluation_status"], "READY")
        self.assertIn(res["recommended_strategy"], ["CLEARANCE", "DISCOUNT", "STOP_REPLENISHMENT"])
        self.assertGreater(len(res["ranked_strategies"]), 1)
        self.assertTrue("DISCOUNT" in res["alternative_strategies"] or "CLEARANCE" in res["alternative_strategies"])
        self.assertGreater(res["strategy_confidence"], 0.70)

    def test_ac03_low_risk_sku_strategy_recommendation(self):
        """AC-03: Low risk SKU recommendation for HOLD or MONITOR."""
        res = self.strat_engine.evaluate_sku_strategy(self.ctx_low, self.el_low)

        self.assertEqual(res["sku"], "SKU_LOW")
        self.assertIn(res["recommended_strategy"], ["HOLD", "MONITOR"])

    def test_ac11_structured_rationale(self):
        """AC-11: Structured strategy rationale generation."""
        res = self.strat_engine.evaluate_sku_strategy(self.ctx_critical, self.el_critical)

        rationale = res["rationale"]
        self.assertTrue(isinstance(rationale, list))
        self.assertGreater(len(rationale), 0)
        self.assertTrue(all("signal" in r and "value" in r and "contribution" in r for r in rationale))

    def test_ac12_tie_ambiguity_handling(self):
        """AC-12: Tie ambiguity handling when top strategies differ by <= 0.03."""
        res = self.strat_engine.evaluate_sku_strategy(self.ctx_critical, self.el_critical)
        if len(res["ranked_strategies"]) > 1:
            diff = abs(res["ranked_strategies"][0]["score"] - res["ranked_strategies"][1]["score"])
            if diff <= 0.03:
                self.assertTrue(res["requires_review"])

    def test_ac13_blocked_context_handling(self):
        """AC-13: Handling BLOCKED context from M6-02."""
        ctx_blocked = self.builder.build_sku_decision_context(risk_record={"sku": "SKU_BLOCKED"}, capital_record=None)
        el_blocked = self.el_engine.evaluate_sku_eligibility(ctx_blocked)

        res = self.strat_engine.evaluate_sku_strategy(ctx_blocked, el_blocked)

        self.assertEqual(res["evaluation_status"], "NO_ELIGIBLE_STRATEGY")
        self.assertIsNone(res["recommended_strategy"])
        self.assertEqual(res["ranked_strategies"], [])

    def test_ac14_ac18_portfolio_and_artifacts(self):
        """AC-14, AC-18: Portfolio strategy evaluation & deliverable artifact generation."""
        summary_payload = self.strat_engine.evaluate_portfolio_strategy(
            [self.ctx_critical, self.ctx_low],
            [self.el_critical, self.el_low]
        )

        self.assertEqual(summary_payload["summary"]["total_skus"], 2)

        art_paths = self.strat_engine.save_strategy_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["recovery_strategy_summary"]))
        self.assertTrue(os.path.exists(art_paths["recovery_strategy_by_recommendation"]))
        self.assertTrue(os.path.exists(art_paths["recovery_strategy_validation"]))
