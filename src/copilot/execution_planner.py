"""
Execution Planner for Task M7-04 Tool Orchestration.
Module 07: AI Copilot & Merchant Workspace

Constructs structured Execution Plans for sequential or parallel tool execution.
"""

import uuid
from typing import Dict, Any, List, Optional
from src.copilot.dependency_resolver import DependencyResolver


class ExecutionPlanner:
    """Constructs execution plans based on intent and dependency resolution."""

    INTENT_TOOL_MAP = {
        "RISK_QUERY": ["get_risk_profile", "get_inventory_aging"],
        "EXPLANATION_QUERY": ["get_risk_profile", "get_risk_explanation"],
        "CAPITAL_QUERY": ["get_capital_exposure", "get_inventory_aging"],
        "AGING_QUERY": ["get_inventory_aging"],
        "DECISION_QUERY": ["get_risk_profile", "get_capital_exposure", "get_inventory_aging", "get_decision_recommendation"],
        "RECOVERY_QUERY": ["get_risk_profile", "get_capital_exposure", "get_recovery_options"],
        "ACTION_QUERY": ["get_risk_profile", "get_capital_exposure", "get_decision_recommendation", "get_priority_actions"],
        "SUMMARY_QUERY": ["get_risk_profile", "get_capital_exposure", "get_decision_recommendation"],
        "DATA_QUALITY_QUERY": ["get_dataset_status"],
        "GENERAL_HELP": []
    }

    @classmethod
    def create_plan(
        cls,
        intent_code: str,
        subject_type: str = "SKU",
        subject_id: Optional[str] = None
    ) -> Dict[str, Any]:

        plan_id = f"PLAN-{uuid.uuid4().hex[:8].upper()}"

        raw_tools = cls.INTENT_TOOL_MAP.get(intent_code, ["get_risk_profile"])
        resolved_tools = DependencyResolver.resolve_dependencies(raw_tools)
        batches = DependencyResolver.get_parallel_batches(resolved_tools)

        execution_mode = "PARALLEL" if len(batches) < len(resolved_tools) and len(resolved_tools) > 1 else "SEQUENTIAL"

        steps = []
        step_counter = 1
        for batch in batches:
            for tool_name in batch:
                prereqs = DependencyResolver.PREREQUISITES_MAP.get(tool_name, [])
                depends_on = [p for p in prereqs if p in resolved_tools]
                steps.append({
                    "step_number": step_counter,
                    "tool_name": tool_name,
                    "depends_on": depends_on,
                    "is_parallelable": len(batch) > 1
                })
                step_counter += 1

        return {
            "plan_id": plan_id,
            "subject": {
                "type": subject_type,
                "id": subject_id or "ALL"
            },
            "execution_mode": execution_mode,
            "steps": steps,
            "resolved_tools": resolved_tools,
            "batches": batches
        }
