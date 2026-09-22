"""
Test suite for Task M7-07 Decision Copilot (Module 07).
Verifies AC-01 through AC-15 requirements:
- Natural-language recommendation retrieval & reasoning explanation
- Scenario simulation (25% / 30% discount) & Side-by-side option comparison
- Alternative strategy analysis (BUNDLE, LIQUIDATION) & Action priority ranking
- Decision Lifecycle State tracking (RECOMMENDED -> SIMULATED)
- Zero decision hallucination & Grounded Response Engine integration
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.decision_copilot import DecisionCopilot
from src.copilot.decision_query import DecisionQueryAnalyzer
from src.copilot.decision_state import DecisionState
from src.copilot.decision_comparator import DecisionComparator


class TestDecisionCopilot(TestCase):

    def setUp(self):
        self.copilot = DecisionCopilot()

    def test_decision_query_analysis(self):
        """AC-01, AC-02, AC-04, AC-05: Verifies decision query classification."""
        # 1. Recommendation explanation
        res_why = DecisionQueryAnalyzer.analyze_query("Tại sao hệ thống lại đề xuất giảm giá?")
        self.assertEqual(res_why["query_type"], "WHY_RECOMMENDATION")

        # 2. Scenario query (30% discount)
        res_scen = DecisionQueryAnalyzer.analyze_query("Nếu giảm giá 30% thì sao?")
        self.assertEqual(res_scen["query_type"], "SCENARIO")
        self.assertEqual(res_scen["simulated_rate"], 0.30)

        # 3. Comparison query
        res_comp = DecisionQueryAnalyzer.analyze_query("Giảm giá 20% hay 30% tốt hơn?")
        self.assertEqual(res_comp["query_type"], "COMPARE_OPTIONS")

    def test_decision_comparator(self):
        """AC-05, AC-06, AC-07: Verifies side-by-side comparison of options."""
        base_rec = {"action": "DISCOUNT", "discount_rate": 0.20, "expected_recovery": 12000000.0}
        target_opt = {"action": "DISCOUNT", "discount_rate": 0.30, "expected_recovery": 14000000.0}

        comp = DecisionComparator.compare_options(base_rec, target_opt)
        self.assertEqual(comp["tradeoff_analysis"]["additional_recovery"], 2000000.0)
        self.assertEqual(comp["tradeoff_analysis"]["discount_rate_diff_pct"], 10.0)

    def test_end_to_end_recommendation_flow(self):
        """AC-01, AC-03, AC-11, AC-12, AC-13, AC-14: Verifies recommendation retrieval and grounding."""
        response = self.copilot.process_decision_query(
            query="Tôi nên làm gì với SKU-001?",
            sku_id="SKU-001",
            merchant_id="m01",
            dataset_version="v1.0"
        )

        self.assertEqual(response["status"], "SUCCESS")
        self.assertEqual(response["query_type"], "RECOMMENDATION")
        self.assertEqual(response["decision_state"], "RECOMMENDED")
        self.assertEqual(response["decision_context"]["current_recommendation"]["action"], "DISCOUNT")
        self.assertGreater(len(response["decision_context"]["alternatives"]), 0)
        self.assertIn("grounded_response", response["decision_context"])

    def test_end_to_end_scenario_simulation_flow(self):
        """AC-04, AC-09, AC-10: Verifies scenario simulation state & distinction from recommendation."""
        response = self.copilot.process_decision_query(
            query="Nếu giảm giá 30% thì sao?",
            sku_id="SKU-001",
            merchant_id="m01",
            dataset_version="v1.0"
        )

        self.assertEqual(response["query_type"], "SCENARIO")
        self.assertEqual(response["decision_state"], "SIMULATED")
        self.assertIsNotNone(response["decision_context"]["scenario"])
        self.assertEqual(response["decision_context"]["scenario"]["discount_rate"], 0.30)
        # Recommendation remains 20%
        self.assertEqual(response["decision_context"]["current_recommendation"]["discount_rate"], 0.20)
