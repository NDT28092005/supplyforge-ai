"""Print a policy-bound slow-moving quality report."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService


class Command(BaseCommand):
    help = 'Report mature 60-day quality gates for one slow-moving operational source.'

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', type=int, required=True)
        parser.add_argument('--source', default='CSV')
        parser.add_argument('--output', type=Path, help='Optional JSON report destination.')

    def handle(self, *args, **options):
        report = SlowMovingQualityMonitoringService.report(
            workspace_id=options['workspace_id'], source_key=str(options['source']).upper(),
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        output = options.get('output')
        if output:
            output = output.resolve()
            if output.exists():
                raise CommandError(f'Refusing to overwrite existing report: {output}')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized, encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'Wrote slow-moving quality report: {output}'))
        self.stdout.write(serialized)
