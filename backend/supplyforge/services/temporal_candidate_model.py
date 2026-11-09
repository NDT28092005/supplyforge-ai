"""Controlled loader for a temporal demand-risk candidate model.

Unlike the legacy model loader, this service does not impose an estimator type.
It validates the immutable benchmark manifest, artifact checksums and the runtime
feature contract before a candidate can make a serving prediction.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from supplyforge.services.temporal_feature_service import (
    CONTRACT_PATH,
    FeatureContractIncomplete,
    TemporalFeatureService,
)
from supplyforge.ml.temporal_operating_mode import load_operating_mode_policy
from supplyforge.services.temporal_promotion_governance import PROMOTION_POLICY_PATH, file_sha256 as promotion_policy_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RISK_CLASSES = ("CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK")
ALLOWED_SERVING_STATES = {"SHADOW", "CANARY", "ACTIVE"}


class TemporalCandidateUnavailable(Exception):
    """A candidate exists but is not safe or approved for live inference."""


@dataclass(frozen=True)
class TemporalCandidateStatus:
    available: bool
    code: str
    detail: str
    model_name: str | None = None
    model_version: str | None = None
    serving_state: str | None = None
    calibrated: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class TemporalCandidateModelService:
    """Load a separately promoted temporal candidate without silent fallback."""

    _cache_lock = threading.Lock()
    _cache: dict[str, tuple[tuple[int, ...], dict[str, Any], Any, Any]] = {}

    def __init__(self, manifest_path: Path | None = None):
        configured_path = os.environ.get("TEMPORAL_DEMAND_MODEL_MANIFEST")
        self.manifest_path = Path(manifest_path or configured_path or (
            PROJECT_ROOT / "models" / "temporal-demand-risk" / "model_manifest.json"
        ))
        self._manifest: dict[str, Any] | None = None
        self._model: Any | None = None
        self._calibrator: Any | None = None

    def status(self) -> TemporalCandidateStatus:
        try:
            self._load()
        except TemporalCandidateUnavailable as exc:
            return TemporalCandidateStatus(False, "CANDIDATE_UNAVAILABLE", str(exc))
        except Exception as exc:  # Do not expose raw implementation exceptions to callers.
            return TemporalCandidateStatus(False, "CANDIDATE_INVALID", f"Candidate validation failed: {exc}")
        serving = self._manifest["serving"]
        return TemporalCandidateStatus(
            True,
            "READY",
            "Temporal candidate passed manifest, artifact and feature-contract validation.",
            model_name=self._manifest.get("selected_model"),
            model_version=serving.get("model_version"),
            serving_state=serving.get("state"),
            calibrated=self._calibrator is not None,
        )

    def _load(self) -> None:
        if self._model is not None:
            self._validate_active_promotion(self._manifest)
            return
        if not self.manifest_path.is_file():
            raise TemporalCandidateUnavailable(f"Manifest not found: {self.manifest_path}")
        stat = self.manifest_path.stat()
        cache_key = str(self.manifest_path.resolve())
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        artifact_stats: list[int] = []
        for artifact_name in ("model", "high_risk_calibrator"):
            artifact_meta = (manifest.get("artifacts") or {}).get(artifact_name) or {}
            artifact_path = self.manifest_path.parent / str(artifact_meta.get("path", ""))
            try:
                artifact_stat = artifact_path.stat()
                artifact_stats.extend((artifact_stat.st_mtime_ns, artifact_stat.st_size))
            except OSError:
                artifact_stats.extend((-1, -1))
        parity_meta = ((manifest.get("serving") or {}).get("runtime_feature_parity") or {})
        parity_path = self.manifest_path.parent / str(parity_meta.get("report_path", ""))
        try:
            parity_stat = parity_path.stat()
            artifact_stats.extend((parity_stat.st_mtime_ns, parity_stat.st_size))
        except OSError:
            artifact_stats.extend((-1, -1))
        signature = (stat.st_mtime_ns, stat.st_size, *artifact_stats)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] == signature:
                self._manifest, self._model, self._calibrator = cached[1:]
                self._validate_active_promotion(self._manifest)
                return
        serving = manifest.get("serving") or {}
        if serving.get("state") not in ALLOWED_SERVING_STATES:
            raise TemporalCandidateUnavailable(
                "Candidate has not been approved for SHADOW, CANARY or ACTIVE serving."
            )
        if serving.get("state") == "ACTIVE":
            ground_truth_status = ((manifest.get("ground_truth") or {}).get("contract") or {}).get("status")
            if ground_truth_status != "FROZEN_APPROVED":
                raise TemporalCandidateUnavailable(
                    "ACTIVE serving requires a Ground Truth contract approved through the governance process."
                )
            self._validate_active_promotion(manifest)
        if not serving.get("runtime_feature_parity_verified"):
            raise TemporalCandidateUnavailable(
                "Runtime feature parity has not been verified for this candidate."
            )
        parity_meta = serving.get("runtime_feature_parity") or {}
        relative_report_path = str(parity_meta.get("report_path") or "")
        report_path = self.manifest_path.parent / relative_report_path
        if (
            parity_meta.get("schema_version") != "temporal-feature-parity-v1"
            or not relative_report_path
            or Path(relative_report_path).is_absolute()
            or report_path.resolve().parent != self.manifest_path.parent.resolve()
            or not report_path.is_file()
            or parity_meta.get("report_sha256") != _sha256(report_path)
        ):
            raise TemporalCandidateUnavailable(
                "Staged candidate feature-parity evidence is missing, external, or changed."
            )
        try:
            parity_report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise TemporalCandidateUnavailable("Staged candidate feature-parity report is invalid.") from exc
        parity_benchmark = parity_report.get("benchmark") or {}
        parity_contract = parity_report.get("feature_contract") or {}
        comparison = parity_report.get("comparison") or {}
        if (
            parity_report.get("schema_version") != parity_meta.get("schema_version")
            or parity_report.get("status") != "PASSED"
            or int(comparison.get("feature_value_comparisons") or 0) < 1
            or int(comparison.get("mismatch_count") or 0) != 0
            or int(comparison.get("extraction_error_count") or 0) != 0
            or parity_benchmark.get("manifest_sha256") != parity_meta.get("benchmark_manifest_sha256")
            or parity_benchmark.get("source_sha256") != parity_meta.get("source_sha256")
            or parity_contract.get("sha256") != parity_meta.get("feature_contract_sha256")
            or parity_report.get("workspace_id") != parity_meta.get("workspace_id")
            or not isinstance(parity_meta.get("workspace_id"), int)
            or parity_meta.get("workspace_id", 0) < 1
        ):
            raise TemporalCandidateUnavailable("Staged candidate feature-parity evidence does not bind this candidate.")
        if manifest.get("artifact_status") == "STAGED_FOR_GOVERNED_SERVING":
            operating_mode = manifest.get("operating_mode") or {}
            operating_contract = operating_mode.get("contract") or {}
            operating_selection = operating_mode.get("selection") or {}
            relative_policy_path = str(operating_contract.get("path") or "")
            policy_path = self.manifest_path.parent / relative_policy_path
            if (
                not relative_policy_path
                or Path(relative_policy_path).is_absolute()
                or policy_path.resolve().parent != self.manifest_path.parent.resolve()
                or not policy_path.is_file()
                or operating_contract.get("sha256") != _sha256(policy_path)
            ):
                raise TemporalCandidateUnavailable(
                    "Staged candidate operating-mode policy is missing, external, or changed."
                )
            try:
                policy = load_operating_mode_policy(policy_path)
            except (OSError, ValueError) as exc:
                raise TemporalCandidateUnavailable("Staged candidate operating-mode policy is invalid.") from exc
            if (
                policy.get("schema_version") != operating_contract.get("schema_version")
                or operating_selection.get("selection_split") != "validation_only"
                or operating_selection.get("mode") not in policy.get("modes", {})
                or operating_selection.get("selected_model") != manifest.get("selected_model")
            ):
                raise TemporalCandidateUnavailable("Staged candidate operating-mode selection evidence is invalid.")
        contract_meta = manifest.get("feature_contract") or {}
        current_contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        if contract_meta.get("schema_version") != current_contract.get("schema_version"):
            raise TemporalCandidateUnavailable("Candidate feature schema version differs from runtime contract.")
        if contract_meta.get("feature_columns") != current_contract.get("feature_columns"):
            raise TemporalCandidateUnavailable("Candidate feature order differs from runtime contract.")
        if contract_meta.get("class_order") != list(RISK_CLASSES):
            raise TemporalCandidateUnavailable("Candidate class order is invalid.")
        expected_contract_hash = contract_meta.get("sha256")
        if expected_contract_hash and expected_contract_hash != _sha256(CONTRACT_PATH):
            raise TemporalCandidateUnavailable("Feature contract checksum differs from evaluated candidate.")
        if parity_contract.get("sha256") != expected_contract_hash:
            raise TemporalCandidateUnavailable("Feature-parity evidence uses a different feature contract.")
        if parity_contract.get("feature_columns") != contract_meta.get("feature_columns"):
            raise TemporalCandidateUnavailable("Feature-parity evidence uses a different feature-column order.")
        if parity_benchmark.get("source_sha256") != (manifest.get("source") or {}).get("sha256"):
            raise TemporalCandidateUnavailable("Feature-parity evidence uses a different benchmark source.")

        artifacts = manifest.get("artifacts") or {}
        model_meta = artifacts.get("model") or {}
        model_path = self.manifest_path.parent / str(model_meta.get("path", ""))
        if not model_path.is_file():
            raise TemporalCandidateUnavailable("Candidate model artifact is missing.")
        if model_meta.get("sha256") != _sha256(model_path):
            raise TemporalCandidateUnavailable("Candidate model checksum does not match its manifest.")
        try:
            with model_path.open("rb") as handle:
                model = pickle.load(handle)
        except Exception as exc:
            raise TemporalCandidateUnavailable(f"Candidate model cannot be loaded: {exc}") from exc
        if not hasattr(model, "predict_proba") or not hasattr(model, "classes_"):
            raise TemporalCandidateUnavailable("Candidate estimator must expose classes_ and predict_proba().")
        classes = {int(value) for value in model.classes_}
        if classes != set(range(len(RISK_CLASSES))):
            raise TemporalCandidateUnavailable("Candidate estimator classes must contain all required numeric risk codes.")

        calibrator = None
        calibrator_meta = artifacts.get("high_risk_calibrator")
        if calibrator_meta:
            calibrator_path = self.manifest_path.parent / str(calibrator_meta.get("path", ""))
            if not calibrator_path.is_file() or calibrator_meta.get("sha256") != _sha256(calibrator_path):
                raise TemporalCandidateUnavailable("Candidate calibration artifact is missing or changed.")
            with calibrator_path.open("rb") as handle:
                calibrator = pickle.load(handle)
            if not hasattr(calibrator, "transform"):
                raise TemporalCandidateUnavailable("Candidate calibration artifact has no transform() method.")
        self._manifest = manifest
        self._model = model
        self._calibrator = calibrator
        with self._cache_lock:
            self._cache[cache_key] = (signature, manifest, model, calibrator)

    @staticmethod
    def _validate_active_promotion(manifest: dict[str, Any] | None) -> None:
        """Fail closed if the accountable approval is stale or revoked."""
        if not manifest or (manifest.get("serving") or {}).get("state") != "ACTIVE":
            return
        serving = manifest.get("serving") or {}
        approval_meta = serving.get("promotion_approval") or {}
        parity_meta = serving.get("runtime_feature_parity") or {}
        try:
            from supplyforge.models import TemporalCandidatePromotionApproval

            approval = TemporalCandidatePromotionApproval.objects.filter(
                id=approval_meta.get("id"),
                status=TemporalCandidatePromotionApproval.STATUS_APPROVED,
            ).first()
        except Exception as exc:
            raise TemporalCandidateUnavailable("ACTIVE promotion approval cannot be verified.") from exc
        if not approval:
            raise TemporalCandidateUnavailable("ACTIVE promotion approval is missing or has been revoked.")
        if (
            approval.workspace_id != approval_meta.get("workspace_id")
            or approval.workspace_id != parity_meta.get("workspace_id")
            or approval.model_version != serving.get("model_version")
            or approval.benchmark_manifest_sha256 != approval_meta.get("benchmark_manifest_sha256")
            or approval.promotion_policy_sha256 != approval_meta.get("promotion_policy_sha256")
            or approval.shadow_report_sha256 != approval_meta.get("shadow_report_sha256")
            or approval.promotion_policy_sha256 != promotion_policy_sha256(PROMOTION_POLICY_PATH)
        ):
            raise TemporalCandidateUnavailable("ACTIVE promotion approval no longer matches its serving evidence.")

    def predict(self, canonical_sku: str, *, user_id: str, workspace_id: int | None = None, as_of=None) -> dict[str, Any]:
        self._load()
        parity_workspace_id = self._manifest["serving"]["runtime_feature_parity"]["workspace_id"]
        if workspace_id is None or int(workspace_id) != parity_workspace_id:
            raise TemporalCandidateUnavailable(
                "Candidate parity evidence is scoped to a different workspace. Re-run parity before serving this workspace."
            )
        runtime_features = TemporalFeatureService()
        workspace_owner_id = runtime_features.workspace_owner_user_id(workspace_id)
        if str(user_id) != workspace_owner_id:
            raise TemporalCandidateUnavailable(
                "Candidate user scope does not match the parity-verified workspace owner."
            )
        snapshot = runtime_features.extract(
            canonical_sku,
            user_id=workspace_owner_id,
            workspace_id=workspace_id,
            as_of=as_of,
        )
        columns = self._manifest["feature_contract"]["feature_columns"]
        feature_frame = pd.DataFrame(
            [[snapshot.values[name] for name in columns]],
            columns=columns,
            dtype=float,
        )
        raw = self._model.predict_proba(feature_frame)
        probabilities = np.zeros((1, len(RISK_CLASSES)), dtype=float)
        for index, class_code in enumerate(self._model.classes_):
            probabilities[0, int(class_code)] = raw[0, index]
        if not np.isclose(probabilities.sum(), 1.0, atol=0.01):
            raise TemporalCandidateUnavailable("Candidate returned invalid class probabilities.")
        raw_high_risk = float(probabilities[0, 0] + probabilities[0, 1])
        high_risk_probability = raw_high_risk
        if self._calibrator is not None:
            high_risk_probability = float(self._calibrator.transform([raw_high_risk])[0])
        class_code = int(probabilities.argmax(axis=1)[0])
        ground_truth = self._manifest.get("ground_truth") or {}
        ground_truth_contract = ground_truth.get("contract") or {}
        operating_mode = self._manifest.get("operating_mode") or {}
        operating_selection = operating_mode.get("selection") or {}
        thresholds = (self._manifest.get("label_definition") or {}).get("thresholds") or {
            "critical_future_quantity": 0,
            "high_risk_future_quantity_max": 5,
            "medium_risk_future_quantity_max": 25,
        }
        return {
            "risk_class": RISK_CLASSES[class_code],
            "risk_probability": max(0.0, min(1.0, high_risk_probability)),
            "raw_high_risk_probability": raw_high_risk,
            "class_probabilities": {label: float(probabilities[0, index]) for index, label in enumerate(RISK_CLASSES)},
            "model_name": self._manifest.get("selected_model"),
            "model_version": self._manifest["serving"].get("model_version"),
            "serving_state": self._manifest["serving"].get("state"),
            "feature_schema_version": self._manifest["feature_contract"]["schema_version"],
            "ground_truth_schema_version": ground_truth_contract.get("schema_version", ""),
            "ground_truth_status": ground_truth_contract.get("status", ""),
            "ground_truth_thresholds": thresholds,
            "operating_mode": operating_selection.get("mode", "balanced"),
            "decision_cutoff": snapshot.decision_cutoff.isoformat(),
            "feature_values": snapshot.values,
            "data_provenance": {
                "source": "runtime_verified_fulfilled_order_events",
                "canonical_sku": snapshot.canonical_sku,
                "qualifying_order_count": snapshot.qualifying_order_count,
                "parity_workspace_id": parity_workspace_id,
            },
        }

    def get_model_and_contract(self) -> tuple[Any, list[str]]:
        """Return validated components for the separate TreeSHAP explanation path."""
        self._load()
        return self._model, list(self._manifest["feature_contract"]["feature_columns"])
