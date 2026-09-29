import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import DecisionContextBuilder, StrategyType
from src.analytics.action_eligibility_engine import ActionEligibilityEngine, ActionStatus
from src.analytics.recovery_strategy_engine import RecoveryStrategyEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine


class DecisionEligibilityAndStrategyTestCase(TestCase):
    """Test suite for DEC-001 (Action Eligibility) & DEC-002 (Strategy Recommendation)."""

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.eligibility_engine = ActionEligibilityEngine()
        self.strategy_engine = RecoveryStrategyEngine()
        self.recommendation_engine = DecisionRecommendationEngine()

    def test_dec_001_action_eligibility_guardrails(self):
        """DEC-001: Verify CLEARANCE eligibility requires Risk=HIGH, Capital available, Enough demand, No active campaign, Data confidence."""
        
        # 1. Fully eligible SKU
        ctx_eligible = self.builder.build_sku_decision_context(
            risk_record={"sku": "SKU_ELIGIBLE", "slow_moving_risk_class": "HIGH_RISK", "risk_probability": 0.85},
            capital_record={"capital_exposure": 10000000.0, "inventory_age_days": 120, "aging_bucket": "STALE"}
        )
        ctx_eligible["has_enough_demand"] = True
        ctx_eligible["active_campaign"] = False
        ctx_eligible["data_confidence"] = "SUFFICIENT"
        ctx_eligible["data_health_score"] = 90

        res_eligible = self.eligibility_engine.evaluate_sku_eligibility(ctx_eligible)
        self.assertIn("CLEARANCE", res_eligible["eligible_actions"])

        # 2. Blocked by Active Campaign
        ctx_campaign = dict(ctx_eligible)
        ctx_campaign["sku"] = "SKU_CAMPAIGN"
        ctx_campaign["active_campaign"] = True

        res_campaign = self.eligibility_engine.evaluate_sku_eligibility(ctx_campaign)
        self.assertNotIn("CLEARANCE", res_campaign["eligible_actions"])
        clearance_reasons = next(a["reasons"] for a in res_campaign["action_evaluations"] if a["action_id"] == "CLEARANCE")
        self.assertTrue(any("CLEARANCE_INELIGIBLE_CAMPAIGN" in r["rule"] for r in clearance_reasons))

        # 3. Blocked by Insufficient Data Confidence
        ctx_low_data = dict(ctx_eligible)
        ctx_low_data["sku"] = "SKU_LOW_DATA"
        ctx_low_data["data_confidence"] = "INSUFFICIENT"
        ctx_low_data["data_health_score"] = 20

        res_low_data = self.eligibility_engine.evaluate_sku_eligibility(ctx_low_data)
        self.assertNotIn("CLEARANCE", res_low_data["eligible_actions"])
        clearance_reasons_data = next(a["reasons"] for a in res_low_data["action_evaluations"] if a["action_id"] == "CLEARANCE")
        self.assertTrue(any("CLEARANCE_INELIGIBLE_CONFIDENCE" in r["rule"] for r in clearance_reasons_data))

    def test_dec_002_supported_strategy_vocabulary(self):
        """DEC-002: Verify all 7 strategies (CLEARANCE, DISCOUNT, BUNDLE, PROMOTION, REPOSITION, MONITOR, HOLD) are supported."""
        supported_strats = [s.value for s in StrategyType]
        
        self.assertIn("CLEARANCE", supported_strats)
        self.assertIn("DISCOUNT", supported_strats)
        self.assertIn("BUNDLE", supported_strats)
        self.assertIn("PROMOTION", supported_strats)
        self.assertIn("REPOSITION", supported_strats)
        self.assertIn("MONITOR", supported_strats)
        self.assertIn("HOLD", supported_strats)

        # Test evaluating REPOSITION eligibility
        ctx_reposition = self.builder.build_sku_decision_context(
            risk_record={"sku": "SKU_REPOSITION", "slow_moving_risk_class": "MEDIUM_RISK", "risk_probability": 0.50},
            capital_record={"capital_exposure": 2000000.0, "inventory_age_days": 45, "aging_bucket": "AGING"}
        )
        res_reposition = self.eligibility_engine.evaluate_sku_eligibility(ctx_reposition)
        self.assertIn("REPOSITION", res_reposition["eligible_actions"])
