"""
Core Conversation Manager Engine for Task M7-09 Conversation & Memory.
Module 07: AI Copilot & Merchant Workspace

Coordinates multi-turn sessions, message history, entity tracking, pronoun reference resolution,
user preferences, context compression, tenant isolation, and audit logging.
"""

import uuid
import time
import logging
from typing import Dict, Any, List, Optional

from src.copilot.entity_tracker import EntityTracker
from src.copilot.reference_resolver import ReferenceResolver
from src.copilot.memory_manager import MemoryManager, TenantIsolationError
from src.copilot.conversation_summarizer import ConversationSummarizer

logger = logging.getLogger(__name__)


class ConversationManager:
    """Core Session & Memory Control Infrastructure for Module 07 Copilot."""

    def __init__(self):
        self.entity_tracker = EntityTracker()
        self.reference_resolver = ReferenceResolver()
        self.memory_manager = MemoryManager()
        self.summarizer = ConversationSummarizer()

        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[Dict[str, Any]]] = {}

    def create_conversation(
        self,
        tenant_id: str,
        merchant_id: str,
        user_id: str = "user_default"
    ) -> Dict[str, Any]:

        conv_id = f"CONV-{uuid.uuid4().hex[:8].upper()}"
        session = {
            "conversation_id": conv_id,
            "tenant_id": tenant_id,
            "merchant_id": merchant_id,
            "user_id": user_id,
            "status": "ACTIVE",
            "current_topic": "GENERAL",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        self._sessions[conv_id] = session
        self._messages[conv_id] = []
        return session

    def add_message(
        self,
        conversation_id: str,
        tenant_id: str,
        merchant_id: str,
        role: str,
        content: str
    ) -> Dict[str, Any]:

        session = self._sessions.get(conversation_id)
        if not session:
            session = self.create_conversation(tenant_id, merchant_id)
            conversation_id = session["conversation_id"]

        # Enforce Tenant Isolation
        self.memory_manager.validate_tenant_access(
            request_tenant_id=tenant_id,
            request_merchant_id=merchant_id,
            target_memory_tenant=session["tenant_id"],
            target_memory_merchant=session["merchant_id"]
        )

        # Update Entity Tracking & Reference Resolution
        if role == "user":
            ent_res = self.entity_tracker.extract_and_update(content)
            ref_res = self.reference_resolver.resolve_reference(content, ent_res)
            if ref_res["is_resolved"] and ref_res["resolved_sku"]:
                content += f" (Resolved SKU context: {ref_res['resolved_sku']})"

        msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
        msg = {
            "message_id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        self._messages[conversation_id].append(msg)
        session["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        return msg

    def get_context(
        self,
        conversation_id: str,
        tenant_id: str,
        merchant_id: str
    ) -> Dict[str, Any]:

        session = self._sessions.get(conversation_id)
        if not session:
            return {}

        self.memory_manager.validate_tenant_access(
            request_tenant_id=tenant_id,
            request_merchant_id=merchant_id,
            target_memory_tenant=session["tenant_id"],
            target_memory_merchant=session["merchant_id"]
        )

        msgs = self._messages.get(conversation_id, [])
        sum_res = self.summarizer.summarize_messages(msgs)
        memories = self.memory_manager.get_memories(tenant_id, merchant_id)

        active_ent = self.entity_tracker.extract_and_update("")

        return {
            "conversation_id": conversation_id,
            "current_topic": session["current_topic"],
            "active_entities": active_ent["all_entities"],
            "active_sku": active_ent["active_sku"],
            "active_decision_id": active_ent["active_decision_id"],
            "active_plan_id": active_ent["active_plan_id"],
            "summary": sum_res["summary"],
            "recent_messages": sum_res["recent_messages"],
            "user_memories": memories
        }
