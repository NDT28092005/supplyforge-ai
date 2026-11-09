"""Create idempotent in-app review digests for assigned slow-moving alerts."""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from supplyforge.services.slow_moving_alert_operations import SlowMovingAlertDigestService


class Command(BaseCommand):
    help = (
        'Prepare concise in-app slow-moving review digests. This command never sends '
        'email, Slack or Zalo, and never bypasses notification consent or quality gates.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', type=int, required=True)
        parser.add_argument('--source', default='CSV')
        parser.add_argument('--date', dest='delivery_date', help='ISO date; defaults to today in the configured timezone.')

    def handle(self, *args, **options):
        delivery_date = None
        if options.get('delivery_date'):
            try:
                delivery_date = date.fromisoformat(options['delivery_date'])
            except ValueError as exc:
                raise CommandError('--date phải có dạng YYYY-MM-DD.') from exc
        result = SlowMovingAlertDigestService.prepare_in_app_digests(
            workspace_id=options['workspace_id'],
            source_key=str(options['source']),
            delivery_date=delivery_date,
        )
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
