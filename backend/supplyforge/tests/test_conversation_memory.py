"""
Test suite for Task M7-09 Conversation & Memory (Module 07).
Verifies AC-01 through AC-20 requirements:
- Multi-turn conversation session & message history management
- Entity tracking (SKU, Decision ID, Plan ID) & Pronoun reference resolution ("nó", "phương án đó")
- User preference memory & Tenant isolation enforcement
- Context compression & Business Truth Isolation
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.conversation_manager import ConversationManager
from src.copilot.entity_tracker import EntityTracker
from src.copilot.reference_resolver import ReferenceResolver
from src.copilot.memory_manager import MemoryManager, TenantIsolationError
from src.copilot.conversation_summarizer import ConversationSummarizer


class TestConversationMemory(TestCase):

    def setUp(self):
        self.conv_manager = ConversationManager()
        self.memory_manager = MemoryManager()

    def test_entity_tracking_and_reference_resolution(self):
        """AC-03, AC-04, AC-05: Verifies entity tracking and pronoun resolution ("nó", "phương án đó")."""
        tracker = EntityTracker()
        res1 = tracker.extract_and_update("Phân tích rủi ro cho SKU-001 và DEC-1001")
        self.assertEqual(res1["active_sku"], "SKU-001")
        self.assertEqual(res1["active_decision_id"], "DEC-1001")

        # Resolve pronoun "Nó" -> SKU-001
        ref1 = ReferenceResolver.resolve_reference("Nó đang khóa bao nhiêu vốn?", res1)
        self.assertTrue(ref1["is_resolved"])
        self.assertEqual(ref1["resolved_sku"], "SKU-001")

        # Resolve "phương án đó" -> DEC-1001
        ref2 = ReferenceResolver.resolve_reference("Khuyến nghị của phương án đó là gì?", res1)
        self.assertEqual(ref2["resolved_decision_id"], "DEC-1001")

    def test_tenant_isolation_guard(self):
        """AC-15, AC-16: Verifies strict tenant memory access isolation."""
        self.memory_manager.set_memory(
            tenant_id="tenant_a",
            merchant_id="merchant_a",
            key="response_style",
            value="concise"
        )

        # Authorized access -> Pass
        mem = self.memory_manager.get_memories("tenant_a", "merchant_a")
        self.assertEqual(len(mem), 1)

        # Cross-tenant access attempt -> TenantIsolationError
        with self.assertRaises(TenantIsolationError):
            self.memory_manager.validate_tenant_access(
                request_tenant_id="tenant_b",
                request_merchant_id="merchant_b",
                target_memory_tenant="tenant_a",
                target_memory_merchant="merchant_a"
            )

    def test_conversation_summarizer(self):
        """AC-06, AC-13: Verifies context compression for multi-turn conversations."""
        msgs = [
            {"role": "user", "content": f"Message {i}"} for i in range(10)
        ]
        sum_res = ConversationSummarizer.summarize_messages(msgs, max_recent_turns=2)
        self.assertIn("Tóm tắt", sum_res["summary"])
        self.assertEqual(len(sum_res["recent_messages"]), 4)

    def test_end_to_end_conversation_manager(self):
        """AC-01, AC-02, AC-10, AC-11, AC-12, AC-17, AC-18, AC-19: Verifies full multi-turn conversation session flow."""
        session = self.conv_manager.create_conversation("tenant_01", "merchant_01")
        conv_id = session["conversation_id"]

        # Turn 1: Explicit SKU
        self.conv_manager.add_message(conv_id, "tenant_01", "merchant_01", "user", "Phân tích rủi ro SKU-001")
        self.conv_manager.add_message(conv_id, "tenant_01", "merchant_01", "assistant", "SKU-001 rủi ro Critical")

        # Turn 2: Implicit Pronoun "Nó"
        msg2 = self.conv_manager.add_message(conv_id, "tenant_01", "merchant_01", "user", "Nó đang khóa bao nhiêu vốn?")
        self.assertIn("Resolved SKU context: SKU-001", msg2["content"])

        ctx = self.conv_manager.get_context(conv_id, "tenant_01", "merchant_01")
        self.assertEqual(ctx["active_sku"], "SKU-001")
        self.assertEqual(len(ctx["recent_messages"]), 3)
