"""Import the approved orders_full export for live temporal feature parity."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.ml.temporal_benchmark import PROJECT_ROOT
from supplyforge.services.temporal_source_ingestion import TemporalSourceIngestionService


class Command(BaseCommand):
    help = (
        "Import verified fulfilled demand events from orders_full.zip without buyer PII. "
        "This is separate from the permissive merchant CSV importer."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, required=True)
        parser.add_argument(
            "--source",
            type=Path,
            default=PROJECT_ROOT / "test-data" / "Database - NCKH" / "orders_full.zip",
        )
        parser.add_argument("--chunk-size", type=int, default=20_000)
        parser.add_argument(
            "--replace-existing-source",
            action="store_true",
            help="Delete only prior orders_full_temporal orders for this workspace owner before import.",
        )

    def handle(self, *args, **options):
        try:
            summary = TemporalSourceIngestionService.import_zip(
                source=options["source"],
                workspace_id=options["workspace_id"],
                replace_existing_source=options["replace_existing_source"],
                chunk_size=options["chunk_size"],
            )
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            "Imported verified temporal source: "
            f"{summary.retained_orders:,} orders, {summary.retained_items:,} item lines, "
            f"{summary.created_products:,} products. "
            f"Skipped {summary.skipped_orders:,} orders and {summary.skipped_items:,} items."
        ))
