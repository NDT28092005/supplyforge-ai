"""Report observed versus missing action-plan outcomes."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.services.action_outcome_reporting import ActionOutcomeEvidenceService


class Command(BaseCommand):
    help = "Report merchant-recorded completed action outcomes without asserting causal impact."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, required=True)
        parser.add_argument("--output", type=Path, help="Optional new JSON destination; existing files are preserved.")

    def handle(self, *args, **options):
        report = ActionOutcomeEvidenceService.report(workspace_id=options["workspace_id"])
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        output = options.get("output")
        if output:
            output = output.resolve()
            if output.exists():
                raise CommandError(f"Refusing to overwrite report: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote action outcome report: {output}"))
        self.stdout.write(serialized)
