"""
Core Action Planner Engine for Task M7-08 Action Planning.
Module 07: AI Copilot & Merchant Workspace

Coordinates Decision-to-Action Mapping, task decomposition, dependency resolution,
parameter integrity validation, SLA deadlines, and approval status transitions.
"""

import uuid
import logging
from typing import Dict, Any, List, Optional

from src.copilot.action_template_registry import ActionTemplateRegistry
from src.copilot.dependency_manager import ActionDependencyManager
from src.copilot.action_validator import ActionValidator
from src.copilot.plan_versioning import PlanVersioningManager

logger = logging.getLogger(__name__)


class ActionPlanner:
    """Operational Execution Planner for Module 07 Copilot."""

    def __init__(self):
        self.template_registry = ActionTemplateRegistry()
        self.dependency_manager = ActionDependencyManager()
        self.validator = ActionValidator()
        self.version_manager = PlanVersioningManager()

    def create_action_plan(
        self,
        decision_data: Dict[str, Any],
        subject_id: str = "SKU-001",
        decision_id: Optional[str] = None,
        decision_version: str = "v1.0"
    ) -> Dict[str, Any]:

        plan_id = f"PLAN-{uuid.uuid4().hex[:8].upper()}"
        dec_id = decision_id or f"DEC-{uuid.uuid4().hex[:6].upper()}"

        action_type = decision_data.get("recommended_action", "DISCOUNT")
        discount_rate = decision_data.get("discount_rate", 0.20)
        expected_recovery = decision_data.get("expected_recovery", 12000000.0)
        p_score = decision_data.get("action_priority_score", 0.91)

        proposed_action = {
            "type": action_type,
            "discount_rate": discount_rate
        }

        # 1. Parameter Integrity Validation
        self.validator.validate_plan_parameters(decision_data, proposed_action)

        # 2. Priority Inheritance from M6-07
        priority = "HIGH" if p_score >= 0.80 else ("MEDIUM" if p_score >= 0.50 else "LOW")

        # 3. Task Decomposition from Template Registry
        raw_tasks = self.template_registry.get_template(action_type)
        tasks = [dict(t) for t in raw_tasks]

        # 4. Dependency Validation & Status Resolution
        self.dependency_manager.validate_dependencies(tasks)
        tasks = self.dependency_manager.resolve_task_statuses(tasks)

        # 5. Build Measurable Success Criteria & Expected Outcome
        expected_outcome = {
            "expected_recovery_vnd": expected_recovery,
            "target_metric": "Capital Exposure",
            "evaluation_window_days": 7,
            "success_criteria": f"Giảm giá phơi nhiễm vốn và thu hồi tối thiểu {expected_recovery:,.0f} VNĐ."
        }

        return {
            "plan_id": plan_id,
            "decision_id": dec_id,
            "decision_version": decision_version,
            "subject_id": subject_id,
            "status": "DRAFT",
            "action": proposed_action,
            "priority": priority,
            "tasks": tasks,
            "expected_outcome": expected_outcome
        }

    def approve_plan(self, action_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Approves a DRAFT action plan for execution."""
        if action_plan.get("status") in ["DRAFT", "PENDING_APPROVAL"]:
            action_plan["status"] = "APPROVED"
        return action_plan
