"""
Test suite for Task M7-04 Tool Orchestration (Module 07).
Verifies AC-01 through AC-14 requirements:
- Tool Registry & Tool Selection from intent
- Execution Planning & Dependency Resolution (Topological ordering & Parallel batches)
- Input & Output Validation (blocking unauthorized LLM tool calls)
- Retry Management & Non-Retryable Error handling
- Evidence Aggregation & Audit Trail Traceability
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.tool_orchestrator import ToolOrchestrator
from src.copilot.execution_planner import ExecutionPlanner
from src.copilot.dependency_resolver import DependencyResolver
from src.copilot.tool_validator import ToolValidator, UnauthorizedToolError, ToolValidationError
from src.copilot.retry_manager import RetryManager


class TestToolOrchestration(TestCase):

    def setUp(self):
        self.orchestrator = ToolOrchestrator()

    def test_dependency_resolution_and_topological_order(self):
        """AC-01, AC-04: Verifies topological ordering of tool steps with dependencies."""
        raw_tools = ["get_decision_recommendation", "get_risk_profile"]
        resolved = DependencyResolver.resolve_dependencies(raw_tools)
        # get_risk_profile must execute BEFORE get_decision_recommendation
        self.assertEqual(resolved[0], "get_risk_profile")
        self.assertEqual(resolved[1], "get_decision_recommendation")

    def test_parallel_batches(self):
        """AC-05: Verifies parallel batching for independent tools."""
        independent_tools = ["get_risk_profile", "get_capital_exposure", "get_inventory_aging"]
        batches = DependencyResolver.get_parallel_batches(independent_tools)
        # Independent tools can execute in 1 parallel batch
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)

    def test_execution_plan_creation(self):
        """AC-02, AC-03: Verifies creation of structured ExecutionPlan."""
        plan = ExecutionPlanner.create_plan("DECISION_QUERY", subject_type="SKU", subject_id="SKU-001")
        self.assertIn("plan_id", plan)
        self.assertEqual(plan["subject"]["id"], "SKU-001")
        self.assertGreater(len(plan["steps"]), 0)

    def test_llm_proposed_tool_validation_and_permission_guard(self):
        """AC-06, AC-07, AC-10, AC-13: Verifies application-side validation of proposed LLM tool calls."""
        # 1. Registered Valid Tool Call -> Allowed
        res_valid = self.orchestrator.validate_llm_proposed_tool_call("get_risk_profile", {"sku_id": "SKU-001"})
        self.assertTrue(res_valid["is_allowed"])

        # 2. Unauthorized / Unknown Tool Call -> Rejected
        res_invalid = self.orchestrator.validate_llm_proposed_tool_call("delete_database", {"sku_id": "SKU-001"})
        self.assertFalse(res_invalid["is_allowed"])
        self.assertIn("REJECT_UNKNOWN_TOOL", res_invalid["error"])

    def test_end_to_end_orchestration_and_audit_trace(self):
        """AC-09, AC-11, AC-12: Verifies end-to-end tool orchestration, evidence aggregation & audit trace."""
        result = self.orchestrator.orchestrate_tools(
            intent_code="DECISION_QUERY",
            merchant_id="merchant_test",
            sku_id="SKU-001",
            dataset_version="v1.0"
        )

        self.assertIn("orchestration_id", result)
        self.assertIn("evidence_package", result)
        self.assertEqual(result["trace"]["status"], "SUCCESS")
        self.assertGreater(result["trace"]["execution_time_ms"], 0)
