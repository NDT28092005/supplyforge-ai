"""
Context Retriever Engine for Task M7-02 Context Retrieval.
Module 07: AI Copilot & Merchant Workspace

Coordinates Context Planning, Provider Dispatch, Validation, Version Consistency,
and Evidence Package Assembly.
"""

import logging
from typing import Dict, Any, Optional, List

from src.copilot.context_planner import ContextPlanner
from src.copilot.context_validator import (
    ContextValidator, DatasetNotReadyError, VersionMismatchError
)
from src.copilot.evidence_assembler import EvidenceAssembler
from src.copilot.providers import (
    RiskProfileProvider, RiskExplanationProvider,
    CapitalExposureProvider, DecisionSupportProvider,
    DatasetStatusProvider
)

logger = logging.getLogger(__name__)


class ContextRetriever:
    """Core retrieval engine for Module 07 Context Retrieval Layer."""

    def __init__(self):
        self.planner = ContextPlanner()
        self.validator = ContextValidator()
        self.assembler = EvidenceAssembler()
        self._cache: Dict[str, Any] = {}

    def retrieve_evidence_context(
        self,
        intent_code: str,
        merchant_id: str = "merchant_default",
        sku_id: Optional[str] = None,
        dataset_version: str = "v1.0",
        use_cache: bool = True
    ) -> Dict[str, Any]:

        cache_key = f"{merchant_id}:{dataset_version}:{intent_code}:{sku_id or 'PORTFOLIO'}"
        if use_cache and cache_key in self._cache:
            logger.info("Returning cached Evidence Context for %s", cache_key)
            return self._cache[cache_key]

        # 1. DAT-11 Readiness Gate Check
        dataset_status = DatasetStatusProvider.get_status(dataset_version)
        try:
            self.validator.validate_dataset_readiness(dataset_status)
        except DatasetNotReadyError as e:
            return self._build_error_response("DATASET_NOT_READY", str(e), merchant_id, dataset_version, sku_id)

        # 2. Plan Context Requirements
        plan = self.planner.create_plan(intent_code, sku_id)
        required_modules = plan["required_modules"]

        # 3. Retrieve Raw Contexts from Providers
        raw_contexts = []
        try:
            if "M3_RISK" in required_modules:
                raw_contexts.append(RiskProfileProvider.get_context(sku_id, dataset_version))
            if "M4_EXPLAINABILITY" in required_modules:
                raw_contexts.append(RiskExplanationProvider.get_context(sku_id, dataset_version))
            if "M5_CAPITAL" in required_modules:
                raw_contexts.append(CapitalExposureProvider.get_context(sku_id, dataset_version))
            if "M6_DECISION" in required_modules:
                raw_contexts.append(DecisionSupportProvider.get_context(sku_id, dataset_version))
        except Exception as e:
            logger.error("Provider retrieval error: %s", e)
            return self._build_error_response("SOURCE_UNAVAILABLE", str(e), merchant_id, dataset_version, sku_id)

        # 4. Validate Dataset Version Consistency across providers
        try:
            self.validator.validate_version_consistency(raw_contexts)
        except VersionMismatchError as e:
            return self._build_error_response("CONTEXT_VERSION_MISMATCH", str(e), merchant_id, dataset_version, sku_id)

        # 5. Validate Field Completeness
        validation_summary = self.validator.validate_completeness(raw_contexts, plan["required_fields"])

        # 6. Evidence Package Assembly & Size Control
        evidence_package = self.assembler.assemble_evidence_package(
            merchant_id=merchant_id,
            dataset_version=dataset_version,
            scope=plan["scope"],
            target_id=sku_id,
            raw_contexts=raw_contexts,
            validation_summary=validation_summary
        )

        if use_cache:
            self._cache[cache_key] = evidence_package

        return evidence_package

    def _build_error_response(
        self,
        error_code: str,
        message: str,
        merchant_id: str,
        dataset_version: str,
        sku_id: Optional[str]
    ) -> Dict[str, Any]:
        return {
            "context_id": "CTX-ERROR",
            "merchant_id": merchant_id,
            "dataset_version": dataset_version,
            "readiness_status": "NOT_READY" if error_code == "DATASET_NOT_READY" else "ERROR",
            "subject": {"type": "SKU" if sku_id else "PORTFOLIO", "id": sku_id or "ALL"},
            "error": {
                "code": error_code,
                "message": message
            },
            "evidence_items": [],
            "validation_summary": {
                "is_valid": False,
                "version_mismatch": error_code == "CONTEXT_VERSION_MISMATCH",
                "missing_fields": []
            }
        }
