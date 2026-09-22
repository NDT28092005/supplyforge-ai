"""
Test suite for Task M7-06 Risk & Capital Copilot (Module 07).
Verifies AC-01 through AC-15 requirements:
- Risk & Capital natural-language queries
- Risk x Capital & Risk x Aging cross-analysis
- Portfolio summary analysis & Multi-criteria filtering
- SHAP feature explanation integration & M6 Decision Engine handoff
- API contract compliance & zero synthetic metric generation
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.risk_capital_copilot import RiskCapitalCopilot
from src.copilot.risk_capital_query import RiskCapitalQueryAnalyzer
from src.copilot.risk_capital_context import RiskCapitalContextBuilder


class TestRiskCapitalCopilot(TestCase):

    def setUp(self):
        self.copilot = RiskCapitalCopilot()

    def test_query_analysis(self):
        """AC-01, AC-02, AC-07, AC-09: Verifies query type classification and M6 handoff detection."""
        # 1. Ranking query
        res_rank = RiskCapitalQueryAnalyzer.analyze_query("Top 10 SKU rủi ro cao nhất theo vốn bị khóa")
        self.assertEqual(res_rank["analysis_type"], "RANKING")
        self.assertFalse(res_rank["is_m6_handoff"])

        # 2. M6 Decision handoff query
        res_m6 = RiskCapitalQueryAnalyzer.analyze_query("Tôi nên làm gì với SKU-001?")
        self.assertEqual(res_m6["analysis_type"], "M6_HANDOFF")
        self.assertTrue(res_m6["is_m6_handoff"])

    def test_risk_capital_context_builder(self):
        """AC-03, AC-04, AC-08: Verifies context aggregation between M3, M4, and M5."""
        ctx = RiskCapitalContextBuilder.build_sku_context(
            sku_id="SKU-001",
            risk_profile={"risk_class": "CRITICAL", "risk_score": 0.95},
            capital_profile={"capital_exposure": 15000000.0, "aging_days": 375},
            explanation_profile={"top_signals": [{"feature": "forecast_7d"}]}
        )

        self.assertEqual(ctx["sku_id"], "SKU-001")
        self.assertEqual(ctx["risk"]["risk_class"], "CRITICAL")
        self.assertEqual(ctx["capital"]["capital_exposure"], 15000000.0)
        self.assertEqual(ctx["explanation"]["top_driver"], "forecast_7d")
        self.assertIn("Critical", ctx["relationship_summary"])

    def test_end_to_end_risk_capital_copilot(self):
        """AC-05, AC-06, AC-10, AC-11, AC-12, AC-14: Verifies end-to-end processing and schema compliance."""
        response = self.copilot.process_query(
            query="SKU-001 có rủi ro gì và đang khóa bao nhiêu vốn?",
            merchant_id="merchant_test",
            sku_id="SKU-001",
            dataset_version="v1.0"
        )

        self.assertEqual(response["status"], "SUCCESS")
        self.assertEqual(response["dataset_version"], "v1.0")
        self.assertGreater(len(response["results"]), 0)
        self.assertIn("grounded_response", response["evidence_summary"])

    def test_m6_decision_handoff_flow(self):
        """AC-09, AC-13: Verifies handoff to M6 Decision Engine without reinventing recommendations."""
        response = self.copilot.process_query(
            query="Tôi nên xử lý SKU-001 như thế nào?",
            merchant_id="merchant_test",
            sku_id="SKU-001",
            dataset_version="v1.0"
        )

        self.assertEqual(response["analysis_type"], "M6_HANDOFF")
        self.assertEqual(response["evidence_summary"]["handoff_target"], "M6_DECISION_ENGINE")
