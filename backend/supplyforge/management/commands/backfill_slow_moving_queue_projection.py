"""Backfill typed queue fields from immutable assessment evidence in batches."""

from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from supplyforge.models import (
    IntegrationOperationalRiskAssessment,
    SlowMovingRiskAssessment,
)


def _decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _integer(value):
    if value in (None, ''):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


class Command(BaseCommand):
    help = 'Backfill typed slow-moving queue fields from existing immutable evidence without changing scores.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', default='')
        parser.add_argument('--workspace-id', type=int)
        parser.add_argument('--connection-id', default='')
        parser.add_argument('--batch-size', type=int, default=1000)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        batch_size = max(1, min(int(options['batch_size']), 5000))
        query = SlowMovingRiskAssessment.objects.all().order_by('id')
        if options.get('run_id'):
            query = query.filter(assessment_run_id=options['run_id'])
        if options.get('workspace_id'):
            query = query.filter(session__workspace_id=options['workspace_id'])
        if not options.get('run_id') and not options.get('workspace_id') and not options.get('connection_id'):
            raise CommandError('Cần --run-id, --workspace-id hoặc --connection-id để giới hạn phạm vi backfill.')
        csv_changed = 0
        csv_buffer = []
        for assessment in query.iterator(chunk_size=batch_size):
            evidence = assessment.evidence or {}
            priority = evidence.get('priority_score', assessment.risk_score)
            values = {
                'priority_score': float(priority) if priority not in (None, '') else None,
                'sellable_stock_quantity': _decimal(evidence.get('stock_quantity')),
                'capital_exposure_vnd': _decimal(evidence.get('capital_exposure_vnd')),
                'days_since_last_sale': _integer(evidence.get('dsls')),
                'eligibility_status': str(evidence.get('eligibility_status') or assessment.assessment_status or '')[:32],
            }
            if any(getattr(assessment, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(assessment, key, value)
                csv_buffer.append(assessment)
            if len(csv_buffer) >= batch_size:
                if options['apply']:
                    SlowMovingRiskAssessment.objects.bulk_update(csv_buffer, list(values), batch_size=batch_size)
                csv_changed += len(csv_buffer)
                csv_buffer.clear()
        if csv_buffer:
            if options['apply']:
                SlowMovingRiskAssessment.objects.bulk_update(csv_buffer, list(values), batch_size=batch_size)
            csv_changed += len(csv_buffer)

        odoo_query = IntegrationOperationalRiskAssessment.objects.all().order_by('id')
        if options.get('connection_id'):
            odoo_query = odoo_query.filter(snapshot__connection_id=options['connection_id'])
        elif options.get('workspace_id'):
            odoo_query = odoo_query.filter(snapshot__connection__workspace_id=options['workspace_id'])
        else:
            # A run belongs only to CSV. Do not widen a run-scoped request to
            # every ERP workspace merely because it has no Odoo selector.
            odoo_query = odoo_query.none()
        odoo_changed = 0
        odoo_buffer = []
        for assessment in odoo_query.iterator(chunk_size=batch_size):
            evidence = assessment.evidence or {}
            priority = evidence.get('priority_score', assessment.risk_score)
            values = {
                'priority_score': float(priority) if priority not in (None, '') else None,
                'sellable_stock_quantity': _decimal(evidence.get('stock_quantity')),
                'capital_exposure_vnd': _decimal(evidence.get('capital_exposure_vnd')),
                'days_since_last_sale': _integer(evidence.get('dsls')),
                'eligibility_status': str(evidence.get('eligibility_status') or 'ELIGIBLE')[:32],
            }
            if any(getattr(assessment, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(assessment, key, value)
                odoo_buffer.append(assessment)
            if len(odoo_buffer) >= batch_size:
                if options['apply']:
                    IntegrationOperationalRiskAssessment.objects.bulk_update(odoo_buffer, list(values), batch_size=batch_size)
                odoo_changed += len(odoo_buffer)
                odoo_buffer.clear()
        if odoo_buffer:
            if options['apply']:
                IntegrationOperationalRiskAssessment.objects.bulk_update(odoo_buffer, list(values), batch_size=batch_size)
            odoo_changed += len(odoo_buffer)
        mode = 'Đã cập nhật' if options['apply'] else 'Sẽ cập nhật (dry run)'
        self.stdout.write(self.style.SUCCESS(
            f'{mode} {csv_changed} CSV và {odoo_changed} Odoo queue projection.'
        ))
