"""Shared safety gate for executing decisions derived from an ML assessment."""

from __future__ import annotations

from typing import Any

from supplyforge.services.model_loader import ModelLoaderService


def decision_requires_ready_model_runtime(decision: Any) -> bool:
    """Only model-backed decisions are blocked when the serving runtime degrades."""
    parameters = getattr(decision, 'action_parameters', None)
    if not isinstance(parameters, dict):
        return False
    return bool(
        parameters.get('model_runtime_required')
        or parameters.get('model_runtime')
        or parameters.get('model_inference')
    )


def execution_runtime_status(decision: Any) -> dict | None:
    """Return a safe status payload when this ML-backed decision cannot execute."""
    if not decision_requires_ready_model_runtime(decision):
        return None
    runtime = ModelLoaderService.runtime_status()
    if runtime.get('decision_actions_allowed'):
        return None
    return {
        'state': runtime.get('state', 'UNAVAILABLE'),
        'model_version': runtime.get('model_version'),
        'explainability': runtime.get('explainability', 'UNAVAILABLE'),
    }
