"""
Tool Validator for Task M7-04 Tool Orchestration.
Module 07: AI Copilot & Merchant Workspace

Validates proposed tool calls, input parameters, and output results against registry contracts.
"""

from typing import Dict, Any, List, Optional
from src.copilot.copilot_architecture import CopilotToolRegistry


class ToolValidationError(Exception):
    pass


class UnauthorizedToolError(ToolValidationError):
    pass


class ToolValidator:
    """Validates tool authorization, input parameters, and execution output."""

    @classmethod
    def validate_tool_permission(cls, tool_name: str) -> bool:
        definition = CopilotToolRegistry.get_tool_definition(tool_name)
        if not definition:
            raise UnauthorizedToolError(f"REJECT_UNKNOWN_TOOL: Tool '{tool_name}' is not registered in Copilot Tool Registry.")
        return True

    @classmethod
    def validate_input_parameters(
        cls,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:

        cls.validate_tool_permission(tool_name)
        definition = CopilotToolRegistry.get_tool_definition(tool_name)
        required_params = definition.get("required_params", [])

        missing = [p for p in required_params if p not in params or params[p] is None]
        if missing:
            raise ToolValidationError(f"Missing required input parameters for tool '{tool_name}': {missing}")

        return {
            "merchant_id": params.get("merchant_id", "merchant_default"),
            "dataset_version": params.get("dataset_version", "v1.0"),
            "sku_id": params.get("sku_id")
        }

    @classmethod
    def validate_tool_result(cls, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        if not result or result.get("status") != "SUCCESS":
            return {
                "is_valid": False,
                "error_message": result.get("error_message", f"Tool '{tool_name}' returned status {result.get('status')}")
            }

        data = result.get("data")
        if data is None:
            return {
                "is_valid": False,
                "error_message": f"Tool '{tool_name}' returned null data payload."
            }

        return {
            "is_valid": True,
            "error_message": None
        }
