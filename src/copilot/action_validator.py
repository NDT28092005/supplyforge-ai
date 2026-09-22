"""
Action Plan Validator for Task M7-08 Action Planning.
Module 07: AI Copilot & Merchant Workspace

Validates parameter integrity between M6 decision recommendation and operational action plan.
"""

from typing import Dict, Any, List


class ActionValidationError(Exception):
    pass


class ActionValidator:
    """Verifies that operational Action Plans preserve 100% parameter integrity with M6 outputs."""

    @classmethod
    def validate_plan_parameters(
        cls,
        m6_decision: Dict[str, Any],
        proposed_action: Dict[str, Any]
    ) -> bool:

        m6_rate = m6_decision.get("discount_rate")
        plan_rate = proposed_action.get("discount_rate")

        if m6_rate is not None and plan_rate is not None:
            if abs(m6_rate - plan_rate) > 1e-4:
                raise ActionValidationError(
                    f"Parameter Integrity Violation: M6 discount_rate is {m6_rate*100:.0f}%, "
                    f"but Action Plan has {plan_rate*100:.0f}%."
                )

        return True
