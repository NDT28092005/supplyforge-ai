"""
Fallback Response Generator for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Generates deterministic template-based responses when LLM generation or validation fails.
"""

from typing import Dict, Any


class FallbackResponseGenerator:
    """Generates 100% accurate, deterministic template responses from evidence."""

    @classmethod
    def generate_fallback(cls, evidence_package: Dict[str, Any]) -> str:
        subject = evidence_package.get("subject", {})
        sku_id = subject.get("id", "Sản phẩm")
        risk = evidence_package.get("risk", {})
        cap = evidence_package.get("capital", {})
        dec = evidence_package.get("decision", {})

        lines = [f"📌 **Báo cáo DSS chuẩn hóa cho {sku_id}**:"]

        if "risk_class" in risk:
            lines.append(f"- Mức rủi ro bán chậm (M3): **{risk.get('risk_class')}** (Score: {risk.get('risk_score')})")

        if "capital_exposure" in cap:
            lines.append(f"- Vốn bị phơi nhiễm (M5): **{cap.get('capital_exposure'):,.0f} VNĐ** (Số ngày tồn kho: {cap.get('aging_days', 0)} ngày)")

        if "recommended_action" in dec:
            lines.append(f"- Khuyến nghị hành động (M6): **{dec.get('recommended_action')}** (Mức giảm giá: {(dec.get('discount_rate', 0)*100):.0f}%)")
            lines.append(f"- Giá trị thu hồi dự kiến: **{dec.get('expected_recovery', 0):,.0f} VNĐ**")

        if len(lines) == 1:
            lines.append("- Hiện chưa có đủ dữ liệu bằng chứng xác thực cho đối tượng này.")

        return "\n".join(lines)
