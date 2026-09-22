"""
Context Validator for Task M7-02 Context Retrieval.
Module 07: AI Copilot & Merchant Workspace

Validates DAT-11 Readiness status, dataset version consistency, and field completeness.
"""

from typing import Dict, Any, List


class ContextValidationError(Exception):
    pass


class DatasetNotReadyError(ContextValidationError):
    pass


class VersionMismatchError(ContextValidationError):
    pass


class ContextValidator:
    """Validates raw provider outputs before evidence assembly."""

    @classmethod
    def validate_dataset_readiness(cls, dataset_status: Dict[str, Any]) -> bool:
        data = dataset_status.get("data", {})
        readiness = data.get("readiness_status", "NOT_READY")
        if readiness != "READY":
            raise DatasetNotReadyError("Dataset status is NOT_READY. Cannot generate DSS evidence.")
        return True

    @classmethod
    def validate_version_consistency(cls, raw_contexts: List[Dict[str, Any]]) -> bool:
        versions = set()
        for ctx in raw_contexts:
            ver = ctx.get("dataset_version")
            if ver:
                versions.add(ver)

        if len(versions) > 1:
            raise VersionMismatchError(f"CONTEXT_VERSION_MISMATCH detected across providers: {versions}")
        return True

    @classmethod
    def validate_completeness(cls, raw_contexts: List[Dict[str, Any]], required_fields: List[str]) -> Dict[str, Any]:
        missing_fields = []
        assembled_keys = set()
        for ctx in raw_contexts:
            data = ctx.get("data", {})
            assembled_keys.update(data.keys())

        for field in required_fields:
            if field not in assembled_keys:
                missing_fields.append(field)

        return {
            "is_valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "version_mismatch": False
        }
