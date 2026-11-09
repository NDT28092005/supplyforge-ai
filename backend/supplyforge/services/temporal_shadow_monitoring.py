"""Matured-outcome monitoring for governed temporal SHADOW/CANARY candidates."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from bisect import bisect_right
import math
from math import ceil
from typing import Any

from django.db.models import DateTimeField, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from supplyforge.models import OrderItem, TemporalShadowPrediction


RISK_CLASSES = {"CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"}
HIGH_RISK_CLASSES = {"CRITICAL", "HIGH_RISK"}


class TemporalShadowMonitoringError(ValueError):
    """Raised when SHADOW telemetry would be incomplete or invalid."""


class TemporalShadowMonitoringService:
    """Persist and assess live candidate predictions only after labels mature.

    A stored row represents a decision cohort. It is not used as a training
    label, does not rewrite a prediction, and does not assert an inventory or
    capital outcome. Outcome labels are reconstructed exclusively from later
    verified fulfilled-demand events using the versioned target thresholds
    captured at prediction time.
    """

    HORIZON_DAYS = 60
    RANKING_FRACTION = 0.05
    CALIBRATION_BINS = 10
    DRIFT_ALERT_PSI = 0.20
    MIN_DRIFT_COHORT_SIZE = 20

    @staticmethod
    def _aware(value: datetime | str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @staticmethod
    def _normalise_probability(value: Any, name: str) -> float:
        try:
            probability = float(value)
        except (TypeError, ValueError) as exc:
            raise TemporalShadowMonitoringError(f"{name} must be numeric") from exc
        if not 0 <= probability <= 1:
            raise TemporalShadowMonitoringError(f"{name} must be in [0, 1]")
        return probability

    @classmethod
    def record_prediction(cls, *, workspace_id: int, prediction: dict[str, Any]) -> TemporalShadowPrediction | None:
        """Idempotently capture a SHADOW/CANARY decision cohort.

        ACTIVE output is intentionally excluded: its performance is handled by
        the established model-governance lifecycle, while this table exists to
        assess a candidate before promotion.
        """
        serving_state = str(prediction.get("serving_state") or "").upper()
        if serving_state not in {"SHADOW", "CANARY"}:
            return None
        risk_class = str(prediction.get("risk_class") or "").upper()
        if risk_class not in RISK_CLASSES:
            raise TemporalShadowMonitoringError("predicted risk_class is invalid")
        canonical_sku = str((prediction.get("data_provenance") or {}).get("canonical_sku") or "").strip()
        model_version = str(prediction.get("model_version") or "").strip()
        if not canonical_sku or not model_version:
            raise TemporalShadowMonitoringError("canonical SKU and model version are required")
        cutoff = cls._aware(prediction["decision_cutoff"])
        thresholds = dict(prediction.get("ground_truth_thresholds") or {
            "critical_future_quantity": 0,
            "high_risk_future_quantity_max": 5,
            "medium_risk_future_quantity_max": 25,
        })
        high_max = int(thresholds.get("high_risk_future_quantity_max", -1))
        medium_max = int(thresholds.get("medium_risk_future_quantity_max", -1))
        if int(thresholds.get("critical_future_quantity", -1)) != 0 or high_max < 1 or medium_max <= high_max:
            raise TemporalShadowMonitoringError("captured Ground Truth thresholds are invalid")

        feature_values = prediction.get("feature_values") or {}
        class_probabilities = prediction.get("class_probabilities") or {}
        record, _ = TemporalShadowPrediction.objects.get_or_create(
            workspace_id=workspace_id,
            canonical_sku=canonical_sku,
            model_version=model_version,
            decision_cutoff=cutoff,
            defaults={
                "serving_state": serving_state,
                "operating_mode": str(prediction.get("operating_mode") or "balanced"),
                "feature_schema_version": str(prediction.get("feature_schema_version") or ""),
                "ground_truth_schema_version": str(prediction.get("ground_truth_schema_version") or ""),
                "ground_truth_thresholds_json": thresholds,
                "outcome_observation_ends_at": cutoff + timedelta(days=cls.HORIZON_DAYS),
                "predicted_risk_class": risk_class,
                "high_risk_probability": cls._normalise_probability(prediction.get("risk_probability"), "risk_probability"),
                "raw_high_risk_probability": cls._normalise_probability(
                    prediction.get("raw_high_risk_probability"), "raw_high_risk_probability"
                ),
                "class_probabilities_json": {key: float(value) for key, value in class_probabilities.items()},
                "feature_vector_json": {key: float(value) for key, value in feature_values.items()},
                "source_lineage_json": {
                    "source": (prediction.get("data_provenance") or {}).get("source"),
                    "qualifyingOrderCount": (prediction.get("data_provenance") or {}).get("qualifying_order_count"),
                    "groundTruthStatus": prediction.get("ground_truth_status"),
                },
            },
        )
        return record

    @staticmethod
    def _actual_risk_class(future_quantity: float, thresholds: dict[str, Any]) -> str:
        high_max = float(thresholds["high_risk_future_quantity_max"])
        medium_max = float(thresholds["medium_risk_future_quantity_max"])
        if future_quantity <= 0:
            return "CRITICAL"
        if future_quantity <= high_max:
            return "HIGH_RISK"
        if future_quantity <= medium_max:
            return "MEDIUM_RISK"
        return "LOW_RISK"

    @classmethod
    def _future_fulfilled_quantity(cls, prediction: TemporalShadowPrediction) -> float:
        """Read only qualifying events strictly after the stored decision cutoff."""
        items = (
            OrderItem.objects.filter(
                canonical_sku=prediction.canonical_sku,
                quantity__gt=0,
                order__user_id=str(prediction.workspace.owner_id),
                order__status__in=("COMPLETED", "SHIPPED"),
                order__return_identifier__isnull=True,
                order__is_accounting=True,
                order__demand_eligibility_verified=True,
            )
            .annotate(
                event_time=Coalesce(
                    F("order__source_event_at"),
                    F("order__created_at"),
                    output_field=DateTimeField(),
                )
            )
            .filter(
                event_time__isnull=False,
                event_time__gt=prediction.decision_cutoff,
                event_time__lte=prediction.outcome_observation_ends_at,
            )
        )
        return float(items.aggregate(total=Sum("quantity"))["total"] or 0.0)

    @classmethod
    def mature_outcomes(
        cls,
        *,
        workspace_id: int | None = None,
        as_of: datetime | None = None,
        batch_size: int = 500,
    ) -> dict[str, int]:
        """Attach outcomes only for cohorts whose entire 60-day window ended."""
        observed_at = cls._aware(as_of) if as_of else timezone.now()
        pending = TemporalShadowPrediction.objects.filter(
            actual_risk_class__isnull=True,
            outcome_observation_ends_at__lte=observed_at,
        ).select_related("workspace")
        if workspace_id is not None:
            pending = pending.filter(workspace_id=workspace_id)
        matured = 0
        for prediction in pending.iterator(chunk_size=batch_size):
            future_quantity = cls._future_fulfilled_quantity(prediction)
            prediction.actual_future_fulfilled_quantity = future_quantity
            prediction.actual_risk_class = cls._actual_risk_class(
                future_quantity,
                dict(prediction.ground_truth_thresholds_json or {}),
            )
            prediction.outcome_observed_at = observed_at
            prediction.save(update_fields=[
                "actual_future_fulfilled_quantity", "actual_risk_class", "outcome_observed_at",
            ])
            matured += 1
        total = TemporalShadowPrediction.objects.all()
        if workspace_id is not None:
            total = total.filter(workspace_id=workspace_id)
        return {
            "matured_now": matured,
            "matured_total": total.filter(actual_risk_class__isnull=False).count(),
            "immature_pending": total.filter(actual_risk_class__isnull=True).count(),
        }

    @classmethod
    def _cohort_metrics(cls, rows: list[TemporalShadowPrediction]) -> dict[str, Any]:
        actual_high = [row.actual_risk_class in HIGH_RISK_CLASSES for row in rows]
        predicted_high = [row.predicted_risk_class in HIGH_RISK_CLASSES for row in rows]
        true_positive = sum(actual and predicted for actual, predicted in zip(actual_high, predicted_high))
        predicted_positive = sum(predicted_high)
        actual_positive = sum(actual_high)
        probabilities = [float(row.high_risk_probability) for row in rows]
        brier = sum((probability - int(actual)) ** 2 for probability, actual in zip(probabilities, actual_high)) / len(rows)

        bins: list[list[tuple[float, bool]]] = [[] for _ in range(cls.CALIBRATION_BINS)]
        for probability, actual in zip(probabilities, actual_high):
            bins[min(cls.CALIBRATION_BINS - 1, int(probability * cls.CALIBRATION_BINS))].append((probability, actual))
        ece = 0.0
        for entries in bins:
            if entries:
                predicted_mean = sum(entry[0] for entry in entries) / len(entries)
                actual_mean = sum(int(entry[1]) for entry in entries) / len(entries)
                ece += len(entries) / len(rows) * abs(predicted_mean - actual_mean)

        top_k = max(1, ceil(len(rows) * cls.RANKING_FRACTION))
        top_rows = sorted(rows, key=lambda row: (-float(row.high_risk_probability), row.canonical_sku))[:top_k]
        top_true_positive = sum(row.actual_risk_class in HIGH_RISK_CLASSES for row in top_rows)
        return {
            "evaluated_skus": len(rows),
            "actual_high_risk_count": actual_positive,
            "predicted_high_risk_count": predicted_positive,
            "high_risk_precision": true_positive / predicted_positive if predicted_positive else None,
            "high_risk_recall": true_positive / actual_positive if actual_positive else None,
            "high_risk_brier": brier,
            "high_risk_ece": ece,
            "ranking_fraction": cls.RANKING_FRACTION,
            "ranking_k": top_k,
            "precision_at_5pct": top_true_positive / top_k,
            "recall_at_5pct": top_true_positive / actual_positive if actual_positive else None,
        }

    @staticmethod
    def _quantile(sorted_values: list[float], quantile: float) -> float:
        position = (len(sorted_values) - 1) * quantile
        lower = int(position)
        upper = min(lower + 1, len(sorted_values) - 1)
        weight = position - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight

    @classmethod
    def _population_stability_index(cls, reference: list[float], current: list[float]) -> float | None:
        """Compute PSI from reference deciles without using outcome labels."""
        if len(reference) < cls.MIN_DRIFT_COHORT_SIZE or len(current) < cls.MIN_DRIFT_COHORT_SIZE:
            return None
        reference = sorted(reference)
        boundaries = sorted({cls._quantile(reference, index / cls.CALIBRATION_BINS) for index in range(1, cls.CALIBRATION_BINS)})
        if not boundaries:
            return 0.0
        reference_counts = [0] * (len(boundaries) + 1)
        current_counts = [0] * (len(boundaries) + 1)
        for value in reference:
            reference_counts[bisect_right(boundaries, value)] += 1
        for value in current:
            current_counts[bisect_right(boundaries, value)] += 1
        epsilon = 1e-6
        return sum(
            ((current_count / len(current)) + epsilon - ((reference_count / len(reference)) + epsilon))
            * math.log(
                ((current_count / len(current)) + epsilon) / ((reference_count / len(reference)) + epsilon)
            )
            for reference_count, current_count in zip(reference_counts, current_counts)
        )

    @classmethod
    def quality_report(cls, *, workspace_id: int | None = None, model_version: str | None = None) -> dict[str, Any]:
        """Return cohort-blocked quality metrics; immature rows are never scored."""
        all_rows = TemporalShadowPrediction.objects.all()
        if workspace_id is not None:
            all_rows = all_rows.filter(workspace_id=workspace_id)
        if model_version:
            all_rows = all_rows.filter(model_version=model_version)
        mature_rows = list(all_rows.filter(actual_risk_class__isnull=False).order_by(
            "workspace_id", "model_version", "decision_cutoff", "canonical_sku"
        ))
        cohorts: dict[tuple[int, str, str, datetime], list[TemporalShadowPrediction]] = defaultdict(list)
        for row in mature_rows:
            cohorts[(row.workspace_id, row.model_version, row.operating_mode, row.decision_cutoff)].append(row)
        results = []
        reference_by_model: dict[tuple[int, str, str], tuple[datetime, list[float]]] = {}
        for (row_workspace_id, version, mode, cutoff), rows in cohorts.items():
            metrics = cls._cohort_metrics(rows)
            drift_key = (row_workspace_id, version, mode)
            probabilities = [float(row.high_risk_probability) for row in rows]
            if drift_key not in reference_by_model:
                reference_by_model[drift_key] = (cutoff, probabilities)
                probability_psi = None
                drift_reference_cutoff = None
            else:
                drift_reference_cutoff, reference = reference_by_model[drift_key]
                probability_psi = cls._population_stability_index(reference, probabilities)
            results.append({
                "workspace_id": row_workspace_id,
                "model_version": version,
                "operating_mode": mode,
                "decision_cutoff": cutoff.isoformat(),
                "drift_reference_cutoff": drift_reference_cutoff.isoformat() if drift_reference_cutoff else None,
                "high_risk_probability_psi": probability_psi,
                "drift_status": (
                    "INSUFFICIENT_REFERENCE" if probability_psi is None
                    else "ALERT" if probability_psi >= cls.DRIFT_ALERT_PSI
                    else "HEALTHY"
                ),
                "drift_alert_psi": cls.DRIFT_ALERT_PSI,
                **metrics,
            })
        return {
            "scope": "matured 60-day future fulfilled-demand outcomes only; not inventory, capital, or causal action outcomes",
            "matured_prediction_count": len(mature_rows),
            "immature_prediction_count": all_rows.filter(actual_risk_class__isnull=True).count(),
            "cohort_count": len(results),
            "cohorts": results,
        }
