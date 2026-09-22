"""
Memory Manager for Task M7-09 Conversation & Memory.
Module 07: AI Copilot & Merchant Workspace

Manages user preferences and session memory with strict tenant isolation.
"""

import uuid
from typing import Dict, Any, List, Optional


class TenantIsolationError(Exception):
    pass


class MemoryManager:
    """Manages short-term working memory and persistent user preferences with tenant isolation."""

    def __init__(self):
        self._memory_store: Dict[str, List[Dict[str, Any]]] = {}

    def set_memory(
        self,
        tenant_id: str,
        merchant_id: str,
        key: str,
        value: Any,
        memory_type: str = "USER_PREFERENCE",
        source: str = "USER_EXPLICIT"
    ) -> Dict[str, Any]:

        store_key = f"{tenant_id}:{merchant_id}"
        if store_key not in self._memory_store:
            self._memory_store[store_key] = []

        memory_id = f"MEM-{uuid.uuid4().hex[:8].upper()}"
        item = {
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "merchant_id": merchant_id,
            "memory_type": memory_type,
            "key": key,
            "value": value,
            "source": source
        }

        # Update existing key or append
        self._memory_store[store_key] = [m for m in self._memory_store[store_key] if m["key"] != key]
        self._memory_store[store_key].append(item)

        return item

    def get_memories(
        self,
        tenant_id: str,
        merchant_id: str
    ) -> List[Dict[str, Any]]:

        store_key = f"{tenant_id}:{merchant_id}"
        return self._memory_store.get(store_key, [])

    def validate_tenant_access(
        self,
        request_tenant_id: str,
        request_merchant_id: str,
        target_memory_tenant: str,
        target_memory_merchant: str
    ) -> bool:

        if request_tenant_id != target_memory_tenant or request_merchant_id != target_memory_merchant:
            raise TenantIsolationError("Tenant Access Violation: Attempted to access memory belonging to another tenant/merchant.")
        return True
