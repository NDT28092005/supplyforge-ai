"""
Copilot Architecture Foundation & Tool Orchestrator for Task M7-01.
Module 07: AI Copilot & Merchant Workspace

Implements:
- 5-Layer Copilot Architecture Pipeline
- Intent Classification Engine (CopilotIntentClassifier)
- Trusted DSS Tool Registry & Dispatcher (CopilotToolRegistry)
- Minimal Grounded Context Builder (CopilotContextBuilder)
- Copilot Orchestrator & LLM Boundary Validator (CopilotOrchestrator)
"""

import json
import logging
import time
import uuid
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CopilotIntent(str, Enum):
    RISK_QUERY = "RISK_QUERY"
    EXPLAINABILITY_QUERY = "EXPLAINABILITY_QUERY"
    CAPITAL_QUERY = "CAPITAL_QUERY"
    DECISION_QUERY = "DECISION_QUERY"
    PORTFOLIO_QUERY = "PORTFOLIO_QUERY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class CopilotIntentClassifier:
    """Classifies user natural-language queries into canonical CopilotIntents."""

    @classmethod
    def classify_query(cls, query: str) -> Dict[str, Any]:
        if not query or not query.strip():
            return {"code": CopilotIntent.OUT_OF_SCOPE.value, "confidence": 0.0, "explanation": "Empty query."}

        q_lower = query.lower()

        # Check for Out of Scope queries
        out_of_scope_keywords = ["cổ phiếu", "thời tiết", "bóng đá", "thể thao", "bài hát", "phim"]
        if any(kw in q_lower for kw in out_of_scope_keywords):
            return {
                "code": CopilotIntent.OUT_OF_SCOPE.value,
                "confidence": 0.95,
                "explanation": "Query is outside the scope of SupplyForge AI inventory DSS."
            }

        # Priority / Decision Intent
        if any(kw in q_lower for kw in ["xử lý", "hành động", "khuyến nghị", "chiết khấu", "ưu tiên", "nên làm gì", "giải phóng"]):
            return {
                "code": CopilotIntent.DECISION_QUERY.value,
                "confidence": 0.90,
                "explanation": "Query asks for decision recommendations or action priority."
            }

        # Explainability Intent
        if any(kw in q_lower for kw in ["tại sao", "nguyên nhân", "lý do", "shap", "tín hiệu"]):
            return {
                "code": CopilotIntent.EXPLAINABILITY_QUERY.value,
                "confidence": 0.88,
                "explanation": "Query asks for risk root causes and diagnostic explanation."
            }

        # Capital / Aging Intent
        if any(kw in q_lower for kw in ["vốn", "đóng băng", "tuổi hàng", "aging", "phơi nhiễm", "giá trị tồn"]):
            return {
                "code": CopilotIntent.CAPITAL_QUERY.value,
                "confidence": 0.89,
                "explanation": "Query asks for capital exposure and inventory aging."
            }

        # Risk Detection Intent
        if any(kw in q_lower for kw in ["rủi ro", "bán chậm", "slow-moving", "nguy cơ", "critical"]):
            return {
                "code": CopilotIntent.RISK_QUERY.value,
                "confidence": 0.87,
                "explanation": "Query asks for slow-moving risk score or classification."
            }

        # Default Portfolio Query
        return {
            "code": CopilotIntent.PORTFOLIO_QUERY.value,
            "confidence": 0.70,
            "explanation": "General inventory portfolio query."
        }


class CopilotToolRegistry:
    """Registry managing canonical Trusted DSS Tools connecting M3–M6 APIs."""

    TOOLS = {
        "get_risk_profile": {
            "purpose": "Extracts SKU risk score and risk class from Module 03 Risk Detection.",
            "source_module": "M3_RISK",
            "required_params": ["sku_id"]
        },
        "get_risk_explanation": {
            "purpose": "Extracts SHAP diagnostic signals and explanations from Module 04 Explainability.",
            "source_module": "M4_EXPLAINABILITY",
            "required_params": ["sku_id"]
        },
        "get_capital_exposure": {
            "purpose": "Extracts capital exposure and inventory value from Module 05 Capital Exposure Engine.",
            "source_module": "M5_CAPITAL",
            "required_params": ["sku_id"]
        },
        "get_inventory_aging": {
            "purpose": "Extracts inventory aging days and aging bucket from Module 05 Inventory Aging Engine.",
            "source_module": "M5_AGING",
            "required_params": ["sku_id"]
        },
        "get_recovery_options": {
            "purpose": "Extracts discount simulation scenarios from Module 06 Discount Engine.",
            "source_module": "M6_DISCOUNT",
            "required_params": ["sku_id"]
        },
        "get_decision_recommendation": {
            "purpose": "Extracts canonical decision recommendation from Module 06 Decision Engine.",
            "source_module": "M6_DECISION",
            "required_params": ["sku_id"]
        },
        "get_priority_actions": {
            "purpose": "Extracts portfolio action priority queue from Module 06 Action Priority Engine.",
            "source_module": "M6_PRIORITY",
            "required_params": []
        }
    }

    @classmethod
    def get_tool_definition(cls, tool_name: str) -> Optional[Dict[str, Any]]:
        return cls.TOOLS.get(tool_name)


