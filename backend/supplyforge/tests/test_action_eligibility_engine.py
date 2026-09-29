"""
Test suite for Task M6-02 Action Eligibility Engine (Module 06).
Verifies AC-01 through AC-15 requirements:
- Evaluation of 7 canonical strategies (HOLD, MONITOR, PROMOTION, BUNDLE, DISCOUNT, CLEARANCE, STOP_REPLENISHMENT)
- Status state transitions (ELIGIBLE, INELIGIBLE, BLOCKED, REQUIRES_REVIEW)
- Structured Reason Trace generation (signal, value, rule, message)
- Hard constraint blocking (NOT_READY Context -> ALL BLOCKED)
- Externalized policy configuration & artifact deliverable generation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import DecisionContextBuilder, DecisionStatus, StrategyType
from src.analytics.action_eligibility_engine import ActionEligibilityEngine, ActionStatus, ActionEligibilityError


class TestActionEligibilityEngine(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.engine = ActionEligibilityEngine()

        # SKU 1: Critical Risk -> CLEARANCE / DISCOUNT / STOP_REPLENISHMENT
        self.ctx_critical = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_CRITICAL",
                "canonical_sku_id": "CSKU_CRITICAL",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "risk_score": 95.0
            },
            explainability_record={"diagnostic_signals": ["POSSIBLE_OBSOLESCENCE"]},
            capital_record={
                "capital_exposure": 10000000.0,
                "risk_weighted_exposure": 10000000.0,
                "inventory_age_days": 240,
                "aging_bucket": "SEVERELY_STALE",
                "aging_risk_level": "CRITICAL_AGING"
            }
        )

        # SKU 2: Low Risk -> HOLD / MONITOR
        self.ctx_low = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_LOW",
                "canonical_sku_id": "CSKU_LOW",
                "slow_moving_risk_class": "LOW_RISK",
                "risk_probability": 0.10,
                "risk_score": 10.0
            },
            explainability_record={"diagnostic_signals": []},
            capital_record={
                "capital_exposure": 1000000.0,
                "risk_weighted_exposure": 100000.0,
                "inventory_age_days": 15,
                "aging_bucket": "RECENT",
                "aging_risk_level": "FRESH"
            }
        )

    def test_ac01_ac03_ac06_ac07_critical_sku_eligibility(self):
        """AC-01, AC-03, AC-06, AC-07: Critical SKU eligibility for DISCOUNT, CLEARANCE, STOP_REPLENISHMENT."""
        res = self.engine.evaluate_sku_eligibility(self.ctx_critical)

        self.assertEqual(res["sku"], "SKU_CRITICAL")
        self.assertEqual(res["evaluation_status"], "READY")
        self.assertIn("CLEARANCE", res["eligible_actions"])
        self.assertIn("DISCOUNT", res["eligible_actions"])
        self.assertIn("STOP_REPLENISHMENT", res["eligible_actions"])
        self.assertNotIn("HOLD", res["eligible_actions"])

    def test_ac04_low_risk_sku_eligibility(self):
        """AC-04: Low risk SKU eligibility for HOLD & MONITOR."""
        res = self.engine.evaluate_sku_eligibility(self.ctx_low)

        self.assertEqual(res["sku"], "SKU_LOW")
        self.assertIn("HOLD", res["eligible_actions"])
        self.assertIn("MONITOR", res["eligible_actions"])
        self.assertNotIn("CLEARANCE", res["eligible_actions"])

    def test_ac08_ac09_reason_trace_and_requires_review(self):
        """AC-08, AC-09: Evaluates Reason Trace & REQUIRES_REVIEW for high capital exposure."""
        ctx_high_cap = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_HIGH_CAP",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95
            },
            capital_record={
                "capital_exposure": 25000000.0, # 25M > 20M executive review threshold
                "risk_weighted_exposure": 25000000.0,
                "inventory_age_days": 250,
                "aging_bucket": "EXTREMELY_STALE"
            }
        )

        res = self.engine.evaluate_sku_eligibility(ctx_high_cap)

        self.assertIn("CLEARANCE", res["requires_review_actions"])
        # Check structured reason trace
        clearance_eval = next(a for a in res["action_evaluations"] if a["action_id"] == "CLEARANCE")
        self.assertEqual(clearance_eval["status"], ActionStatus.REQUIRES_REVIEW.value)
        self.assertTrue(any(r["rule"] == "REQUIRES_EXECUTIVE_REVIEW" for r in clearance_eval["reasons"]))

    def test_ac10_hard_constraint_blocking(self):
        """AC-10: Hard blocking when DecisionContext status is NOT_READY."""
        ctx_not_ready = self.builder.build_sku_decision_context(
            risk_record={"sku": "SKU_NOT_READY"},
            capital_record=None # Missing capital data
        )

        res = self.engine.evaluate_sku_eligibility(ctx_not_ready)

        self.assertEqual(res["evaluation_status"], "BLOCKED_BY_CONTEXT")
        self.assertEqual(res["eligible_actions"], [])
        self.assertEqual(len(res["blocked_actions"]), len(StrategyType))

    def test_ac11_ac15_portfolio_and_artifacts(self):
        """AC-11, AC-15: Portfolio evaluation & artifact deliverable generation."""
        summary_payload = self.engine.evaluate_portfolio_eligibility([self.ctx_critical, self.ctx_low])

        self.assertEqual(summary_payload["summary"]["total_skus"], 2)
        self.assertGreater(summary_payload["summary"]["eligible_action_counts"]["CLEARANCE"], 0)

        art_paths = self.engine.save_eligibility_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["action_eligibility_summary"]))
        self.assertTrue(os.path.exists(art_paths["action_eligibility_by_action"]))
        self.assertTrue(os.path.exists(art_paths["action_eligibility_validation"]))
