"""
Test suite for Task M7-01 Copilot Architecture (Module 07).
Verifies AC-01 through AC-10 requirements:
- 5-Layer Copilot Architecture pipeline execution
- Intent Classification & Out of Scope detection
- Trusted DSS Tool Contracts & Execution
- Minimal Grounded Context Construction
- LLM Boundary Enforcement (0 direct LLM calculations)
- Copilot Response Schema Contract Compliance
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.copilot_architecture import (
    CopilotOrchestrator, CopilotIntent, CopilotIntentClassifier,
    CopilotToolRegistry, CopilotContextBuilder,
)


class TestCopilotArchitecture(TestCase):

    def setUp(self):
        self.orchestrator = CopilotOrchestrator()

    def test_intent_classification(self):
        """AC-01, AC-02: Verifies natural language intent classification."""
        # Risk query
        res1 = CopilotIntentClassifier.classify_query("Sản phẩm SKU-001 có nguy cơ rủi ro bán chậm không?")
        self.assertEqual(res1["code"], CopilotIntent.RISK_QUERY.value)

        # Decision query
        res2 = CopilotIntentClassifier.classify_query("Tôi nên giảm giá bao nhiêu % để giải phóng vốn SKU-001?")
        self.assertEqual(res2["code"], CopilotIntent.DECISION_QUERY.value)

        # Out of Scope query
        res3 = CopilotIntentClassifier.classify_query("Dự đoán giá cổ phiếu Apple hôm nay")
        self.assertEqual(res3["code"], CopilotIntent.OUT_OF_SCOPE.value)

    def test_tool_registry_contracts(self):
        """AC-03, AC-04: Verifies definition of 7 canonical Trusted DSS Tools."""
        tools = CopilotToolRegistry.TOOLS
        self.assertIn("get_risk_profile", tools)
        self.assertIn("get_risk_explanation", tools)
        self.assertIn("get_capital_exposure", tools)
        self.assertIn("get_inventory_aging", tools)
        self.assertIn("get_recovery_options", tools)
        self.assertIn("get_decision_recommendation", tools)
        self.assertIn("get_priority_actions", tools)
        self.assertEqual(len(tools), 7)

    def test_copilot_request_processing_and_llm_boundary(self):
        """AC-05, AC-06, AC-07, AC-09: Verifies full request pipeline, context building, evidence aggregation & auditability."""
        req = {
            "query": "Tôi nên xử lý SKU-001 như thế nào?",
            "sku_id": "SKU-001",
            "merchant_id": "merchant_test_01"
        }

        response = self.orchestrator.process_request(req)

        self.assertIn("response_id", response)
        self.assertEqual(response["intent"]["code"], CopilotIntent.DECISION_QUERY.value)
        self.assertGreater(len(response["evidence"]), 0)
        self.assertGreater(len(response["recommendations"]), 0)
        self.assertIn("M6_DECISION", response["sources"])

        # Verify LLM Boundary Enforcement Flag
        self.assertTrue(response["audit"]["llm_boundary_enforced"])
        self.assertGreater(response["audit"]["evidence_count"], 0)

    def test_out_of_scope_fallback_handling(self):
        """AC-08, AC-10: Verifies fallback handling for out-of-scope requests."""
        req = {
            "query": "Thời tiết hôm nay thế nào?",
            "merchant_id": "merchant_test_01"
        }

        response = self.orchestrator.process_request(req)
        self.assertEqual(response["intent"]["code"], CopilotIntent.OUT_OF_SCOPE.value)
        self.assertIn("ngoài phạm vi", response["answer"])
        self.assertEqual(len(response["evidence"]), 0)
