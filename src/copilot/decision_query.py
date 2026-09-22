"""
Decision Query Analyzer for Task M7-07 Decision Copilot.
Module 07: AI Copilot & Merchant Workspace

Parses natural-language decision queries into domain query types and simulation parameters.
"""

import re
from typing import Dict, Any, Optional


class DecisionQueryAnalyzer:
    """Parses decision-related queries into action intent types."""

    @classmethod
    def analyze_query(cls, query: str) -> Dict[str, Any]:
        q_lower = query.lower()

        # 1. Why / Explanation query
        if "tại sao" in q_lower or "lý do" in q_lower or "nguyên nhân" in q_lower:
            return {"query_type": "WHY_RECOMMENDATION", "simulated_rate": None}

        # 2. Comparison query (e.g. "Giảm giá 20% hay 30% tốt hơn?")
        if "so sánh" in q_lower or "hay" in q_lower or "tốt hơn" in q_lower:
            return {"query_type": "COMPARE_OPTIONS", "simulated_rate": None}

        # 3. Scenario / What-if query (e.g. "Nếu giảm giá 30% thì sao?")
        rate_match = re.search(r'(\d+)\s*%', query)
        if "nếu" in q_lower or "mô phỏng" in q_lower or rate_match:
            sim_rate = float(rate_match.group(1)) / 100.0 if rate_match else 0.25
            return {"query_type": "SCENARIO", "simulated_rate": sim_rate}


        # 4. Alternatives query
        if "phương án khác" in q_lower or "không giảm giá" in q_lower or "thay thế" in q_lower:
            return {"query_type": "ALTERNATIVE", "simulated_rate": None}

        # 5. Priority query
        if "ưu tiên" in q_lower or "xử lý trước" in q_lower:
            return {"query_type": "PRIORITY", "simulated_rate": None}

        # 6. Recovery query
        if "thu hồi" in q_lower or "giải phóng vốn" in q_lower:
            return {"query_type": "RECOVERY", "simulated_rate": None}

        # 7. Default Recommendation query
        return {"query_type": "RECOMMENDATION", "simulated_rate": None}
