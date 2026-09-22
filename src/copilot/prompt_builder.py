"""
Grounded Prompt Builder for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Formats system grounding rules and trusted evidence into bounded Gemini LLM prompts.
"""

from typing import Dict, Any, List


class GroundedPromptBuilder:
    """Builds bounded Gemini prompts with strict grounding rules."""

    @classmethod
    def build_prompt(
        cls,
        query: str,
        intent_code: str,
        evidence_package: Dict[str, Any]
    ) -> str:

        subject = evidence_package.get("subject", {})
        evidence_items = evidence_package.get("evidence_items", [])

        evidence_lines = []
        for item in evidence_items:
            evidence_lines.append(f"- [{item['source_module']}] {item['metric']}: {item['value']} ({item['interpretation']})")

        if not evidence_lines:
            evidence_lines.append("- (Không tìm thấy dữ liệu bằng chứng khả dụng cho truy vấn này).")

        evidence_text = "\n".join(evidence_lines)

        return (
            f"[SYSTEM INSTRUCTION]\n"
            f"Bạn là AI Copilot của SupplyForge AI. Bạn CHỈ ĐƯỢC PHÉP dùng thông tin từ TRUSTED EVIDENCE bên dưới.\n"
            f"Cấm tự tạo số liệu, cấm tự tính toán lại. Đảm bảo khớp số liệu 100%.\n\n"
            f"[USER QUERY]: {query}\n"
            f"[INTENT]: {intent_code}\n"
            f"[SUBJECT]: {subject.get('type')} {subject.get('id')}\n\n"
            f"[TRUSTED EVIDENCE FROM M3-M6 DSS ENGINES]:\n"
            f"{evidence_text}\n\n"
            f"[RESPONSE INSTRUCTION]: Hãy trả lời câu hỏi của Merchant bằng tiếng Việt một cách trực diện, chuyên nghiệp, chính xác."
        )
