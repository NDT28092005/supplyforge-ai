"""Versioned, validation-only model-selection policies for temporal demand risk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OPERATING_MODE_POLICY_PATH = PROJECT_ROOT / "config" / "temporal_demand_risk_operating_mode_policy.json"

_ALLOWED_METRICS = {
    "macro_f1",
    "balanced_accuracy",
    "high_risk_recall",
    "high_risk_precision",
    "high_risk_pr_auc",
    "precision_at_5pct",
    "recall_at_5pct",
}
_CONSTRAINT_TO_METRIC = {
    "min_high_risk_recall": "high_risk_recall",
    "min_high_risk_precision": "high_risk_precision",
    "min_high_risk_pr_auc": "high_risk_pr_auc",
}


class OperatingModePolicyError(ValueError):
    """Raised when a model-selection policy cannot be safely applied."""


def load_operating_mode_policy(path: Path = OPERATING_MODE_POLICY_PATH) -> dict[str, Any]:
    """Load a predeclared operating policy without inspecting any model result."""
    if not path.is_file():
        raise FileNotFoundError(f"Operating-mode policy not found: {path}")
    policy = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "selection_split", "modes"}
    missing = sorted(required.difference(policy))
    if missing:
        raise OperatingModePolicyError(f"Operating-mode policy is missing keys: {missing}")
    if policy["selection_split"] != "validation_only":
        raise OperatingModePolicyError("Operating-mode selection must be validation_only")
    modes = policy["modes"]
    if not isinstance(modes, dict) or not modes:
        raise OperatingModePolicyError("Operating-mode policy must define at least one mode")
    for mode_name, mode in modes.items():
        if not isinstance(mode, dict):
            raise OperatingModePolicyError(f"Operating mode {mode_name} must be an object")
        ranking = mode.get("ranking")
        fallback_ranking = mode.get("fallback_ranking")
        if not isinstance(ranking, list) or not ranking or not isinstance(fallback_ranking, list) or not fallback_ranking:
            raise OperatingModePolicyError(f"Operating mode {mode_name} requires ranking and fallback_ranking")
        if set(ranking).difference(_ALLOWED_METRICS) or set(fallback_ranking).difference(_ALLOWED_METRICS):
            raise OperatingModePolicyError(f"Operating mode {mode_name} uses an unsupported metric")
        constraints = mode.get("eligibility_constraints", {})
        if not isinstance(constraints, dict) or set(constraints).difference(_CONSTRAINT_TO_METRIC):
            raise OperatingModePolicyError(f"Operating mode {mode_name} has unsupported eligibility constraints")
        for key, value in constraints.items():
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise OperatingModePolicyError(f"Operating mode {mode_name} constraint {key} is invalid") from exc
            if not 0 <= value <= 1:
                raise OperatingModePolicyError(f"Operating mode {mode_name} constraint {key} must be in [0, 1]")
    return policy


def _rank(frame: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Apply a deterministic descending ranking with model name as final tie-breaker."""
    return frame.sort_values([*metrics, "model"], ascending=[False] * len(metrics) + [True], kind="stable")


def select_operating_mode_candidate(
    validation_benchmark: pd.DataFrame,
    policy: dict[str, Any],
    mode_name: str,
) -> tuple[str, dict[str, Any]]:
    """Select an ML candidate from validation metrics only.

    ``validation_benchmark`` is deliberately the only performance input. The
    resulting evidence is suitable for an immutable model manifest and makes a
    test-result-dependent selection structurally impossible in this function.
    """
    modes = policy.get("modes") or {}
    if mode_name not in modes:
        raise OperatingModePolicyError(f"Unknown operating mode: {mode_name}")
    mode = modes[mode_name]
    required = {"model", "model_family", *mode["ranking"], *mode["fallback_ranking"]}
    required.update(_CONSTRAINT_TO_METRIC[key] for key in mode.get("eligibility_constraints", {}))
    missing = sorted(required.difference(validation_benchmark.columns))
    if missing:
        raise OperatingModePolicyError(f"Validation benchmark is missing selection columns: {missing}")
    candidates = validation_benchmark.loc[
        validation_benchmark["model_family"].eq("ML_CANDIDATE")
    ].copy()
    if candidates.empty:
        raise OperatingModePolicyError("No ML candidates are available for operating-mode selection")
    for metric in required.difference({"model", "model_family"}):
        candidates[metric] = pd.to_numeric(candidates[metric], errors="coerce")
    if candidates[list(required.difference({"model", "model_family"}))].isna().any().any():
        raise OperatingModePolicyError("Validation benchmark contains missing or non-numeric selection metrics")

    constraints = mode.get("eligibility_constraints", {})
    eligible_mask = pd.Series(True, index=candidates.index)
    for constraint, threshold in constraints.items():
        eligible_mask &= candidates[_CONSTRAINT_TO_METRIC[constraint]] >= float(threshold)
    eligible = candidates.loc[eligible_mask].copy()
    used_fallback = eligible.empty
    pool = candidates if used_fallback else eligible
    ranking = mode["fallback_ranking"] if used_fallback else mode["ranking"]
    ranked = _rank(pool, ranking).reset_index(drop=True)
    selected = str(ranked.iloc[0]["model"])

    audit_metrics = sorted(set([*mode["ranking"], *mode["fallback_ranking"], *(_CONSTRAINT_TO_METRIC[key] for key in constraints)]))
    all_candidates = candidates[["model", *audit_metrics]].copy()
    all_candidates["eligible"] = eligible_mask
    all_candidates = all_candidates.sort_values("model", kind="stable")
    evidence = {
        "selection_split": "validation_only",
        "mode": mode_name,
        "description": mode.get("description", ""),
        "eligibility_constraints": constraints,
        "eligible_model_count": int(len(eligible)),
        "candidate_model_count": int(len(candidates)),
        "used_fallback": bool(used_fallback),
        "ranking_metrics": ranking,
        "selected_model": selected,
        "selected_model_constraints_met": bool(not used_fallback),
        "validation_candidates": all_candidates.to_dict(orient="records"),
    }
    return selected, evidence
