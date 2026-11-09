"""Predeclared, auditable promotion gates for temporal ACTIVE serving."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMOTION_POLICY_PATH = PROJECT_ROOT / "config" / "temporal_demand_risk_promotion_policy.json"


class PromotionGovernanceError(ValueError):
    """Raised when promotion evidence is incomplete, stale, or unsafe."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_promotion_policy(path: Path = PROMOTION_POLICY_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise PromotionGovernanceError(f"Promotion policy not found: {path}")
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionGovernanceError("Promotion policy is not valid JSON.") from exc
    required = {
        "schema_version", "minimum_matured_predictions", "minimum_matured_cohorts",
        "minimum_high_risk_precision", "minimum_high_risk_recall", "minimum_precision_at_5pct",
        "maximum_high_risk_brier", "maximum_high_risk_ece", "maximum_probability_psi",
        "require_no_probability_drift_alert",
    }
    missing = sorted(required.difference(policy))
    if missing:
        raise PromotionGovernanceError(f"Promotion policy is missing fields: {missing}")
    if policy["schema_version"] != "temporal-demand-promotion-v1":
        raise PromotionGovernanceError("Promotion policy schema version is unsupported.")
    for field in required.difference({"schema_version", "require_no_probability_drift_alert"}):
        try:
            value = float(policy[field])
        except (TypeError, ValueError) as exc:
            raise PromotionGovernanceError(f"Promotion policy field {field} must be numeric.") from exc
        if value < 0:
            raise PromotionGovernanceError(f"Promotion policy field {field} cannot be negative.")
    return policy


class TemporalPromotionGovernanceService:
    """Evaluate one immutable SHADOW report without inspecting test metrics."""

    @staticmethod
    def _check(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
        return {"name": name, "passed": bool(passed), "expected": expected, "actual": actual}

    @classmethod
    def evaluate_shadow_report(
        cls,
        *,
        report: dict[str, Any],
        workspace_id: int,
        model_version: str,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        quality = report.get("quality") or {}
        candidates = [
            cohort for cohort in quality.get("cohorts") or []
            if cohort.get("workspace_id") == workspace_id and cohort.get("model_version") == model_version
        ]
        if not candidates:
            raise PromotionGovernanceError("SHADOW report has no mature cohort for this workspace and model version.")

        matured_predictions = sum(int(cohort.get("evaluated_skus") or 0) for cohort in candidates)
        predicted_high = sum(int(cohort.get("predicted_high_risk_count") or 0) for cohort in candidates)
        actual_high = sum(int(cohort.get("actual_high_risk_count") or 0) for cohort in candidates)
        true_positive = sum(
            float(cohort.get("high_risk_precision") or 0) * int(cohort.get("predicted_high_risk_count") or 0)
            for cohort in candidates
        )
        top_k = sum(int(cohort.get("ranking_k") or 0) for cohort in candidates)
        top_true_positive = sum(
            float(cohort.get("precision_at_5pct") or 0) * int(cohort.get("ranking_k") or 0)
            for cohort in candidates
        )
        weighted_brier = sum(
            float(cohort.get("high_risk_brier") or 0) * int(cohort.get("evaluated_skus") or 0)
            for cohort in candidates
        ) / matured_predictions if matured_predictions else None
        weighted_ece = sum(
            float(cohort.get("high_risk_ece") or 0) * int(cohort.get("evaluated_skus") or 0)
            for cohort in candidates
        ) / matured_predictions if matured_predictions else None
        high_precision = true_positive / predicted_high if predicted_high else None
        high_recall = true_positive / actual_high if actual_high else None
        precision_at_5pct = top_true_positive / top_k if top_k else None
        drift_values = [
            float(cohort["high_risk_probability_psi"])
            for cohort in candidates if cohort.get("high_risk_probability_psi") is not None
        ]
        max_psi = max(drift_values) if drift_values else None
        drift_alerts = sum(cohort.get("drift_status") == "ALERT" for cohort in candidates)

        checks = [
            cls._check("minimum_matured_predictions", matured_predictions >= int(policy["minimum_matured_predictions"]), policy["minimum_matured_predictions"], matured_predictions),
            cls._check("minimum_matured_cohorts", len(candidates) >= int(policy["minimum_matured_cohorts"]), policy["minimum_matured_cohorts"], len(candidates)),
            cls._check("minimum_high_risk_precision", high_precision is not None and high_precision >= float(policy["minimum_high_risk_precision"]), policy["minimum_high_risk_precision"], high_precision),
            cls._check("minimum_high_risk_recall", high_recall is not None and high_recall >= float(policy["minimum_high_risk_recall"]), policy["minimum_high_risk_recall"], high_recall),
            cls._check("minimum_precision_at_5pct", precision_at_5pct is not None and precision_at_5pct >= float(policy["minimum_precision_at_5pct"]), policy["minimum_precision_at_5pct"], precision_at_5pct),
            cls._check("maximum_high_risk_brier", weighted_brier is not None and weighted_brier <= float(policy["maximum_high_risk_brier"]), policy["maximum_high_risk_brier"], weighted_brier),
            cls._check("maximum_high_risk_ece", weighted_ece is not None and weighted_ece <= float(policy["maximum_high_risk_ece"]), policy["maximum_high_risk_ece"], weighted_ece),
            cls._check("maximum_probability_psi", max_psi is None or max_psi <= float(policy["maximum_probability_psi"]), policy["maximum_probability_psi"], max_psi),
            cls._check("no_probability_drift_alert", not policy["require_no_probability_drift_alert"] or drift_alerts == 0, policy["require_no_probability_drift_alert"], drift_alerts),
        ]
        return {
            "eligible": all(check["passed"] for check in checks),
            "workspace_id": workspace_id,
            "model_version": model_version,
            "cohort_count": len(candidates),
            "matured_prediction_count": matured_predictions,
            "aggregate_metrics": {
                "high_risk_precision": high_precision,
                "high_risk_recall": high_recall,
                "precision_at_5pct": precision_at_5pct,
                "high_risk_brier": weighted_brier,
                "high_risk_ece": weighted_ece,
                "maximum_probability_psi": max_psi,
                "probability_drift_alert_count": drift_alerts,
            },
            "checks": checks,
            "scope": "Mature SHADOW/CANARY future fulfilled-demand cohorts only; not inventory, capital, or causal action outcomes.",
        }
