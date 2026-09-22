"""
Reference Resolver for Task M7-09 Conversation & Memory.
Module 07: AI Copilot & Merchant Workspace

Resolves pronouns ("nó", "cái này", "phương án đó") to active entities or active decision IDs.
"""

from typing import Dict, Any, Optional


class ReferenceResolver:
    """Resolves implicit pronoun references to explicit domain entities."""

    PRONOUNS = ["nó", "sản phẩm này", "cái này", "mặt hàng này"]
    DECISION_REFS = ["phương án đó", "phương án đầu tiên", "khuyến nghị này", "quyết định đó"]

    @classmethod
    def resolve_reference(
        cls,
        text: str,
        active_entities: Dict[str, Any]
    ) -> Dict[str, Any]:

        t_lower = text.lower()
        resolved_sku = None
        resolved_decision = None

        if any(p in t_lower for p in cls.PRONOUNS):
            resolved_sku = active_entities.get("active_sku")

        if any(d in t_lower for d in cls.DECISION_REFS):
            resolved_decision = active_entities.get("active_decision_id")

        return {
            "resolved_sku": resolved_sku,
            "resolved_decision_id": resolved_decision,
            "is_resolved": resolved_sku is not None or resolved_decision is not None
        }
