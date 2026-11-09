"""Offline/runtime feature-parity evidence for temporal demand candidates.

Parity is deliberately a separate, immutable report.  A boolean supplied at
staging time is not evidence that the exact benchmark source and runtime ORM
events produce the same 19-feature vector at the same decision cutoffs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from django.utils import timezone

from supplyforge.models import TemporalDemandSourceImport
from supplyforge.services.temporal_feature_service import (
    CONTRACT_PATH,
    FeatureContractIncomplete,
    TemporalFeatureService,
)


REPORT_SCHEMA_VERSION = "temporal-feature-parity-v1"


class FeatureParityVerificationError(ValueError):
    """Raised where a parity evaluation cannot be trusted or reproduced."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _evenly_spaced(values: list[Any], limit: int) -> list[Any]:
    if limit < 1:
        raise FeatureParityVerificationError("Sample limits must be positive.")
    if len(values) <= limit:
        return values
    positions = np.linspace(0, len(values) - 1, num=limit, dtype=int).tolist()
    return [values[position] for position in dict.fromkeys(positions)]


@dataclass(frozen=True)
class ParityConfiguration:
    splits: tuple[str, ...] = ("train", "validation", "test")
    cutoffs_per_split: int = 2
    skus_per_cutoff: int = 20
    absolute_tolerance: float = 1e-8
    relative_tolerance: float = 1e-8


