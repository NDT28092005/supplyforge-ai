"""
Plan Versioning Manager for Task M7-08 Action Planning.
Module 07: AI Copilot & Merchant Workspace

Tracks plan versioning (v1, v2) linked to decision versions for auditability.
"""

from typing import Dict, Any


class PlanVersioningManager:
    """Manages audit versioning for Action Plans."""

    @classmethod
    def get_next_version(cls, current_version: str = "v1.0") -> str:
        try:
            v_num = float(current_version.replace("v", ""))
            next_v = v_num + 1.0
            return f"v{next_v:.1f}"
        except Exception:
            return "v2.0"
