"""Explicitly stage a reviewed temporal benchmark artifact for controlled serving."""

import json
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import PROJECT_ROOT, file_sha256
from supplyforge.ml.temporal_operating_mode import (
    OperatingModePolicyError,
    load_operating_mode_policy,
)
from supplyforge.services.temporal_feature_parity import REPORT_SCHEMA_VERSION
from supplyforge.services.temporal_promotion_governance import PROMOTION_POLICY_PATH
from supplyforge.models import TemporalCandidatePromotionApproval


class Command(BaseCommand):
    help = (
        "Copy an immutable benchmark candidate into a serving directory. "
        "It never changes an ACTIVE deployment unless --state ACTIVE and --approve-active are both explicit."
    )

    def add_arguments(self, parser):
        parser.add_argument("source_dir", type=Path, help="Benchmark output directory containing model_manifest.json.")
        parser.add_argument(
            "--destination-dir",
            type=Path,
            default=PROJECT_ROOT / "models" / "temporal-demand-risk",
            help="Empty local serving directory.",
        )
        parser.add_argument("--model-version", required=True)
        parser.add_argument("--state", choices=["SHADOW", "CANARY", "ACTIVE"], default="SHADOW")
        parser.add_argument(
            "--parity-report",
            type=Path,
            help="Immutable PASSED report created by verify_temporal_feature_parity for this exact benchmark.",
        )
        parser.add_argument(
            "--runtime-feature-parity-verified",
            action="store_true",
            help="Deprecated and unsafe. Use --parity-report instead.",
        )
        parser.add_argument(
            "--approve-active",
            action="store_true",
            help="Required in addition to --state ACTIVE to make the candidate eligible for primary routing.",
        )
        parser.add_argument(
            "--promotion-approval-id",
            help="Required approved SHADOW promotion record for ACTIVE serving.",
        )

    def handle(self, *args, **options):
        source_dir = options["source_dir"].resolve()
        destination = options["destination_dir"].resolve()
        manifest_path = source_dir / "model_manifest.json"
        if not manifest_path.is_file():
            raise CommandError(f"Benchmark manifest not found: {manifest_path}")
        if destination.exists() and any(destination.iterdir()):
            raise CommandError(f"Destination must be empty to preserve artifact immutability: {destination}")
        if options["state"] == "ACTIVE" and not options["approve_active"]:
            raise CommandError("ACTIVE requires --approve-active after governance review.")
        if options["state"] == "ACTIVE" and not options["promotion_approval_id"]:
            raise CommandError("ACTIVE requires --promotion-approval-id from approve_temporal_candidate_promotion.")
        if options["runtime_feature_parity_verified"]:
            raise CommandError(
                "A boolean parity attestation is no longer accepted. Supply --parity-report produced by "
                "verify_temporal_feature_parity."
            )
        if not options["parity_report"]:
            raise CommandError("All serving states require a --parity-report with status PASSED.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("artifact_status") != "EVALUATION_CANDIDATE_ONLY":
            raise CommandError("Source artifact is not an evaluation candidate produced by the temporal benchmark.")
        for artifact_name in ("model", "high_risk_calibrator"):
            meta = (manifest.get("artifacts") or {}).get(artifact_name) or {}
            source_artifact = source_dir / str(meta.get("path", ""))
            if not source_artifact.is_file() or file_sha256(source_artifact) != meta.get("sha256"):
                raise CommandError(f"Invalid {artifact_name} checksum in source benchmark output.")

        # Ground-truth evidence is not needed for inference, but retaining it
        # beside a staged candidate keeps the target policy auditable later.
        ground_truth = manifest.get("ground_truth") or {}
        ground_truth_files: list[Path] = []
        if ground_truth:
            ground_truth_contract = ground_truth.get("contract") or {}
            contract_path = Path(str(ground_truth_contract.get("path", "")))
            expected_hash = ground_truth_contract.get("sha256")
            if not contract_path.is_file() or not expected_hash or file_sha256(contract_path) != expected_hash:
                raise CommandError("Ground Truth contract is missing or its checksum does not match the benchmark manifest.")
            ground_truth_files.append(contract_path)
            report_files = {"ground_truth_validation.json", *(ground_truth.get("artifacts") or {}).values()}
            for filename in report_files:
                report_path = source_dir / str(filename)
                if report_path.parent != source_dir or not report_path.is_file():
                    raise CommandError(f"Ground Truth evidence file is missing or invalid: {filename}")
                ground_truth_files.append(report_path)
        if options["state"] == "ACTIVE":
            contract_status = (ground_truth.get("contract") or {}).get("status")
            if contract_status != "FROZEN_APPROVED":
                raise CommandError(
                    "ACTIVE serving requires a Ground Truth contract with status FROZEN_APPROVED. "
                    "A candidate or pending target policy may only be staged in SHADOW or CANARY."
                )

        operating_mode = manifest.get("operating_mode") or {}
        operating_contract = operating_mode.get("contract") or {}
        operating_selection = operating_mode.get("selection") or {}
        operating_policy_path = Path(str(operating_contract.get("path", "")))
        expected_operating_hash = operating_contract.get("sha256")
        if not operating_policy_path.is_file() or not expected_operating_hash:
            raise CommandError("Operating-mode policy is missing from the benchmark manifest.")
        if file_sha256(operating_policy_path) != expected_operating_hash:
            raise CommandError("Operating-mode policy checksum does not match the benchmark manifest.")
        try:
            operating_policy = load_operating_mode_policy(operating_policy_path)
        except (OSError, ValueError, OperatingModePolicyError) as exc:
            raise CommandError(f"Operating-mode policy is invalid: {exc}") from exc
        if operating_contract.get("schema_version") != operating_policy["schema_version"]:
            raise CommandError("Operating-mode policy schema does not match the benchmark manifest.")
        if operating_selection.get("selection_split") != "validation_only":
            raise CommandError("Candidate selection must be based on validation_only metrics.")
        if operating_selection.get("mode") not in operating_policy["modes"]:
            raise CommandError("Candidate operating mode is not defined by its policy.")
        if operating_selection.get("selected_model") != manifest.get("selected_model"):
            raise CommandError("Operating-mode selection does not match the selected model artifact.")

        parity_report_path = options["parity_report"].resolve()
        if not parity_report_path.is_file():
            raise CommandError(f"Feature parity report not found: {parity_report_path}")
        try:
            parity_report = json.loads(parity_report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError("Feature parity report is not valid JSON.") from exc
        parity_benchmark = parity_report.get("benchmark") or {}
        parity_contract = parity_report.get("feature_contract") or {}
        comparison = parity_report.get("comparison") or {}
        expected_manifest_sha = file_sha256(manifest_path)
        if parity_report.get("schema_version") != REPORT_SCHEMA_VERSION or parity_report.get("status") != "PASSED":
            raise CommandError("Feature parity report must use the current schema and have status PASSED.")
        if parity_benchmark.get("manifest_sha256") != expected_manifest_sha:
            raise CommandError("Feature parity report was generated for a different benchmark manifest.")
        if parity_benchmark.get("source_sha256") != (manifest.get("source") or {}).get("sha256"):
            raise CommandError("Feature parity report source checksum does not match the benchmark manifest.")
        if parity_contract.get("sha256") != (manifest.get("feature_contract") or {}).get("sha256"):
            raise CommandError("Feature parity report feature-contract checksum does not match the benchmark manifest.")
        if parity_contract.get("feature_columns") != (manifest.get("feature_contract") or {}).get("feature_columns"):
            raise CommandError("Feature parity report feature-column order does not match the benchmark manifest.")
        if int(comparison.get("feature_value_comparisons") or 0) < 1:
            raise CommandError("Feature parity report contains no feature comparisons.")
        if int(comparison.get("mismatch_count") or 0) != 0 or int(comparison.get("extraction_error_count") or 0) != 0:
            raise CommandError("Feature parity report contains mismatches or runtime extraction errors.")
        try:
            parity_workspace_id = int(parity_report.get("workspace_id"))
        except (TypeError, ValueError) as exc:
            raise CommandError("Feature parity report must bind a positive workspace_id.") from exc
        if parity_workspace_id < 1:
            raise CommandError("Feature parity report must bind a positive workspace_id.")

        promotion_approval = None
        if options["state"] == "ACTIVE":
            promotion_approval = TemporalCandidatePromotionApproval.objects.filter(
                id=options["promotion_approval_id"],
                status=TemporalCandidatePromotionApproval.STATUS_APPROVED,
            ).first()
            if not promotion_approval:
                raise CommandError("Promotion approval is missing or revoked.")
            if (
                promotion_approval.workspace_id != parity_workspace_id
                or promotion_approval.model_version != options["model_version"]
                or promotion_approval.selected_model != manifest.get("selected_model")
                or promotion_approval.benchmark_manifest_sha256 != expected_manifest_sha
                or promotion_approval.source_sha256 != parity_benchmark.get("source_sha256")
                or promotion_approval.feature_contract_sha256 != parity_contract.get("sha256")
                or promotion_approval.promotion_policy_sha256 != file_sha256(PROMOTION_POLICY_PATH)
            ):
                raise CommandError("Promotion approval does not bind this workspace, model, benchmark, policy, or parity evidence.")

        destination.mkdir(parents=True, exist_ok=True)
        for meta in manifest["artifacts"].values():
            source_artifact = source_dir / meta["path"]
            shutil.copy2(source_artifact, destination / meta["path"])
        if ground_truth_files:
            for source_file in ground_truth_files:
                destination_name = "ground_truth_contract.json" if source_file == Path(ground_truth["contract"]["path"]) else source_file.name
                shutil.copy2(source_file, destination / destination_name)
            manifest["ground_truth"]["contract"]["path"] = "ground_truth_contract.json"
        shutil.copy2(operating_policy_path, destination / "operating_mode_policy.json")
        manifest["operating_mode"]["contract"]["path"] = "operating_mode_policy.json"
        staged_parity_report = destination / "temporal_feature_parity_report.json"
        shutil.copy2(parity_report_path, staged_parity_report)
        manifest["artifact_status"] = "STAGED_FOR_GOVERNED_SERVING"
        manifest["serving"] = {
            "state": options["state"],
            "model_version": options["model_version"],
            "runtime_feature_parity_verified": True,
            "runtime_feature_parity": {
                "schema_version": REPORT_SCHEMA_VERSION,
                "report_path": staged_parity_report.name,
                "report_sha256": file_sha256(staged_parity_report),
                "benchmark_manifest_sha256": expected_manifest_sha,
                "source_sha256": parity_benchmark["source_sha256"],
                "feature_contract_sha256": parity_contract["sha256"],
                "workspace_id": parity_workspace_id,
            },
        }
        if promotion_approval:
            manifest["serving"]["promotion_approval"] = {
                "id": str(promotion_approval.id),
                "workspace_id": promotion_approval.workspace_id,
                "model_version": promotion_approval.model_version,
                "benchmark_manifest_sha256": promotion_approval.benchmark_manifest_sha256,
                "promotion_policy_sha256": promotion_approval.promotion_policy_sha256,
                "shadow_report_sha256": promotion_approval.shadow_report_sha256,
                "approval_reference": promotion_approval.approval_reference,
            }
        (destination / "model_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(
            f"Staged temporal candidate {options['model_version']} in {destination} with state {options['state']}."
        ))
