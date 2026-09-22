"""
Entity Extractor for Task M7-03 Intent Classification.
Module 07: AI Copilot & Merchant Workspace

Extracts domain entities (SKU ID, risk class, top_n ranking, category, capital thresholds).
"""

import re
from typing import Dict, Any, Optional


class EntityExtractor:
    """Extracts domain entities from natural language queries."""

    SKU_PATTERN = re.compile(r'(SKU[-_][A-Za-z0-9_-]+|SKU[0-9]+)', re.IGNORECASE)
    TOP_N_PATTERN = re.compile(r'(top\s*(\d+)|(\d+)\s*(sku|sản phẩm|mặt hàng))', re.IGNORECASE)
    CAPITAL_PATTERN = re.compile(r'(\d+)\s*(tỷ|b|triệu|m)', re.IGNORECASE)

    @classmethod
    def extract_entities(cls, query: str) -> Dict[str, Any]:
        if not query:
            return {}

        entities: Dict[str, Any] = {
            "sku_id": None,
            "product_name": None,
            "category": None,
            "risk_class": None,
            "top_n": None,
            "capital_threshold": None
        }

        # 1. Extract SKU ID
        sku_match = cls.SKU_PATTERN.search(query)
        if sku_match:
            entities["sku_id"] = sku_match.group(1).upper()

        # 2. Extract Risk Class
        q_upper = query.upper()
        if "CRITICAL" in q_upper:
            entities["risk_class"] = "CRITICAL"
        elif "HIGH" in q_upper:
            entities["risk_class"] = "HIGH_RISK"
        elif "MEDIUM" in q_upper:
            entities["risk_class"] = "MEDIUM_RISK"
        elif "LOW" in q_upper:
            entities["risk_class"] = "LOW_RISK"

        # 3. Extract Top N
        top_match = cls.TOP_N_PATTERN.search(query)
        if top_match:
            n_str = top_match.group(2) or top_match.group(3)
            if n_str:
                entities["top_n"] = int(n_str)

        # 4. Extract Category
        q_lower = query.lower()
        if "thời trang" in q_lower or "fashion" in q_lower:
            entities["category"] = "Fashion"
        elif "điện tử" in q_lower or "electronics" in q_lower:
            entities["category"] = "Electronics"
        elif "fmcg" in q_lower or "tiêu dùng" in q_lower:
            entities["category"] = "FMCG"

        return entities
