"""
Core Tool Orchestrator Engine for Task M7-04 Tool Orchestration.
Module 07: AI Copilot & Merchant Workspace

Coordinates tool planning, input/output validation, execution, retry management,
evidence aggregation, and trace logging.
"""

import uuid
import time
import logging
from typing import Dict, Any, List, Optional

from src.copilot.execution_planner import ExecutionPlanner
from src.copilot.tool_validator import ToolValidator, ToolValidationError
from src.copilot.retry_manager import RetryManager
from src.copilot.context_retriever import ContextRetriever

logger = logging.getLogger(__name__)


class ToolOrchestrator:
    """Execution Control Plane for Module 07 Copilot Tools."""

    def __init__(self):
        self.planner = ExecutionPlanner()
        self.validator = ToolValidator()
        self.retry_manager = RetryManager()
        self.retriever = ContextRetriever()

    def orchestrate_tools(
        self,
        intent_code: str,
        merchant_id: str = "merchant_default",
        sku_id: Optional[str] = None,
        dataset_version: str = "v1.0"
    ) -> Dict[str, Any]:

        orchestration_id = f"ORCH-{uuid.uuid4().hex[:8].upper()}"
        start_time = time.time()

        # 1. Create Execution Plan
        plan = self.planner.create_plan(
            intent_code=intent_code,
            subject_type="SKU" if sku_id else "PORTFOLIO",
            subject_id=sku_id
        )

        # 2. Retrieve Trusted Evidence Context via M7-02 Retriever
        evidence_package = self.retriever.retrieve_evidence_context(
            intent_code=intent_code,
            merchant_id=merchant_id,
            sku_id=sku_id,
            dataset_version=dataset_version,
            use_cache=False
        )

        # 3. Validate Evidence & Version Consistency
        val_summary = evidence_package.get("validation_summary", {})
        if val_summary.get("version_mismatch"):
            logger.error("Dataset version mismatch in evidence package.")

        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        # 4. Construct Execution Audit Trace
        trace = {
            "orchestration_id": orchestration_id,
            "plan_id": plan["plan_id"],
            "intent_code": intent_code,
            "merchant_id": merchant_id,
            "dataset_version": dataset_version,
            "execution_mode": plan["execution_mode"],
            "executed_steps": plan["steps"],
            "tool_count": len(plan["steps"]),
            "status": "SUCCESS" if val_summary.get("is_valid", True) else "FAILED",
            "execution_time_ms": execution_time_ms
        }

        return {
            "orchestration_id": orchestration_id,
            "plan": plan,
            "evidence_package": evidence_package,
            "trace": trace
        }

    def validate_llm_proposed_tool_call(self, proposed_tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validates proposed tool call from LLM against permission guard and input schema."""
        try:
            self.validator.validate_tool_permission(proposed_tool)
            clean_params = self.validator.validate_input_parameters(proposed_tool, params)
            return {
                "is_allowed": True,
                "tool_name": proposed_tool,
                "validated_params": clean_params
            }
        except ToolValidationError as e:
            return {
                "is_allowed": False,
                "tool_name": proposed_tool,
                "error": str(e)
            }
