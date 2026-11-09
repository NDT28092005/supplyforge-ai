"""Create immutable offline/runtime feature-parity evidence."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import PROJECT_ROOT
from supplyforge.services.temporal_feature_parity import (
    FeatureParityVerificationError,
    ParityConfiguration,
    TemporalFeatureParityService,
)


class Command(BaseCommand):
    help = (
        "Compare sampled benchmark risk_snapshots.parquet vectors with runtime ORM feature extraction. "
        "A PASSED report is required before a temporal candidate can be staged for serving."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, required=True)
        parser.add_argument("--benchmark-dir", type=Path, required=True)
        parser.add_argument(
            "--source",
            type=Path,
            default=PROJECT_ROOT / "test-data" / "Database - NCKH" / "orders_full.zip",
            help="The exact archive used by the benchmark and imported for the selected workspace.",
        )
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--splits", default="train,validation,test")
        parser.add_argument("--cutoffs-per-split", type=int, default=2)
        parser.add_argument("--skus-per-cutoff", type=int, default=20)
        parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
        parser.add_argument("--relative-tolerance", type=float, default=1e-8)

    def handle(self, *args, **options):
        configuration = ParityConfiguration(
            splits=tuple(part.strip() for part in options["splits"].split(",") if part.strip()),
            cutoffs_per_split=options["cutoffs_per_split"],
            skus_per_cutoff=options["skus_per_cutoff"],
            absolute_tolerance=options["absolute_tolerance"],
            relative_tolerance=options["relative_tolerance"],
        )
        try:
            report = TemporalFeatureParityService.verify(
                workspace_id=options["workspace_id"],
                benchmark_dir=options["benchmark_dir"],
                source=options["source"],
                configuration=configuration,
            )
            output = TemporalFeatureParityService.write_report(report, options["output"])
        except (FeatureParityVerificationError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] != "PASSED":
            raise CommandError(f"Feature parity failed. Evidence was written to {output}")
        self.stdout.write(self.style.SUCCESS(f"Feature parity passed. Immutable report: {output}"))
