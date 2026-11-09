"""Reconcile completed action plans from provider-neutral ERP daily facts."""

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from supplyforge.services.action_outcome_reconciliation import ActionOutcomeReconciliationService


class Command(BaseCommand):
    help = "Create read-only ERP observations for completed action plans without overwriting merchant outcomes."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, required=True)
        parser.add_argument("--as-of", help="YYYY-MM-DD; defaults to local current date.")
        parser.add_argument("--output", type=Path, help="Optional new JSON destination.")

    def handle(self, *args, **options):
        try:
            as_of = date.fromisoformat(options["as_of"]) if options.get("as_of") else timezone.localdate()
        except ValueError as exc:
            raise CommandError("--as-of must use YYYY-MM-DD") from exc
        report = ActionOutcomeReconciliationService.reconcile_workspace(
            workspace_id=options["workspace_id"], as_of=as_of
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        output = options.get("output")
        if output:
            output = output.resolve()
            if output.exists():
                raise CommandError(f"Refusing to overwrite report: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote action-outcome reconciliation report: {output}"))
        self.stdout.write(serialized)
