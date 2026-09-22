"""
Audit Service for Task M7-10 Copilot API & Persistence.
Module 07: AI Copilot & Merchant Workspace

Records end-to-end audit traces to reconstruct past Copilot interactions.
"""

import uuid
import time
from typing import Dict, Any, List


class AuditLogger:
    """Logs full audit records for request reconstruction."""

    def __init__(self):
        self._audit_records: List[Dict[str, Any]] = []

    def log_interaction(
        self,
        conversation_id: str,
        tenant_id: str,
        merchant_id: str,
        query: str,
        intent_code: str,
        tools_called: List[str],
        response_content: str,
        cost_info: Dict[str, Any],
        latency_ms: float
    ) -> Dict[str, Any]:

        req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
        record = {
            "request_id": req_id,
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "merchant_id": merchant_id,
            "query": query,
            "intent_code": intent_code,
            "tools_called": tools_called,
            "response_content": response_content,
            "token_info": cost_info,
            "latency_ms": latency_ms,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        self._audit_records.append(record)
        return record

    def reconstruct_interaction(self, request_id: str) -> Dict[str, Any]:
        for rec in self._audit_records:
            if rec["request_id"] == request_id:
                return rec
        return {}
