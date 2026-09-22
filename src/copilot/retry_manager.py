"""
Retry Manager for Task M7-04 Tool Orchestration.
Module 07: AI Copilot & Merchant Workspace

Handles tool execution retries, timeouts, and non-retryable error isolation.
"""

import time
import logging
from typing import Callable, Any, Dict

logger = logging.getLogger(__name__)


class RetryManager:
    """Manages tool execution retries with exponential backoff."""

    NON_RETRYABLE_ERRORS = [
        "INVALID_INPUT", "NOT_READY", "VERSION_MISMATCH", "REJECT_UNKNOWN_TOOL"
    ]

    @classmethod
    def execute_with_retry(
        cls,
        tool_func: Callable[[], Dict[str, Any]],
        max_retries: int = 2,
        retry_delay_sec: float = 0.1
    ) -> Dict[str, Any]:

        attempts = 0
        last_exception = None

        while attempts <= max_retries:
            attempts += 1
            try:
                result = tool_func()
                status = result.get("status")

                if status == "SUCCESS":
                    return result

                error_msg = result.get("error_message", "")
                if any(non in error_msg for non in cls.NON_RETRYABLE_ERRORS):
                    logger.warning("Non-retryable error encountered: %s. Aborting retry.", error_msg)
                    return result

            except Exception as e:
                last_exception = e
                logger.warning("Attempt %d failed with exception: %s", attempts, e)

            if attempts <= max_retries:
                time.sleep(retry_delay_sec * (2 ** (attempts - 1)))

        return {
            "status": "FAILED",
            "error_message": f"Execution failed after {max_retries + 1} attempts. Last error: {last_exception}",
            "data": None
        }
