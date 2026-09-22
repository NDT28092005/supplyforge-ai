"""
Intent Classifier Engine for Task M7-03 Intent Classification.
Module 07: AI Copilot & Merchant Workspace

Hybrid Pattern & Rule-based Classifier with Multi-Intent Support, Scope Guarding,
Entity Extraction, Multi-Turn Context Resolution, and DSS Context Mapping.
"""

import uuid
import logging
from typing import Dict, Any, List, Optional

from src.copilot.scope_guard import ScopeGuard
from src.copilot.entity_extractor import EntityExtractor
from src.copilot.context_resolver import ContextResolver
from src.copilot.intent_validator import IntentValidator

logger = logging.getLogger(__name__)


class IntentClassifier:
    """Core Intent Classification Engine for Module 07."""

    INTENT_CONTEXT_MAP = {
        "RISK_QUERY": ["RISK_PROFILE"],
        "EXPLANATION_QUERY": ["RISK_PROFILE", "RISK_EXPLANATION"],
        "CAPITAL_QUERY": ["CAPITAL_EXPOSURE"],
        "AGING_QUERY": ["INVENTORY_AGING"],
        "DECISION_QUERY": ["DECISION_RECOMMENDATION"],
        "RECOVERY_QUERY": ["RECOVERY_OPTIONS", "CAPITAL_EXPOSURE"],
        "ACTION_QUERY": ["ACTION_PRIORITY", "RISK_PROFILE", "CAPITAL_EXPOSURE"],
        "COMPARISON_QUERY": ["RISK_PROFILE", "CAPITAL_EXPOSURE"],
        "SUMMARY_QUERY": ["RISK_PROFILE", "CAPITAL_EXPOSURE", "DECISION_RECOMMENDATION"],
        "SKU_QUERY": ["SKU_PROFILE"],
        "DATA_QUALITY_QUERY": ["DATASET_STATUS"],
        "GENERAL_HELP": ["SYSTEM_KNOWLEDGE"]
    }

    def __init__(self):
        self.scope_guard = ScopeGuard()
        self.extractor = EntityExtractor()
        self.resolver = ContextResolver()
        self.validator = IntentValidator()

    def classify(
        self,
        query: str,
        session_id: str = "default_session"
    ) -> Dict[str, Any]:

        classification_id = f"CLS-{uuid.uuid4().hex[:8].upper()}"

        # 1. Scope Guard Check
        scope_res = self.scope_guard.check_scope(query)
        if not scope_res["is_in_scope"]:
            return self._build_result(
                classification_id=classification_id,
                query=query,
                primary_intent="OUT_OF_SCOPE",
                secondary_intents=[],
                confidence=0.99,
                entities={},
                context={"subject_type": "NONE", "subject_id": "NONE"},
                is_ambiguous=False,
                is_out_of_scope=True
            )

        # 2. Entity Extraction
        entities = self.extractor.extract_entities(query)

        # 3. Context Resolution (Multi-Turn SKU inheritance)
        resolved_context = self.resolver.resolve_context(session_id, entities)

        # 4. Pattern / Rule-Based Multi-Intent Detection
        detected_intents, confidence = self._detect_intents(query)

        primary_intent = detected_intents[0] if detected_intents else "SUMMARY_QUERY"
        secondary_intents = detected_intents[1:] if len(detected_intents) > 1 else []

        # 5. Validation & Ambiguity Handling
        val_res = self.validator.validate_classification(primary_intent, confidence)
        final_intent = val_res["validated_intent"]
        is_ambiguous = val_res["is_ambiguous"]
        clarification_prompt = val_res["clarification_prompt"]

        return self._build_result(
            classification_id=classification_id,
            query=query,
            primary_intent=final_intent,
            secondary_intents=secondary_intents,
            confidence=val_res["confidence"],
            entities=entities,
            context=resolved_context,
            is_ambiguous=is_ambiguous,
            is_out_of_scope=False,
            clarification_prompt=clarification_prompt
        )

    def _detect_intents(self, query: str) -> tuple[List[str], float]:
        q_lower = query.lower()
        intents = []
        confidence = 0.85

        # Compound / Multi-intent detection
        if "tại sao" in q_lower or "nguyên nhân" in q_lower or "lý do" in q_lower:
            intents.append("EXPLANATION_QUERY")
            confidence = 0.92

        if "vốn" in q_lower or "đóng băng" in q_lower or "phơi nhiễm" in q_lower:
            intents.append("CAPITAL_QUERY")
            confidence = 0.90

        if "tuổi" in q_lower or "lâu nhất" in q_lower or "aging" in q_lower:
            intents.append("AGING_QUERY")
            confidence = 0.88

        if "xử lý" in q_lower or "hành động" in q_lower or "nên làm gì" in q_lower or "giảm giá" in q_lower:
            intents.append("DECISION_QUERY")
            confidence = 0.90

        if "rủi ro" in q_lower or "bán chậm" in q_lower or "critical" in q_lower:
            if "EXPLANATION_QUERY" not in intents:
                intents.append("RISK_QUERY")
                confidence = 0.88

        if "tóm tắt" in q_lower or "tổng quan" in q_lower:
            intents.append("SUMMARY_QUERY")
            confidence = 0.95

        if "chất lượng" in q_lower or "sẵn sàng" in q_lower or "dataset" in q_lower:
            intents.append("DATA_QUALITY_QUERY")
            confidence = 0.92

        if "hướng dẫn" in q_lower or "hoạt động thế nào" in q_lower:
            intents.append("GENERAL_HELP")
            confidence = 0.95

        if not intents:
            intents = ["SUMMARY_QUERY"]
            confidence = 0.55  # Low confidence triggers AMBIGUOUS_INTENT in validator

        return intents, confidence

    def _build_result(
        self,
        classification_id: str,
        query: str,
        primary_intent: str,
        secondary_intents: List[str],
        confidence: float,
        entities: Dict[str, Any],
        context: Dict[str, Any],
        is_ambiguous: bool,
        is_out_of_scope: bool,
        clarification_prompt: Optional[str] = None
    ) -> Dict[str, Any]:

        # Map intent to context requirements
        req_context = self.INTENT_CONTEXT_MAP.get(primary_intent, ["SYSTEM_KNOWLEDGE"])
        for sec in secondary_intents:
            req_context.extend(self.INTENT_CONTEXT_MAP.get(sec, []))
        req_context = list(dict.fromkeys(req_context))  # Unique list

        return {
            "classification_id": classification_id,
            "raw_query": query,
            "primary_intent": primary_intent,
            "secondary_intents": secondary_intents,
            "confidence": confidence,
            "entities": entities,
            "context": context,
            "context_requirements": req_context,
            "is_ambiguous": is_ambiguous,
            "is_out_of_scope": is_out_of_scope,
            "clarification_prompt": clarification_prompt,
            "next_action": "CLARIFY" if is_ambiguous else ("FALLBACK" if is_out_of_scope else "RETRIEVE_CONTEXT")
        }
