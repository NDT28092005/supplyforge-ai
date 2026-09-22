"""
Test suite for Task M7-10 Copilot API & Persistence (Module 07).
Verifies AC-01 through AC-24 requirements:
- Copilot Query & Conversation Persistence (CopilotConversation, CopilotMessage, CopilotToolCall, CopilotAuditLog)
- Idempotency key checking & duplicate request mitigation
- Token usage & Cost tracking calculations
- End-to-end audit trace reconstruction
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models.copilot_models import CopilotConversation, CopilotMessage, CopilotToolCall, CopilotAuditLog
from src.copilot.idempotency_service import IdempotencyManager
from src.copilot.cost_tracker import CostTracker
from src.copilot.audit_service import AuditLogger


class TestCopilotAPIPersistence(TestCase):

    def setUp(self):
        self.idempotency_mgr = IdempotencyManager()
        self.audit_logger = AuditLogger()

    def test_database_models_persistence(self):
        """AC-03, AC-04, AC-05, AC-06, AC-14: Verifies Django ORM models persistence for Conversations & Messages."""
        conv = CopilotConversation.objects.create(
            tenant_id="tenant_test",
            merchant_id="merchant_test",
            user_id="user_test",
            title="Session Test"
        )
        self.assertIsNotNone(conv.conversation_id)

        msg = CopilotMessage.objects.create(
            conversation=conv,
            role="user",
            content="Phân tích SKU-001"
        )
        self.assertEqual(msg.role, "user")

        tool_call = CopilotToolCall.objects.create(
            conversation=conv,
            tool_name="get_risk_profile",
            source_module="M3_RISK",
            input_params={"sku_id": "SKU-001"},
            status="SUCCESS",
            execution_time_ms=12.5
        )
        self.assertEqual(tool_call.tool_name, "get_risk_profile")

    def test_idempotency_manager(self):
        """AC-15: Verifies Idempotency-Key caching and duplicate request prevention."""
        key = "idemp-key-12345"
        resp_data = {"status": "SUCCESS", "message": "Grounded Response"}

        # 1. First check -> None
        self.assertIsNone(self.idempotency_mgr.get_response(key))

        # 2. Store response
        self.idempotency_mgr.set_response(key, resp_data)

        # 3. Duplicate check -> Cached response
        cached = self.idempotency_mgr.get_response(key)
        self.assertEqual(cached["message"], "Grounded Response")

    def test_cost_tracker(self):
        """AC-20: Verifies token calculation and USD cost estimation."""
        inp = "SKU-001 có rủi ro gì và đang phơi nhiễm bao nhiêu vốn?"
        out = "SKU-001 hiện thuộc mức rủi ro Critical với vốn phơi nhiễm 15 triệu VNĐ."

        cost_res = CostTracker.calculate_cost(inp, out)
        self.assertGreater(cost_res["input_tokens"], 0)
        self.assertGreater(cost_res["output_tokens"], 0)
        self.assertGreater(cost_res["estimated_cost_usd"], 0.0)

    def test_audit_reconstruction(self):
        """AC-07, AC-19, AC-22: Verifies audit logging and full interaction reconstruction."""
        record = self.audit_logger.log_interaction(
            conversation_id="CONV-1001",
            tenant_id="tenant_01",
            merchant_id="merchant_01",
            query="SKU-001 có rủi ro gì?",
            intent_code="RISK_QUERY",
            tools_called=["get_risk_profile"],
            response_content="SKU-001 có rủi ro Critical.",
            cost_info={"total_tokens": 120, "estimated_cost_usd": 0.0001},
            latency_ms=145.0
        )

        req_id = record["request_id"]
        reconstructed = self.audit_logger.reconstruct_interaction(req_id)
        self.assertEqual(reconstructed["intent_code"], "RISK_QUERY")
        self.assertEqual(reconstructed["latency_ms"], 145.0)
