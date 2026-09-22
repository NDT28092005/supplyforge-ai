"""
Cost Tracker for Task M7-10 Copilot API & Persistence.
Module 07: AI Copilot & Merchant Workspace

Tracks input/output token usage and calculates estimated LLM costs.
"""

from typing import Dict, Any


class CostTracker:
    """Calculates LLM token usage and estimated API cost."""

    COST_PER_1K_INPUT_TOKENS = 0.00015
    COST_PER_1K_OUTPUT_TOKENS = 0.00060

    @classmethod
    def calculate_cost(cls, input_text: str, output_text: str) -> Dict[str, Any]:
        # Approximate 1 token = 4 characters
        input_tokens = max(1, len(input_text) // 4)
        output_tokens = max(1, len(output_text) // 4)
        total_tokens = input_tokens + output_tokens

        cost_usd = (
            (input_tokens / 1000.0) * cls.COST_PER_1K_INPUT_TOKENS +
            (output_tokens / 1000.0) * cls.COST_PER_1K_OUTPUT_TOKENS
        )

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(cost_usd, 6)
        }
