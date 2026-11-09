"""Mature and report governed temporal SHADOW/CANARY prediction cohorts."""

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from supplyforge.services.temporal_shadow_monitoring import TemporalShadowMonitoringService


class Command(BaseCommand):
    help = (
        "Mature 60-day temporal SHADOW/CANARY outcomes and report cohort-blocked "
        "precision, recall, calibration, prediction-score drift, and Precision@5%."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int)
        parser.add_argument("--model-version")
        parser.add_argument(
            "--as-of",
            help="Optional ISO-8601 timestamp for deterministic backfills; defaults to now.",
        )
        parser.add_argument("--output", type=Path, help="Optional JSON report destination.")

    def handle(self, *args, **options):
        as_of = None
        if options.get("as_of"):
            try:
                as_of = datetime.fromisoformat(options["as_of"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise CommandError("--as-of must be an ISO-8601 timestamp") from exc
            if timezone.is_naive(as_of):
                as_of = timezone.make_aware(as_of, timezone.get_current_timezone())
        maturity = TemporalShadowMonitoringService.mature_outcomes(
            workspace_id=options.get("workspace_id"),
            as_of=as_of,
        )
        report = {
            "generated_at": (as_of or timezone.now()).isoformat(),
            "maturity": maturity,
            "quality": TemporalShadowMonitoringService.quality_report(
                workspace_id=options.get("workspace_id"),
                model_version=options.get("model_version"),
            ),
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        output = options.get("output")
        if output:
            output = output.resolve()
            if output.exists():
                raise CommandError(f"Refusing to overwrite existing report: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote temporal SHADOW report: {output}"))
        self.stdout.write(serialized)
