import pandas as pd
from django.test import TestCase

from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier
from src.analytics.aging_risk_classifier import AgingRiskClassifier
from src.analytics.capital_valuation_engine import CapitalValuationEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine
from src.analytics.action_eligibility_engine import ActionEligibilityEngine
from src.analytics.explanation_assembly_engine import ExplanationAssemblyEngine
from src.analytics.risk_scoring_engine import RiskScoringEngine


class BackendUnitTestPyramid(TestCase):
    """
    Task 3.1: Backend Unit Tests for core business logic domain functions.
    Covers: Risk scoring, Risk classification, Capital calculation, Aging classification,
    Decision rules, Eligibility rules, and Explanation mapping.
    """

    def setUp(self):
        self.risk_classifier = SlowMovingRiskClassifier()
        self.aging_classifier = AgingRiskClassifier()
        self.capital_engine = CapitalValuationEngine()
        self.decision_engine = DecisionRecommendationEngine()
        self.eligibility_engine = ActionEligibilityEngine()
        self.explanation_engine = ExplanationAssemblyEngine()
        self.scoring_engine = RiskScoringEngine()

    def test_critical_risk(self):
        """Test risk classification for a CRITICAL slow-moving SKU."""
        df_input = pd.DataFrame([{
            'sku': 'SKU_CRIT_001',
            'product_name': 'Test Critical Item',
            'slow_moving_signal_score': 0.85,
            'dsls': 150,
            'zero_rate': 0.95,
            'sales_velocity_30d': 0.0
        }])
        res = self.risk_classifier.classify_slow_moving_risk(df_input)
        self.assertIn("riskClassificationRecords", res)
        records = res["riskClassificationRecords"]
        self.assertTrue(len(records) > 0)
        self.assertEqual(records[0]["risk_level"], "CRITICAL")

    def test_risk_scoring_bounds(self):
        """Test risk scoring engine calculates scores within [0, 100] range."""
        df_input = pd.DataFrame([{
            'sku': 'SKU_SCORE_001',
            'dsls': 90,
            'inventory_turnover': 0.1,
            'sales_velocity_30d': 0.0,
            'zero_rate_90d': 0.8
        }])
        res_dict = self.scoring_engine.calculate_risk_scores(df_input)
        self.assertIn("scores", res_dict)
        records = res_dict["scores"]
        self.assertTrue(len(records) > 0)
        score = float(records[0].get('risk_score', 50.0))
        self.assertTrue(0.0 <= score <= 100.0)

    def test_risk_classification_categories(self):
        """Test risk classification maps items into valid severity bands."""
        df_input = pd.DataFrame([{
            'sku': 'SKU_LOW_001',
            'product_name': 'Test Healthy Item',
            'slow_moving_signal_score': 0.10,
            'dsls': 10,
            'zero_rate': 0.0,
            'sales_velocity_30d': 5.0
        }])
        res = self.risk_classifier.classify_slow_moving_risk(df_input)
        records = res["riskClassificationRecords"]
        self.assertEqual(records[0]["risk_level"], "LOW_RISK")

    def test_capital_exposure_valuation(self):
        """Test capital valuation engine computes correct holding cost & tied-up capital."""
        inv_dict = {
            "sku": "SKU_001",
            "stock_on_hand": 100,
            "unit_cost": 50000.0,
            "dsls": 90
        }
        r_dict = {"risk_class": "HIGH_RISK", "risk_probability": 0.85, "risk_score": 78.5}
        val = self.capital_engine.value_sku("SKU_001", inv_dict, r_dict)
        self.assertIn("inventory_capital_exposure", val)
        self.assertEqual(val["inventory_capital_exposure"], 5000000.0)

    def test_inventory_aging_classification(self):
        """Test inventory aging classifier categorizes days into standard buckets."""
        b1 = self.aging_classifier.classify_aging_risk_level(25)
        b2 = self.aging_classifier.classify_aging_risk_level(45)
        b3 = self.aging_classifier.classify_aging_risk_level(190)
        self.assertEqual(b1, "FRESH")
        self.assertEqual(b2, "AGING")
        self.assertEqual(b3, "CRITICAL_AGING")

    def test_decision_rules_recommendation(self):
        """Test decision engine generates CFO-grade recommendations based on risk & capital."""
        r_asm = {"sku": "SKU_TEST", "risk_class": "CRITICAL", "risk_probability": 0.9, "risk_score": 85.0}
        elig = {"sku": "SKU_TEST", "is_eligible": True, "eligible_actions": ["DISCOUNT_CAMPAIGN"]}
        strat = {"sku": "SKU_TEST", "recovery_strategy": "DISCOUNT_CAMPAIGN", "estimated_recovery_value": 45000000.0}
        rec = self.decision_engine.generate_sku_recommendation(r_asm, elig, strat)
        self.assertIn("action", rec)
        self.assertIn("priority", rec)

    def test_action_eligibility_rules(self):
        """Test action eligibility rules validate margin & liquidation constraints."""
        decision_context = {
            "sku": "SKU_001",
            "decision_status": "READY",
            "risk_context": {"risk_class": "CRITICAL", "risk_probability": 0.9},
            "capital_context": {"capital_exposure": 5000000.0},
            "aging_context": {"aging_bucket": "STALE", "aging_days": 95}
        }
        el = self.eligibility_engine.evaluate_sku_eligibility(decision_context)
        self.assertIn("evaluation_status", el)
        self.assertIn("eligible_actions", el)

    def test_explanation_mapping(self):
        """Test explanation assembly engine generates human-readable XAI breakdown."""
        feat_dict = {"sales_velocity_30d": 0.0, "sales_velocity_90d": 0.0}
        exp = self.explanation_engine.assemble_sku_explanation(
            "SKU_001", feat_dict, "CRITICAL", 0.92, 88.0
        )
        self.assertIn("sku", exp)
        self.assertIn("explanation_summary", exp)
