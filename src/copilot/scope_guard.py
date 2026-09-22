"""
Scope Guard for Task M7-03 Intent Classification.
Module 07: AI Copilot & Merchant Workspace

Detects out-of-scope queries and prevents non-DSS requests from triggering system tools.
"""

import re
from typing import Dict, Any, List


class ScopeGuard:
    """Blocks queries outside SupplyForge AI domain scope."""

    BLOCKED_KEYWORDS = [
        "cổ phiếu", "thời tiết", "bóng đá", "thể thao", "giá vàng",
        "chứng khoán", "tiền điện tử", "bitcoin", "bài hát", "phim"
    ]

    @classmethod
    def check_scope(cls, query: str) -> Dict[str, Any]:
        if not query or not query.strip():
            return {"is_in_scope": False, "reason": "EMPTY_QUERY"}

        q_lower = query.lower()
        for kw in cls.BLOCKED_KEYWORDS:
            if kw in q_lower:
                return {
                    "is_in_scope": False,
                    "reason": f"OUT_OF_SCOPE_KEYWORD: {kw}"
                }

        return {"is_in_scope": True, "reason": "VALID_DSS_DOMAIN"}
