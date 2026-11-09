"""Create an explicitly approved immutable Ground Truth contract from benchmark evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import file_sha256, load_ground_truth_contract


class Command(BaseCommand):
    help = (
        "Create a new FROZEN_APPROVED Ground Truth contract from a completed temporal benchmark. "
        "It never changes the source contract or activates a model."
    )

    def add_arguments(self, parser):
        parser.add_argument("benchmark_dir", type=Path, help="Completed benchmark output directory.")
        parser.add_argument("--output-contract", type=Path, required=True, help="New, non-existent approved contract path.")
        parser.add_argument("--approved-by", required=True, help="Named accountable reviewer or governance role.")
        parser.add_argument("--approval-reference", required=True, help="Review, ticket, or experiment reference.")
        parser.add_argument(
            "--approve",
            action="store_true",
            help="Required acknowledgement that this freezes the target policy for a new benchmark run.",
        )

    def handle(self, *args, **options):
        if not options["approve"]:
            raise CommandError("Refusing to freeze Ground Truth without --approve.")
        benchmark_dir = options["benchmark_dir"].resolve()
        output_contract = options["output_contract"].resolve()
        manifest_path = benchmark_dir / "model_manifest.json"
        validation_path = benchmark_dir / "ground_truth_validation.json"
        if not manifest_path.is_file() or not validation_path.is_file():
            raise CommandError("Benchmark directory must contain model_manifest.json and ground_truth_validation.json.")
        if output_contract.exists():
            raise CommandError("Output contract must not already exist; create a new version rather than overwrite one.")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        contract_meta = ((manifest.get("ground_truth") or {}).get("contract") or {})
        source_contract_path = Path(str(contract_meta.get("path", "")))
        expected_hash = str(contract_meta.get("sha256", ""))
        if not source_contract_path.is_file() or not expected_hash:
            raise CommandError("Benchmark manifest has no verifiable Ground Truth contract.")
        if file_sha256(source_contract_path) != expected_hash:
            raise CommandError("Source Ground Truth contract checksum differs from the benchmark manifest.")

        contract = load_ground_truth_contract(source_contract_path)
        if contract.get("status") == "FROZEN_APPROVED":
            raise CommandError("Source contract is already approved. Use it directly or create a reviewed successor version.")
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        if validation.get("selected_strategy") != contract["selected_strategy"]["id"]:
            raise CommandError("Validation evidence does not match the selected Ground Truth strategy.")
        if not validation.get("strategy_comparison_by_split") or not validation.get("discriminability_by_split"):
            raise CommandError("Benchmark Ground Truth validation is incomplete; it lacks strategy or discriminability evidence.")

        approved = dict(contract)
        approved["status"] = "FROZEN_APPROVED"
        approved["approval"] = {
            "approved_at_utc": datetime.now(timezone.utc).isoformat(),
            "approved_by": options["approved_by"].strip(),
            "approval_reference": options["approval_reference"].strip(),
            "source_contract_sha256": expected_hash,
            "source_benchmark_manifest_sha256": file_sha256(manifest_path),
            "ground_truth_validation_sha256": file_sha256(validation_path),
            "required_next_step": "Run a new temporal benchmark using this contract before staging ACTIVE serving.",
        }
        output_contract.parent.mkdir(parents=True, exist_ok=True)
        output_contract.write_text(json.dumps(approved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Created approved Ground Truth contract at {output_contract}. Run a new benchmark with --ground-truth-contract before ACTIVE staging."
        ))
