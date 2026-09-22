"""
Intent Validator for Task M7-03 Intent Classification.
Module 07: AI Copilot & Merchant Workspace

Validates intent taxonomy compliance, confidence thresholds, and handles ambiguity.
"""

from typing import Dict, Any, List

ALLOWED_INTENTS = {
    "RISK_QUERY", "EXPLANATION_QUERY", "CAPITAL_QUERY", "AGING_QUERY",
    "DECISION_QUERY", "RECOVERY_QUERY", "ACTION_QUERY", "COMPARISON_QUERY",
    "SUMMARY_QUERY", "SKU_QUERY", "DATA_QUALITY_QUERY", "GENERAL_HELP",
    "AMBIGUOUS_INTENT", "OUT_OF_SCOPE"
}


class IntentValidator:
    """Validates classification confidence and taxonomy schema compliance."""

    CONFIDENCE_THRESHOLD = 0.60

    @classmethod
    def validate_classification(cls, primary_intent: str, confidence: float) -> Dict[str, Any]:
        if primary_intent not in ALLOWED_INTENTS:
            return {
                "is_valid": False,
                "validated_intent": "AMBIGUOUS_INTENT",
                "confidence": 0.0,
                "is_ambiguous": True,
                "clarification_prompt": "Hệ thống chưa xác định rõ ý định của bạn. Bạn muốn tra cứu Rủi ro, Vốn bị đóng băng, hay Khuyến nghị hành động?"
            }

        if confidence < cls.CONFIDENCE_THRESHOLD:
            return {
                "is_valid": True,
                "validated_intent": "AMBIGUOUS_INTENT",
                "confidence": confidence,
                "is_ambiguous": True,
                "clarification_prompt": "Câu hỏi của bạn có thể bao gồm nhiều thông tin. Bạn muốn xem Rủi ro bán chậm, Vốn đóng băng, hay Khuyến nghị giải phóng vốn?"
            }

        return {
            "is_valid": True,
            "validated_intent": primary_intent,
            "confidence": confidence,
            "is_ambiguous": False,
            "clarification_prompt": None
        }