class TemporalFeatureParityService:
    """Compare benchmark snapshots with live contract extraction deterministically."""

    @staticmethod
    def _load_manifest(benchmark_dir: Path) -> tuple[Path, dict[str, Any]]:
        manifest_path = benchmark_dir / "model_manifest.json"
        if not manifest_path.is_file():
            raise FeatureParityVerificationError(f"Benchmark manifest not found: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise FeatureParityVerificationError("Benchmark manifest is not valid JSON.") from exc
        if manifest.get("artifact_status") != "EVALUATION_CANDIDATE_ONLY":
            raise FeatureParityVerificationError("Parity can only attest a benchmark evaluation candidate.")
        return manifest_path, manifest

    @staticmethod
    def _validate_contract(manifest: dict[str, Any]) -> tuple[list[str], str]:
        current_hash = file_sha256(CONTRACT_PATH)
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        feature_contract = manifest.get("feature_contract") or {}
        expected_features = feature_contract.get("feature_columns")
        if feature_contract.get("sha256") != current_hash:
            raise FeatureParityVerificationError(
                "The benchmark feature-contract checksum differs from the runtime contract. Re-benchmark first."
            )
        if expected_features != contract.get("feature_columns"):
            raise FeatureParityVerificationError(
                "The benchmark feature-column order differs from the runtime contract."
            )
        return list(expected_features), current_hash

    @staticmethod
    def _current_source_import(workspace_id: int, source_sha256: str, contract_sha256: str) -> TemporalDemandSourceImport:
        source_import = (
            TemporalDemandSourceImport.objects.filter(workspace_id=workspace_id, is_current=True)
            .order_by("-imported_at")
            .first()
        )
        if not source_import:
            raise FeatureParityVerificationError(
                "No current verified temporal source import exists for this workspace. Import the benchmark source first."
            )
        if source_import.source_sha256 != source_sha256:
            raise FeatureParityVerificationError(
                "The current runtime source checksum differs from the benchmark source checksum."
            )
        if source_import.feature_contract_sha256 != contract_sha256:
            raise FeatureParityVerificationError(
                "The current runtime source was imported under a different feature contract. Re-import it first."
            )
        return source_import

    @classmethod
    def verify(
        cls,
        *,
        workspace_id: int,
        benchmark_dir: Path,
        source: Path,
        configuration: ParityConfiguration = ParityConfiguration(),
    ) -> dict[str, Any]:
        """Produce an in-memory report; callers decide where immutable evidence lives."""
        benchmark_dir = Path(benchmark_dir).resolve()
        source = Path(source).resolve()
        if not source.is_file():
            raise FeatureParityVerificationError(f"Source archive not found: {source}")
        if configuration.absolute_tolerance < 0 or configuration.relative_tolerance < 0:
            raise FeatureParityVerificationError("Feature comparison tolerances cannot be negative.")

        manifest_path, manifest = cls._load_manifest(benchmark_dir)
        feature_columns, contract_sha256 = cls._validate_contract(manifest)
        source_sha256 = file_sha256(source)
        benchmark_source = manifest.get("source") or {}
        if benchmark_source.get("sha256") != source_sha256:
            raise FeatureParityVerificationError(
                "The provided source archive checksum differs from the benchmark manifest."
            )
        source_import = cls._current_source_import(workspace_id, source_sha256, contract_sha256)

        snapshots_path = benchmark_dir / "risk_snapshots.parquet"
        if not snapshots_path.is_file():
            raise FeatureParityVerificationError(f"Benchmark snapshots not found: {snapshots_path}")
        required_columns = {"split", "cutoff", "sku", *feature_columns}
        snapshots = pd.read_parquet(snapshots_path, columns=sorted(required_columns))
        missing = sorted(required_columns.difference(snapshots.columns))
        if missing:
            raise FeatureParityVerificationError(f"Benchmark snapshot file is missing fields: {missing}")
        requested_splits = tuple(dict.fromkeys(str(split).strip() for split in configuration.splits if str(split).strip()))
        allowed_splits = {"train", "validation", "test"}
        if not requested_splits or set(requested_splits).difference(allowed_splits):
            raise FeatureParityVerificationError("Parity splits must be chosen from train, validation, and test.")
        snapshots = snapshots.loc[snapshots["split"].isin(requested_splits)].copy()
        if snapshots.empty:
            raise FeatureParityVerificationError("No benchmark snapshots match the requested parity splits.")
        snapshots["cutoff"] = pd.to_datetime(snapshots["cutoff"], errors="coerce")
        snapshots = snapshots.dropna(subset=["cutoff", "sku"])

        runtime = TemporalFeatureService()
        owner_user_id = runtime.workspace_owner_user_id(workspace_id)
        comparisons = 0
        mismatch_count = 0
        extraction_errors: list[dict[str, str]] = []
        mismatch_evidence: list[dict[str, Any]] = []
        sampled_pairs: list[dict[str, Any]] = []
        evaluated_cutoffs: dict[str, list[str]] = {}

        for split in requested_splits:
            split_frame = snapshots.loc[snapshots["split"].eq(split)]
            cutoffs = sorted(split_frame["cutoff"].drop_duplicates().tolist())
            selected_cutoffs = _evenly_spaced(cutoffs, configuration.cutoffs_per_split)
            evaluated_cutoffs[split] = [pd.Timestamp(cutoff).date().isoformat() for cutoff in selected_cutoffs]
            for cutoff in selected_cutoffs:
                cutoff_frame = split_frame.loc[split_frame["cutoff"].eq(cutoff)].sort_values("sku", kind="stable")
                selected_indices = _evenly_spaced(list(cutoff_frame.index), configuration.skus_per_cutoff)
                for index in selected_indices:
                    row = cutoff_frame.loc[index]
                    sku = str(row["sku"])
                    sampled_pairs.append({"split": split, "cutoff": pd.Timestamp(cutoff).date().isoformat(), "sku": sku})
                    try:
                        snapshot = runtime.extract(
                            sku,
                            user_id=owner_user_id,
                            workspace_id=workspace_id,
                            as_of=pd.Timestamp(cutoff).to_pydatetime(),
                        )
                    except FeatureContractIncomplete as exc:
                        extraction_errors.append({
                            "split": split,
                            "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                            "sku": sku,
                            "error": str(exc),
                        })
                        continue
                    for feature in feature_columns:
                        comparisons += 1
                        expected = float(row[feature])
                        actual = float(snapshot.values[feature])
                        if not np.isclose(
                            actual,
                            expected,
                            atol=configuration.absolute_tolerance,
                            rtol=configuration.relative_tolerance,
                            equal_nan=False,
                        ):
                            mismatch_count += 1
                            if len(mismatch_evidence) < 100:
                                mismatch_evidence.append({
                                    "split": split,
                                    "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                                    "sku": sku,
                                    "feature": feature,
                                    "offline_value": expected,
                                    "runtime_value": actual,
                                    "absolute_difference": abs(actual - expected),
                                })

        status = "PASSED" if comparisons and not mismatch_count and not extraction_errors else "FAILED"
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": status,
            "generated_at": timezone.now().isoformat(),
            "workspace_id": workspace_id,
            "benchmark": {
                "directory": str(benchmark_dir),
                "manifest_sha256": file_sha256(manifest_path),
                "selected_model": manifest.get("selected_model"),
                "source_sha256": source_sha256,
            },
            "runtime_source_import": {
                "id": str(source_import.id),
                "source_name": source_import.source_name,
                "source_sha256": source_import.source_sha256,
                "imported_at": source_import.imported_at.isoformat(),
            },
            "feature_contract": {
                "path": str(CONTRACT_PATH),
                "schema_version": runtime.contract.get("schema_version"),
                "sha256": contract_sha256,
                "feature_columns": feature_columns,
            },
            "sample_policy": {
                "splits": list(requested_splits),
                "cutoffs_per_split": configuration.cutoffs_per_split,
                "skus_per_cutoff": configuration.skus_per_cutoff,
                "absolute_tolerance": configuration.absolute_tolerance,
                "relative_tolerance": configuration.relative_tolerance,
            },
            "evaluated_cutoffs": evaluated_cutoffs,
            "sampled_pairs": sampled_pairs,
            "comparison": {
                "feature_value_comparisons": comparisons,
                "mismatch_count": mismatch_count,
                "extraction_error_count": len(extraction_errors),
            },
            "mismatch_evidence": mismatch_evidence,
            "extraction_errors": extraction_errors[:100],
            "attestation": (
                "PASSED means sampled offline snapshots and runtime extraction matched under the recorded source "
                "and feature contract; it is not a production-quality or business-impact claim."
            ),
        }

    @staticmethod
    def write_report(report: dict[str, Any], destination: Path) -> Path:
        destination = Path(destination).resolve()
        if destination.exists():
            raise FeatureParityVerificationError(
                f"Refusing to overwrite parity evidence: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return destination
