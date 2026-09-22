"""
Risk & Capital Query Analyzer for Task M7-06 Risk & Capital Copilot.
Module 07: AI Copilot & Merchant Workspace

Parses natural-language queries into structured analysis types and filtering parameters.
"""

import re
from typing import Dict, Any, Optional


class RiskCapitalQueryAnalyzer:
    """Parses natural-language queries into domain analysis types and filter criteria."""

    @classmethod
    def analyze_query(cls, query: str, sku_id: Optional[str] = None) -> Dict[str, Any]:
        q_lower = query.lower()

        # 1. Decision Handoff Check (M6)
        if any(kw in q_lower for kw in ["nên làm gì", "xử lý", "giảm giá", "khuyến nghị", "phương án"]):
            return {
                "analysis_type": "M6_HANDOFF",
                "is_m6_handoff": True,
                "filters": {}
            }


        # 2. Ranking Check
        if "top" in q_lower or "xếp hạng" in q_lower or "nhiều nhất" in q_lower:
            return {
                "analysis_type": "RANKING",
                "is_m6_handoff": False,
                "filters": {"top_n": 10, "rank_by": "capital_exposure"}
            }

        # 3. Cross Analysis / Filtering Check (e.g. Critical + Aging > 180 + Capital > 10M)
        has_risk_cond = "critical" in q_lower or "rủi ro" in q_lower
        has_capital_cond = "vốn" in q_lower or "triệu" in q_lower
        has_aging_cond = "tồn" in q_lower or "ngày" in q_lower

        if has_risk_cond and (has_capital_cond or has_aging_cond):
            return {
                "analysis_type": "CROSS_ANALYSIS",
                "is_m6_handoff": False,
                "filters": {
                    "risk_class": "CRITICAL" if "critical" in q_lower else None,
                    "min_aging_days": 180 if "180" in q_lower else None,
                    "min_capital": 10000000.0 if "10 triệu" in q_lower or "10m" in q_lower else None
                }
            }

        # 4. Single SKU Check
        if sku_id or "sku" in q_lower:
            return {
                "analysis_type": "SINGLE_SKU",
                "is_m6_handoff": False,
                "filters": {"sku_id": sku_id}
            }

        # 5. Portfolio Summary Check
        return {
            "analysis_type": "RISK_PORTFOLIO" if "rủi ro" in q_lower else "CAPITAL_PORTFOLIO",
            "is_m6_handoff": False,
            "filters": {}
        }
