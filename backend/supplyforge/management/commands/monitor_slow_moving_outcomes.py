"""Mature slow-moving outcomes without changing the deployed rule."""

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from supplyforge.services.slow_moving_outcomes import SlowMovingOutcomeService


class Command(BaseCommand):
    help = 'Mature 30/60/90-day slow-moving future-demand outcomes after their grace period.'

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', type=int)
        parser.add_argument('--as-of', help='ISO-8601 timestamp; defaults to now.')
        parser.add_argument('--output', type=Path, help='Optional JSON report destination.')

    def handle(self, *args, **options):
        as_of = None
        if options.get('as_of'):
            try:
                as_of = datetime.fromisoformat(options['as_of'].replace('Z', '+00:00'))
            except ValueError as exc:
                raise CommandError('--as-of must be an ISO-8601 timestamp') from exc
            if timezone.is_naive(as_of):
                as_of = timezone.make_aware(as_of, timezone.get_current_timezone())
        report = {
            'generated_at': (as_of or timezone.now()).isoformat(),
            'maturity': SlowMovingOutcomeService.mature_outcomes(
                workspace_id=options.get('workspace_id'), as_of=as_of,
            ),
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        output = options.get('output')
        if output:
            output = output.resolve()
            if output.exists():
                raise CommandError(f'Refusing to overwrite existing report: {output}')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized, encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(f'Wrote slow-moving maturity report: {output}'))
        self.stdout.write(serialized)
