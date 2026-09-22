"""
Evidence Assembler for Task M7-02 Context Retrieval.
Module 07: AI Copilot & Merchant Workspace

Assembles validated raw provider contexts into structured EvidencePackage JSON payloads.
"""

import uuid
from typing import Dict, Any, List, Optional


class EvidenceAssembler:
    """Filters raw provider data and compiles structured EvidencePackage JSON payloads."""

    @classmethod
    def assemble_evidence_package(
        cls,
        merchant_id: str,
        dataset_version: str,
        scope: str,
        target_id: Optional[str],
        raw_contexts: List[Dict[str, Any]],
        validation_summary: Dict[str, Any]
    ) -> Dict[str, Any]:

        context_id = f"CTX-{uuid.uuid4().hex[:8].upper()}"

        risk_ctx = {}
        exp_ctx = {}
        cap_ctx = {}
        dec_ctx = {}
        evidence_items = []

        for ctx in raw_contexts:
            source = ctx.get("source_module")
            data = ctx.get("data", {})

            if source == "M3_RISK":
                risk_ctx = data
                if "risk_class" in data:
                    evidence_items.append({
                        "metric": "Mức Rủi Ro (Risk Class)",
                        "value": f"{data.get('risk_class')} (Score: {data.get('risk_score')})",
                        "source_module": "M3_RISK",
                        "interpretation": f"Sản phẩm được M3 xếp vào nhóm rủi ro bán chậm {data.get('risk_class')}."
                    })
            elif source == "M4_EXPLAINABILITY":
                exp_ctx = data
                if "top_features" in data and len(data["top_features"]) > 0:
                    top_f = data["top_features"][0]
                    evidence_items.append({
                        "metric": "Yếu Tố Ảnh Hưởng Chính (SHAP)",
                        "value": f"{top_f.get('feature')} (SHAP: {top_f.get('shap_value')})",
                        "source_module": "M4_EXPLAINABILITY",
                        "interpretation": top_f.get("interpretation", "Yếu tố rủi ro chính.")
                    })
            elif source == "M5_CAPITAL":
                cap_ctx = data
                if "capital_exposure" in data:
                    evidence_items.append({
                        "metric": "Vốn Phơi Nhiễm (Capital Exposure)",
                        "value": f"{data.get('capital_exposure'):,.0f} VND",
                        "source_module": "M5_CAPITAL",
                        "interpretation": f"Vốn đang bị khóa trong kho với số ngày tồn kho {data.get('aging_days', 0)} ngày."
                    })
            elif source == "M6_DECISION":
                dec_ctx = data
                if "recommended_action" in data:
                    evidence_items.append({
                        "metric": "Khuyến Nghị Hành Động",
                        "value": f"{data.get('recommended_action')} ({data.get('discount_rate', 0)*100:.0f}%)",
                        "source_module": "M6_DECISION",
                        "interpretation": f"Khuyến nghị tối ưu đạt giá trị thu hồi dự kiến {data.get('expected_recovery', 0):,.0f} VND."
                    })

        return {
            "context_id": context_id,
            "merchant_id": merchant_id,
            "dataset_version": dataset_version,
            "readiness_status": "READY",
            "subject": {
                "type": scope,
                "id": target_id or "PORTFOLIO"
            },
            "risk": risk_ctx,
            "explanation": exp_ctx,
            "capital": cap_ctx,
            "decision": dec_ctx,
            "evidence_items": evidence_items,
            "validation_summary": validation_summary
        }
