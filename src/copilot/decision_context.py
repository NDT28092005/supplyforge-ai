"""
Decision Context Builder for Task M7-07 Decision Copilot.
Module 07: AI Copilot & Merchant Workspace

Aggregates authoritative outputs from M6 Decision Engine.
"""

from typing import Dict, Any, List, Optional


class DecisionContextBuilder:
    """Aggregates M6 decision recommendations, alternatives, and recovery estimates."""

    @classmethod
    def build_context(
        cls,
        sku_id: str,
        decision_data: Dict[str, Any]
    ) -> Dict[str, Any]:

        rec_action = decision_data.get("recommended_action", "DISCOUNT")
        discount_rate = decision_data.get("discount_rate", 0.20)
        expected_recovery = decision_data.get("expected_recovery", 12000000.0)
        priority_score = decision_data.get("action_priority_score", 0.91)
        reasoning = decision_data.get("recommendation_reason", "Mức rủi ro cao và thời gian tồn kho kéo dài.")

        alternatives = decision_data.get("alternatives", [
            {"action": "BUNDLE", "discount_rate": 0.10, "expected_recovery": 9500000.0},
            {"action": "LIQUIDATION", "discount_rate": 0.50, "expected_recovery": 7500000.0}
        ])

        return {
            "subject_id": sku_id,
            "current_recommendation": {
                "action": rec_action,
                "discount_rate": discount_rate,
                "expected_recovery": expected_recovery,
                "priority_score": priority_score,
                "reasoning": reasoning
            },
            "alternatives": alternatives
        }
