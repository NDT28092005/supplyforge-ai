"""
Claim Validator for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Detects unsupported claims and hallucinated assertions in generated text.
"""

from typing import Dict, Any, List


class ClaimValidator:
    """Detects unsupported assertions and missing evidence claims."""

    UNSUPPORTED_KEYWORDS = [
        "chắc chắn 100%", "cam kết không bán được", "hoàn toàn phá sản",
        "tự động thay đổi giá", "đã xóa dữ liệu"
    ]

    @classmethod
    def validate_claims(
        cls,
        generated_text: str,
        evidence_package: Dict[str, Any]
    ) -> Dict[str, Any]:

        if not generated_text:
            return {"unsupported_claims_count": 0, "unsupported_claims": []}

        unsupported = []
        g_lower = generated_text.lower()

        for kw in cls.UNSUPPORTED_KEYWORDS:
            if kw in g_lower:
                unsupported.append(kw)

        # Check for unsupported discount rate claims when decision evidence is null
        dec = evidence_package.get("decision", {})
        if not dec or not dec.get("recommended_action"):
            if "khuyên bạn giảm giá" in g_lower or "áp dụng giảm giá" in g_lower:
                unsupported.append("UNSUPPORTED_DISCOUNT_RECOMMENDATION")

        return {
            "unsupported_claims_count": len(unsupported),
            "unsupported_claims": unsupported
        }