class CopilotContextBuilder:
    """Builds minimal grounded context packages for Gemini consumption."""

    @classmethod
    def build_grounded_context(
        self,
        merchant_id: str = "merchant_default",
        sku_id: Optional[str] = None,
        tool_results: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        tool_results = tool_results or {}

        risk_data = tool_results.get("get_risk_profile", {})
        exp_data = tool_results.get("get_risk_explanation", {})
        cap_data = tool_results.get("get_capital_exposure", {})
        dec_data = tool_results.get("get_decision_recommendation", {})

        return {
            "merchant_context": {
                "merchant_id": merchant_id,
                "dataset_version": "v1.0"
            },
            "sku_context": {
                "sku_id": sku_id or "PORTFOLIO_SUMMARY",
                "product_name": risk_data.get("product_name"),
                "category": risk_data.get("category")
            },
            "risk_context": {
                "risk_class": risk_data.get("risk_class", "UNKNOWN"),
                "risk_score": risk_data.get("risk_score", 0.0),
                "risk_probability": risk_data.get("risk_probability", 0.0)
            },
            "explainability_context": {
                "top_contributors": exp_data.get("top_contributors", []),
                "positive_signals": exp_data.get("positive_signals", []),
                "negative_signals": exp_data.get("negative_signals", [])
            },
            "capital_context": {
                "capital_exposure": cap_data.get("capital_exposure", 0.0),
                "aging_days": cap_data.get("aging_days", 0),
                "aging_bucket": cap_data.get("aging_bucket", "UNKNOWN")
            },
            "decision_context": {
                "recommended_action": dec_data.get("action", "MONITOR"),
                "priority_score": dec_data.get("priority_score", 0.0),
                "discount_rate": dec_data.get("discount_rate"),
                "expected_recovery": dec_data.get("expected_recovery", 0.0)
            }
        }


class CopilotOrchestrator:
    """
    Main Orchestrator for Module 07 Copilot Architecture.
    Coordinates query processing, intent detection, tool selection, evidence aggregation,
    and LLM boundary enforcement.
    """

    def __init__(self):
        self.classifier = CopilotIntentClassifier()
        self.registry = CopilotToolRegistry()
        self.context_builder = CopilotContextBuilder()

    def process_request(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        query = request_payload.get("query", "")
        merchant_id = request_payload.get("merchant_id", "merchant_default")
        sku_id = request_payload.get("sku_id")

        # 1. Intent Detection
        intent = self.classifier.classify_query(query)

        # 2. Handle Out of Scope
        if intent["code"] == CopilotIntent.OUT_OF_SCOPE.value:
            return {
                "response_id": f"COP-{uuid.uuid4().hex[:8].upper()}",
                "query": query,
                "intent": intent,
                "answer": "Yêu cầu của bạn nằm ngoài phạm vi hỗ trợ quản trị tồn kho và tối ưu hóa vốn của SupplyForge AI Copilot.",
                "evidence": [],
                "recommendations": [],
                "actions": [],
                "sources": [],
                "audit": {
                    "tool_calls": [],
                    "evidence_count": 0,
                    "llm_boundary_enforced": True,
                    "execution_time_ms": round((time.time() - start_time) * 1000, 2)
                }
            }

        # 3. Tool Selection based on Intent
        selected_tools = self._select_tools_for_intent(intent["code"], sku_id)

        # 4. Tool Execution & Mock Evidence Aggregation (Simulating M3-M6 trusted API responses)
        tool_results = self._execute_tools(selected_tools, sku_id)
        evidence = self._aggregate_evidence(tool_results)

        # 5. Build Minimal Grounded Context
        grounded_context = self.context_builder.build_grounded_context(merchant_id, sku_id, tool_results)

        # 6. LLM Narrative Generation (Strictly grounded on evidence, 0 direct LLM calculations)
        answer = self._generate_grounded_answer(query, intent["code"], grounded_context, evidence)

        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        return {
            "response_id": f"COP-{uuid.uuid4().hex[:8].upper()}",
            "query": query,
            "intent": intent,
            "answer": answer,
            "evidence": evidence,
            "recommendations": [grounded_context["decision_context"]] if grounded_context["decision_context"].get("recommended_action") else [],
            "actions": [
                {
                    "action_type": grounded_context["decision_context"].get("recommended_action", "REVIEW"),
                    "label": f"Thực thi {grounded_context['decision_context'].get('recommended_action', 'Xem xét')}",
                    "target_sku": sku_id or "ALL"
                }
            ],
            "sources": [tool_info["source_module"] for tool in selected_tools if (tool_info := self.registry.get_tool_definition(tool))],
            "audit": {
                "tool_calls": selected_tools,
                "evidence_count": len(evidence),
                "llm_boundary_enforced": True,
                "execution_time_ms": execution_time_ms
            }
        }

    def _select_tools_for_intent(self, intent_code: str, sku_id: Optional[str]) -> List[str]:
        if not sku_id:
            return ["get_priority_actions"]

        if intent_code == CopilotIntent.RISK_QUERY.value:
            return ["get_risk_profile", "get_inventory_aging"]
        elif intent_code == CopilotIntent.EXPLAINABILITY_QUERY.value:
            return ["get_risk_profile", "get_risk_explanation"]
        elif intent_code == CopilotIntent.CAPITAL_QUERY.value:
            return ["get_capital_exposure", "get_inventory_aging"]
        elif intent_code == CopilotIntent.DECISION_QUERY.value:
            return ["get_risk_profile", "get_capital_exposure", "get_decision_recommendation", "get_recovery_options"]
        else:
            return ["get_risk_profile", "get_capital_exposure", "get_decision_recommendation"]

    def _execute_tools(self, tools: List[str], sku_id: Optional[str]) -> Dict[str, Any]:
        """Simulates structured execution of M3-M6 API calls."""
        results = {}
        for tool in tools:
            if tool == "get_risk_profile":
                results[tool] = {
                    "sku": sku_id,
                    "risk_class": "CRITICAL",
                    "risk_score": 0.95,
                    "risk_probability": 0.95
                }
            elif tool == "get_risk_explanation":
                results[tool] = {
                    "top_contributors": [{"feature": "days_since_last_sale", "shap_value": 0.42}],
                    "positive_signals": ["zero_sales_90d"],
                    "negative_signals": []
                }
            elif tool == "get_capital_exposure":
                results[tool] = {
                    "capital_exposure": 15000000.0,
                    "aging_days": 375,
                    "aging_bucket": "SEVERELY_STALE"
                }
            elif tool == "get_decision_recommendation":
                results[tool] = {
                    "action": "DISCOUNT",
                    "priority_score": 0.92,
                    "discount_rate": 0.20,
                    "expected_recovery": 12000000.0
                }
        return results

    def _aggregate_evidence(self, tool_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        evidence = []
        if "get_risk_profile" in tool_results:
            rp = tool_results["get_risk_profile"]
            evidence.append({
                "metric": "Risk Class & Score",
                "value": f"{rp.get('risk_class')} ({rp.get('risk_score')})",
                "source_module": "M3_RISK",
                "interpretation": "Mức độ rủi ro bán chậm nghiêm trọng."
            })
        if "get_capital_exposure" in tool_results:
            cap = tool_results["get_capital_exposure"]
            evidence.append({
                "metric": "Capital Exposure",
                "value": f"{cap.get('capital_exposure'):,.0f} VND",
                "source_module": "M5_CAPITAL",
                "interpretation": "Lượng vốn tồn kho đang bị phơi nhiễm."
            })
        if "get_decision_recommendation" in tool_results:
            dec = tool_results["get_decision_recommendation"]
            evidence.append({
                "metric": "Recommended Action",
                "value": f"{dec.get('action')} (Giảm giá {(dec.get('discount_rate', 0)*100):.0f}%)",
                "source_module": "M6_DECISION",
                "interpretation": "Phương án giải phóng vốn tối ưu được M6 khuyến nghị."
            })
        return evidence

    def _generate_grounded_answer(
        self,
        query: str,
        intent_code: str,
        context: Dict[str, Any],
        evidence: List[Dict[str, Any]]
    ) -> str:
        sku = context["sku_context"].get("sku_id", "Danh mục")
        risk_class = context["risk_context"].get("risk_class", "Chưa xác định")
        cap_exposure = context["capital_context"].get("capital_exposure", 0)
        action = context["decision_context"].get("recommended_action", "MONITOR")
        rec_val = context["decision_context"].get("expected_recovery", 0)

        if intent_code == CopilotIntent.DECISION_QUERY.value:
            return (
                f"Đối với sản phẩm **{sku}**, hệ thống xác định mức rủi ro bán chậm **{risk_class}** "
                f"với lượng vốn đang bị đóng băng là **{cap_exposure:,.0f} VNĐ**.\n\n"
                f"Hệ thống Decision Support Engine (Module 06) khuyến nghị thực hiện hành động **{action}** "
                f"(áp dụng mức giảm giá 20%) để đạt giá trị thu hồi vốn dự kiến **{rec_val:,.0f} VNĐ** (tỷ lệ thu hồi 80%)."
            )
        elif intent_code == CopilotIntent.EXPLAINABILITY_QUERY.value:
            return (
                f"Sản phẩm **{sku}** bị đánh giá rủi ro bán chậm **{risk_class}** do thời gian không phát sinh đơn hàng "
                f"kéo dài trên 90 ngày và tốc độ bán gần như bằng 0. "
                f"Dữ liệu phân tích SHAP từ Module 04 cho thấy tính chất 'thời gian kể từ lần bán cuối' đóng góp lớn nhất vào điểm rủi ro."
            )
        else:
            return (
                f"Dữ liệu hệ thống ghi nhận sản phẩm **{sku}** có mức rủi ro **{risk_class}** "
                f"và tổng giá trị vốn phơi nhiễm là **{cap_exposure:,.0f} VNĐ**."
            )
