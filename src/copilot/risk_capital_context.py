"""
Risk & Capital Context Builder for Task M7-06 Risk & Capital Copilot.
Module 07: AI Copilot & Merchant Workspace

Aggregates authoritative metrics from M3 (Risk), M4 (Explanation), and M5 (Capital & Aging).
"""

from typing import Dict, Any, List, Optional


class RiskCapitalContextBuilder:
    """Aggregates authoritative M3, M4, M5 metrics without recalculating business logic."""

    @classmethod
    def build_sku_context(
        cls,
        sku_id: str,
        risk_profile: Dict[str, Any],
        capital_profile: Dict[str, Any],
        explanation_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        risk_class = risk_profile.get("risk_class", "UNKNOWN")
        risk_prob = risk_profile.get("risk_score", 0.0)
        capital_exp = capital_profile.get("capital_exposure", 0.0)
        aging_days = capital_profile.get("aging_days", 0)

        top_driver = None
        if explanation_profile and "top_signals" in explanation_profile and explanation_profile["top_signals"]:
            top_driver = explanation_profile["top_signals"][0].get("feature", "forecast_demand")

        return {
            "sku_id": sku_id,
            "risk": {
                "risk_class": risk_class,
                "risk_probability": risk_prob
            },
            "capital": {
                "capital_exposure": capital_exp,
                "aging_days": aging_days
            },
            "explanation": {
                "top_driver": top_driver
            },
            "relationship_summary": cls._build_relationship_summary(risk_class, capital_exp, aging_days)
        }

    @classmethod
    def _build_relationship_summary(cls, risk_class: str, capital: float, aging: int) -> str:
        if risk_class == "CRITICAL" and capital >= 10000000:
            return "SKU thuộc nhóm rủi ro Critical đồng thời chiếm dụng quy mô vốn lớn (>10M VNĐ)."
        elif risk_class == "CRITICAL":
            return "SKU thuộc nhóm rủi ro Critical nhưng quy mô vốn phơi nhiễm nhỏ."
        elif capital >= 10000000:
            return "SKU đang đóng băng lượng vốn đáng kể nhưng mức rủi ro hiện tại chưa phải Critical."
        return "SKU ở mức rủi ro và quy mô vốn bình thường."
