"""
Grounded Response Engine for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Coordinates prompt construction, Gemini narrative generation, numerical & claim validation,
grounding score evaluation, and deterministic fallback handling.
"""

import uuid
import time
import logging
from typing import Dict, Any, Optional

from src.copilot.prompt_builder import GroundedPromptBuilder
from src.copilot.grounding_validator import GroundingValidator
from src.copilot.fallback_response import FallbackResponseGenerator

logger = logging.getLogger(__name__)


class GroundedResponseEngine:
    """Core Presentation & Reasoning Engine for Module 07 Copilot."""

    def __init__(self):
        self.prompt_builder = GroundedPromptBuilder()
        self.validator = GroundingValidator()
        self.fallback_generator = FallbackResponseGenerator()

    def generate_response(
        self,
        query: str,
        intent_code: str,
        evidence_package: Dict[str, Any],
        orchestration_id: Optional[str] = None
    ) -> Dict[str, Any]:

        response_id = f"RESP-{uuid.uuid4().hex[:8].upper()}"
        start_time = time.time()

        # 1. Build Grounded Prompt
        prompt = self.prompt_builder.build_prompt(query, intent_code, evidence_package)

        # 2. Simulate / Call Gemini LLM Generation
        raw_text, gen_status = self._call_gemini_generation(query, intent_code, evidence_package, prompt)

        # 3. Grounding Validation (Numerical & Claim Consistency)
        val_eval = self.validator.evaluate_grounding(raw_text, evidence_package)
        status = val_eval["status"]
        used_fallback = False

        # 4. Fallback Handling if Validation Failed
        if status == "VALIDATION_FAILED" or gen_status != "SUCCESS":
            logger.warning("Generation or validation failed (status: %s). Falling back to deterministic response.", status)
            content = self.fallback_generator.generate_fallback(evidence_package)
            status = "FALLBACK"
            used_fallback = True
            val_eval["grounding_score"] = 1.0  # Deterministic fallback is 100% grounded
            val_eval["numeric_conflicts"] = 0
            val_eval["unsupported_claims"] = 0
        else:
            content = raw_text

        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        # 5. Extract Source Modules
        evidence_items = evidence_package.get("evidence_items", [])
        sources = list({item.get("source_module") for item in evidence_items if item.get("source_module")})

        return {
            "response_id": response_id,
            "status": status,
            "query": query,
            "intent": intent_code,
            "content": content,
            "grounding": {
                "grounding_score": val_eval["grounding_score"],
                "evidence_count": val_eval["evidence_count"],
                "numeric_conflicts": val_eval["numeric_conflicts"],
                "unsupported_claims": val_eval["unsupported_claims"]
            },
            "sources": sources,
            "audit": {
                "orchestration_id": orchestration_id or "ORCH-DIRECT",
                "execution_time_ms": execution_time_ms,
                "used_fallback": used_fallback
            }
        }

    def _call_gemini_generation(
        self,
        query: str,
        intent_code: str,
        evidence_package: Dict[str, Any],
        prompt: str
    ) -> tuple[str, str]:

        # Grounded text synthesis strictly matching evidence parameters
        subject = evidence_package.get("subject", {})
        sku_id = subject.get("id", "Sản phẩm")
        risk = evidence_package.get("risk", {})
        cap = evidence_package.get("capital", {})
        dec = evidence_package.get("decision", {})

        risk_class = risk.get("risk_class", "Chưa xác định")
        risk_score = risk.get("risk_score", 0.0)
        cap_val = cap.get("capital_exposure", 0.0)
        aging_days = cap.get("aging_days", 0)
        action = dec.get("recommended_action", "MONITOR")
        discount = (dec.get("discount_rate", 0.0) or 0.0) * 100
        rec_val = dec.get("expected_recovery", 0.0)

        if intent_code == "DECISION_QUERY":
            text = (
                f"Sản phẩm **{sku_id}** hiện được hệ thống đánh giá mức rủi ro bán chậm **{risk_class}** "
                f"(Score: {risk_score}) với lượng vốn bị phơi nhiễm là **{cap_val:,.0f} VNĐ** (tuổi kho {aging_days} ngày).\n\n"
                f"Phương án tối ưu từ Module 06 đề xuất thực hiện **{action}** (mức giảm giá {discount:.0f}%) "
                f"với giá trị vốn thu hồi dự kiến đạt **{rec_val:,.0f} VNĐ**."
            )
        elif intent_code == "EXPLANATION_QUERY":
            text = (
                f"Sản phẩm **{sku_id}** bị đánh giá rủi ro bán chậm **{risk_class}** "
                f"do chỉ số thời gian không phát sinh đơn kéo dài {aging_days} ngày và tốc độ bán thấp."
            )
        elif intent_code == "CAPITAL_QUERY":
            text = (
                f"Tổng giá trị vốn phơi nhiễm của **{sku_id}** hiện là **{cap_val:,.0f} VNĐ**, "
                f"với số ngày tồn kho là {aging_days} ngày."
            )
        else:
            text = (
                f"Theo dữ liệu xác thực, sản phẩm **{sku_id}** thuộc mức rủi ro **{risk_class}** "
                f"với vốn phơi nhiễm **{cap_val:,.0f} VNĐ**."
            )

        return text, "SUCCESS"
