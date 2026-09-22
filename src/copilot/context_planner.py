"""
Context Planner for Task M7-02 Context Retrieval.
Module 07: AI Copilot & Merchant Workspace

Maps query intents to context requirements (scope, target SKU, required modules & required fields).
"""

from typing import Dict, Any, Optional, List


class ContextPlanner:
    """Plans minimal required context based on query intent and parameters."""

    @classmethod
    def create_plan(
        cls,
        intent_code: str,
        sku_id: Optional[str] = None,
        target_id: Optional[str] = None
    ) -> Dict[str, Any]:
        scope = "SKU" if sku_id else ("PORTFOLIO" if not target_id else "CATEGORY")

        if intent_code == "RISK_QUERY":
            return {
                "query_intent": intent_code,
                "scope": scope,
                "target_id": sku_id or target_id,
                "required_modules": ["M3_RISK", "M5_CAPITAL"],
                "required_fields": ["sku", "risk_class", "risk_score", "risk_probability", "aging_days"]
            }
        elif intent_code == "EXPLAINABILITY_QUERY":
            return {
                "query_intent": intent_code,
                "scope": scope,
                "target_id": sku_id or target_id,
                "required_modules": ["M3_RISK", "M4_EXPLAINABILITY"],
                "required_fields": ["sku", "risk_class", "top_features", "diagnostic_signals", "explanation_summary"]
            }
        elif intent_code == "CAPITAL_QUERY":
            return {
                "query_intent": intent_code,
                "scope": scope,
                "target_id": sku_id or target_id,
                "required_modules": ["M5_CAPITAL"],
                "required_fields": ["sku", "capital_exposure", "risk_weighted_exposure", "aging_days", "aging_class"]
            }
        elif intent_code == "DECISION_QUERY":
            return {
                "query_intent": intent_code,
                "scope": scope,
                "target_id": sku_id or target_id,
                "required_modules": ["M3_RISK", "M5_CAPITAL", "M6_DECISION"],
                "required_fields": ["sku", "risk_class", "capital_exposure", "recommended_action", "discount_rate", "expected_recovery", "priority_tier"]
            }
        else:
            return {
                "query_intent": intent_code,
                "scope": "PORTFOLIO",
                "target_id": None,
                "required_modules": ["M3_RISK", "M5_CAPITAL", "M6_DECISION"],
                "required_fields": ["at_risk_sku_count", "critical_count", "total_capital_exposure", "expected_portfolio_recovery"]
            }

