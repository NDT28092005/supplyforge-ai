"""
Context Resolver for Task M7-03 Intent Classification.
Module 07: AI Copilot & Merchant Workspace

Resolves conversation state and handles multi-turn entity inheritance (e.g. SKU inheritance across turns).
"""

from typing import Dict, Any, Optional


class ContextResolver:
    """Manages session context state across multi-turn chat conversations."""

    def __init__(self):
        self._session_store: Dict[str, Dict[str, Any]] = {}

    def resolve_context(
        self,
        session_id: str,
        extracted_entities: Dict[str, Any]
    ) -> Dict[str, Any]:

        session_ctx = self._session_store.get(session_id, {})

        initial_sku = extracted_entities.get("sku_id")
        current_sku = initial_sku
        inherited = False

        if not current_sku and session_ctx.get("last_sku_id"):
            current_sku = session_ctx.get("last_sku_id")
            extracted_entities["sku_id"] = current_sku
            inherited = True

        # Update session store
        if current_sku:
            session_ctx["last_sku_id"] = current_sku
        self._session_store[session_id] = session_ctx

        return {
            "subject_type": "SKU" if current_sku else "PORTFOLIO",
            "subject_id": current_sku or "ALL",
            "inherited": inherited
        }


    def clear_session(self, session_id: str) -> None:
        if session_id in self._session_store:
            del self._session_store[session_id]
