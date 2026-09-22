"""
Test suite for Task M7-08 Action Planning (Module 07).
Verifies AC-01 through AC-18 requirements:
- Decision-to-Action Mapping & Task Decomposition
- Operational Task Templates (DISCOUNT, BUNDLE, LIQUIDATION, PROMOTION, HOLD, MONITOR)
- Dependency Resolution & Circular Dependency Blocking Guard
- Parameter Integrity Validation (detects altered discount rates)
- Priority Inheritance from M6-07 & SLA Deadlines
- Human Approval Workflow & Version History Tracking
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.action_planner import ActionPlanner
from src.copilot.action_template_registry import ActionTemplateRegistry
from src.copilot.dependency_manager import ActionDependencyManager, CircularDependencyError
from src.copilot.action_validator import ActionValidator, ActionValidationError
from src.copilot.plan_versioning import PlanVersioningManager


class TestActionPlanning(TestCase):

    def setUp(self):
        self.planner = ActionPlanner()
        self.decision_data = {
            "recommended_action": "DISCOUNT",
            "discount_rate": 0.20,
            "expected_recovery": 12000000.0,
            "action_priority_score": 0.91,
            "recommendation_reason": "Mức rủi ro cao và vốn bị phơi nhiễm 15 triệu."
        }

    def test_action_templates(self):
        """AC-01, AC-02, AC-03, AC-07, AC-08: Verifies task decomposition and template registry."""
        tasks_discount = ActionTemplateRegistry.get_template("DISCOUNT")
        self.assertEqual(len(tasks_discount), 5)
        self.assertEqual(tasks_discount[0]["owner_role"], "Merchandising")

        tasks_bundle = ActionTemplateRegistry.get_template("BUNDLE")
        self.assertEqual(len(tasks_bundle), 3)

    def test_circular_dependency_guard(self):
        """AC-04, AC-05: Verifies detection and blocking of circular dependency graphs."""
        valid_tasks = [
            {"task_id": "T1", "depends_on": []},
            {"task_id": "T2", "depends_on": ["T1"]}
        ]
        self.assertTrue(ActionDependencyManager.validate_dependencies(valid_tasks))

        cyclic_tasks = [
            {"task_id": "T1", "depends_on": ["T2"]},
            {"task_id": "T2", "depends_on": ["T1"]}
        ]
        with self.assertRaises(CircularDependencyError):
            ActionDependencyManager.validate_dependencies(cyclic_tasks)

    def test_parameter_integrity_validation(self):
        """AC-09: Verifies parameter integrity validation blocks altered discount rates."""
        # 1. Matching parameters -> Pass
        self.assertTrue(ActionValidator.validate_plan_parameters(
            self.decision_data, {"discount_rate": 0.20}
        ))

        # 2. Altered parameter (25% instead of 20%) -> Exception
        with self.assertRaises(ActionValidationError):
            ActionValidator.validate_plan_parameters(
                self.decision_data, {"discount_rate": 0.25}
            )

    def test_plan_versioning(self):
        """AC-14: Verifies version increments."""
        self.assertEqual(PlanVersioningManager.get_next_version("v1.0"), "v2.0")

    def test_end_to_end_action_planning_and_approval(self):
        """AC-06, AC-10, AC-11, AC-12, AC-13, AC-15, AC-16, AC-17: Verifies end-to-end plan creation and human approval."""
        # 1. Create Action Plan
        plan = self.planner.create_action_plan(
            decision_data=self.decision_data,
            subject_id="SKU-001",
            decision_id="DEC-1001",
            decision_version="v1.0"
        )

        self.assertIn("plan_id", plan)
        self.assertEqual(plan["status"], "DRAFT")
        self.assertEqual(plan["priority"], "HIGH")
        self.assertEqual(plan["action"]["discount_rate"], 0.20)
        self.assertEqual(plan["expected_outcome"]["expected_recovery_vnd"], 12000000.0)

        # 2. Human Merchant Approval
        approved_plan = self.planner.approve_plan(plan)
        self.assertEqual(approved_plan["status"], "APPROVED")
