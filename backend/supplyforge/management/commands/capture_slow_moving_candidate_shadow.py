"""Capture governed temporal candidate diagnostics for an operational run."""

import json

from django.core.management.base import BaseCommand, CommandError

from supplyforge.services.slow_moving_candidate_shadow import SlowMovingCandidateShadowService


class Command(BaseCommand):
    help = 'Capture calibrated SHADOW/CANARY diagnostics without changing slow-moving rule alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', required=True)

    def handle(self, *args, **options):
        try:
            report = SlowMovingCandidateShadowService.capture_run(options['run_id'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
