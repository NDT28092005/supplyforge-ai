"""Create a governed, revocable approval for ACTIVE temporal serving."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import file_sha256
from supplyforge.models import TemporalCandidatePromotionApproval, Workspace
from supplyforge.services.temporal_promotion_governance import (
    PROMOTION_POLICY_PATH,
    PromotionGovernanceError,
    TemporalPromotionGovernanceService,
    load_promotion_policy,
)


class Command(BaseCommand):
    help = "Approve a mature SHADOW candidate for later ACTIVE staging; it does not deploy a model."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, required=True)
        parser.add_argument("--benchmark-dir", type=Path, required=True)
        parser.add_argument("--shadow-report", type=Path, required=True)
        parser.add_argument("--model-version", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--approval-reference", required=True)
        parser.add_argument("--policy", type=Path, default=PROMOTION_POLICY_PATH)
        parser.add_argument("--approve", action="store_true")

    def handle(self, *args, **options):
        if not options["approve"]:
            raise CommandError("Refusing to create promotion approval without --approve.")
        workspace = Workspace.objects.filter(id=options["workspace_id"]).first()
        if not workspace:
            raise CommandError("Workspace does not exist.")
        benchmark_dir = options["benchmark_dir"].resolve()
        manifest_path = benchmark_dir / "model_manifest.json"
        shadow_path = options["shadow_report"].resolve()
        if not manifest_path.is_file() or not shadow_path.is_file():
            raise CommandError("Benchmark manifest and immutable SHADOW report must both exist.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            shadow_report = json.loads(shadow_path.read_text(encoding="utf-8"))
            policy = load_promotion_policy(options["policy"].resolve())
            evaluation = TemporalPromotionGovernanceService.evaluate_shadow_report(
                report=shadow_report,
                workspace_id=workspace.id,
                model_version=options["model_version"],
                policy=policy,
            )
        except (OSError, ValueError, json.JSONDecodeError, PromotionGovernanceError) as exc:
            raise CommandError(str(exc)) from exc
        if manifest.get("artifact_status") != "EVALUATION_CANDIDATE_ONLY":
            raise CommandError("Promotion approval requires a benchmark evaluation candidate manifest.")
        ground_truth = (manifest.get("ground_truth") or {}).get("contract") or {}
        if ground_truth.get("status") != "FROZEN_APPROVED":
            raise CommandError("Promotion approval requires a benchmark run with FROZEN_APPROVED Ground Truth.")
        if not evaluation["eligible"]:
            failed = [check["name"] for check in evaluation["checks"] if not check["passed"]]
            raise CommandError(f"SHADOW promotion policy is not met: {', '.join(failed)}")
        benchmark_sha = file_sha256(manifest_path)
        if TemporalCandidatePromotionApproval.objects.filter(
            workspace=workspace, model_version=options["model_version"], benchmark_manifest_sha256=benchmark_sha,
        ).exists():
            raise CommandError("A promotion approval already exists for this workspace, model version, and benchmark.")
        feature_contract = manifest.get("feature_contract") or {}
        source = manifest.get("source") or {}
        try:
            approval = TemporalCandidatePromotionApproval.objects.create(
                workspace=workspace,
                model_version=options["model_version"],
                selected_model=str(manifest.get("selected_model") or ""),
                benchmark_manifest_sha256=benchmark_sha,
                source_sha256=str(source["sha256"]),
                feature_contract_sha256=str(feature_contract["sha256"]),
                promotion_policy_sha256=file_sha256(options["policy"].resolve()),
                shadow_report_sha256=file_sha256(shadow_path),
                shadow_quality_json=evaluation,
                approved_by=options["approved_by"].strip(),
                approval_reference=options["approval_reference"].strip(),
            )
        except KeyError as exc:
            raise CommandError("Benchmark manifest is missing source or feature-contract checksum evidence.") from exc
        self.stdout.write(self.style.SUCCESS(
            f"Approved temporal promotion {approval.id}. Use --promotion-approval-id {approval.id} only after ACTIVE staging review."
        ))
