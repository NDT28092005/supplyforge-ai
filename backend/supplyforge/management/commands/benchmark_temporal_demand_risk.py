"""Run the versioned temporal-demand benchmark against a supplied order export."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import GROUND_TRUTH_CONTRACT_PATH, PROJECT_ROOT, main
from supplyforge.ml.temporal_operating_mode import OPERATING_MODE_POLICY_PATH


class Command(BaseCommand):
    help = (
        "Evaluate the time-safe fulfilled-demand risk candidates. "
        "This command creates an evaluation candidate only; it never promotes a model."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=Path,
            default=PROJECT_ROOT / "test-data" / "Database - NCKH" / "orders_full.zip",
            help="ZIP export containing exactly one orders CSV.",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            required=True,
            help="Empty directory where the immutable evaluation artifacts are written.",
        )
        parser.add_argument("--chunk-size", type=int, default=20_000)
        parser.add_argument(
            "--ground-truth-contract",
            type=Path,
            default=GROUND_TRUTH_CONTRACT_PATH,
            help="Versioned Ground Truth policy used for target-validation artifacts.",
        )
        parser.add_argument(
            "--operating-mode-policy",
            type=Path,
            default=OPERATING_MODE_POLICY_PATH,
            help="Versioned validation-only model-selection policy.",
        )
        parser.add_argument(
            "--operating-mode",
            default="balanced",
            help="Declared operating mode from the selection policy.",
        )

    def handle(self, *args, **options):
        source = options["source"].resolve()
        output_dir = options["output_dir"].resolve()
        ground_truth_contract = options["ground_truth_contract"].resolve()
        if not source.is_file():
            raise CommandError(f"Source ZIP does not exist: {source}")
        if output_dir.exists():
            raise CommandError(f"Output directory must not already exist: {output_dir}")
        if not ground_truth_contract.is_file():
            raise CommandError(f"Ground Truth contract does not exist: {ground_truth_contract}")

        exit_code = main(
            [
                "--source", str(source),
                "--output-dir", str(output_dir),
                "--chunk-size", str(options["chunk_size"]),
                "--ground-truth-contract", str(ground_truth_contract),
                "--operating-mode-policy", str(options["operating_mode_policy"].resolve()),
                "--operating-mode", str(options["operating_mode"]),
            ]
        )
        if exit_code:
            raise CommandError(f"Temporal benchmark failed with exit code {exit_code}")
