"""
Decision Option Comparator for Task M7-07 Decision Copilot.
Module 07: AI Copilot & Merchant Workspace

Compares recommended actions against scenarios or alternative strategies side-by-side.
"""

from typing import Dict, Any, List


class DecisionComparator:
    """Performs side-by-side comparison of M6 decision options."""

    @classmethod
    def compare_options(
        cls,
        base_recommendation: Dict[str, Any],
        target_option: Dict[str, Any]
    ) -> Dict[str, Any]:

        base_rate = base_recommendation.get("discount_rate", 0.20)
        target_rate = target_option.get("discount_rate", 0.30)

        base_rec = base_recommendation.get("expected_recovery", 12000000.0)
        target_rec = target_option.get("expected_recovery", 14000000.0)

        diff_rec = round(target_rec - base_rec, 2)
        diff_rate_pct = round((target_rate - base_rate) * 100, 2)


        return {
            "option_a": {
                "label": f"Khuyến nghị chính thức ({base_rate*100:.0f}%)",
                "discount_rate": base_rate,
                "expected_recovery": base_rec
            },
            "option_b": {
                "label": f"Kịch bản mô phỏng ({target_rate*100:.0f}%)",
                "discount_rate": target_rate,
                "expected_recovery": target_rec
            },
            "tradeoff_analysis": {
                "additional_recovery": diff_rec,
                "discount_rate_diff_pct": diff_rate_pct,
                "summary": f"Mức chiết khấu tăng {diff_rate_pct:.0f}% giúp thu hồi thêm {diff_rec:,.0f} VNĐ vốn."
            }
        }
