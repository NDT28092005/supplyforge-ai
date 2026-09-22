"""
Idempotency Service for Task M7-10 Copilot API & Persistence.
Module 07: AI Copilot & Merchant Workspace

Prevents duplicate mutation requests using Idempotency-Key headers.
"""

from typing import Dict, Any, Optional


class IdempotencyManager:
    """Manages cached idempotency responses to handle network retries gracefully."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_response(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        if not idempotency_key:
            return None
        return self._cache.get(idempotency_key)

    def set_response(self, idempotency_key: str, response: Dict[str, Any]) -> None:
        if idempotency_key:
            self._cache[idempotency_key] = response
