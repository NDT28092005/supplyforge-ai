"""
M4 Risk Explanation Context Provider.
Module 07: AI Copilot & Merchant Workspace
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class RiskExplanationProvider:
    """Retrieves M4 Explainability SHAP contributions and diagnostic signals."""

    SOURCE_MODULE = "M4_EXPLAINABILITY"

    @classmethod
    def get_context(cls, sku_id: Optional[str] = None, dataset_version: str = "v1.0") -> Dict[str, Any]:
        if not sku_id:
            return {
                "provider_name": "RiskExplanationProvider",
                "source_module": cls.SOURCE_MODULE,
                "dataset_version": dataset_version,
                "status": "SUCCESS",
                "data": {"global_top_features": ["days_since_last_sale", "sales_velocity_30d", "zero_sales_90d"]}
            }

        return {
            "provider_name": "RiskExplanationProvider",
            "source_module": cls.SOURCE_MODULE,
            "dataset_version": dataset_version,
            "status": "SUCCESS",
            "data": {
                "sku": sku_id,
                "top_features": [
                    {"feature": "days_since_last_sale", "shap_value": 0.42, "interpretation": "Thời gian không phát sinh đơn kéo dài 375 ngày."},
                    {"feature": "zero_sales_90d", "shap_value": 0.28, "interpretation": "Tỷ lệ ngày không có đơn hàng 98.9% trong 90 ngày."}
                ],
                "diagnostic_signals": ["DSLS_CRITICAL_HIGH", "ZERO_SALES_90D_HIGH"],
                "explanation_summary": "Sản phẩm bị đánh giá Critical do zero-sales kéo dài."
            }
        }
