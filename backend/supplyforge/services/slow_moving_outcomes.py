"""Mature immutable future-demand outcomes for slow-moving assessments."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import DateTimeField, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from supplyforge.models import (
    DemandReturnEvent,
    DatasetVersion,
    IntegrationSkuDailyMetric,
    OrderItem,
    SlowMovingAlertState,
    SlowMovingDispositionEvent,
    SlowMovingOutcomeCohort,
    SlowMovingRiskAssessment,
)
from supplyforge.services.slow_moving_run_service import SlowMovingRunError, SlowMovingRunService
from supplyforge.services.slow_moving_quality_policy import load_slow_moving_quality_policy


class SlowMovingOutcomeError(ValueError):
    """A cohort cannot be captured or labelled safely."""


class SlowMovingOutcomeService:
    """Capture decision cohorts and mature labels without data leakage."""

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return timezone.make_aware(value, timezone.get_current_timezone()) if timezone.is_naive(value) else value

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @classmethod
    def _opening_capital_exposure(cls, evidence: dict[str, Any]) -> Decimal | None:
        readiness = (evidence.get('inventory_readiness') or {}).get('status')
        value = cls._decimal(evidence.get('capital_exposure_vnd'))
        if readiness != 'READY' or value is None or value < 0:
            return None
        return value

    @staticmethod
    def _rule_snapshot(assessment) -> dict[str, Any]:
        evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
        return {
            'risk_class': assessment.risk_class,
            'priority_score': float(assessment.risk_score or 0),
            'score_semantics': evidence.get('score_semantics', 'RULE_PRIORITY_NOT_PROBABILITY'),
            'signals': [
                *list(getattr(assessment, 'primary_signals', None) or []),
                *list(getattr(assessment, 'supporting_signals', None) or []),
            ],
            'score_components': evidence.get('priority_score_components') or {},
        }

    @staticmethod
    def _segment_snapshot(run, assessment) -> dict[str, Any]:
        scope = run.source_scope if isinstance(run.source_scope, dict) else {}
        return {
            'category': str(getattr(assessment, 'category', '') or 'UNSPECIFIED'),
            'channel': ','.join(sorted(str(value) for value in scope.get('order_platforms') or [])) or 'UNSPECIFIED',
            'warehouse': str(scope.get('warehouse_scope') or ','.join(sorted(
                str(value) for value in scope.get('warehouse_ids') or []
            )) or 'UNSPECIFIED'),
        }

    @classmethod
    def capture_run(cls, run) -> dict[str, int]:
        """Create one immutable denominator row per eligible assessment."""
        if run.source_type != run.SOURCE_CSV:
            raise SlowMovingOutcomeError('CSV_CAPTURE_REQUIRES_CSV_RUN')
        policy, _ = load_slow_moving_quality_policy()
        grace = int(policy['label_grace_days'])
        assessments = list(
            SlowMovingRiskAssessment.objects.filter(
                assessment_run=run,
                assessment_status='COMPLETE',
            ).only(
                'id', 'sku', 'canonical_sku_id', 'risk_class', 'evidence', 'risk_score',
            )
        )
        alert_ids = {
            str((assessment.evidence or {}).get('alert_state_id'))
            for assessment in assessments
            if (assessment.evidence or {}).get('alert_state_id')
        }
        alert_states = {
            str(alert.id): alert
            for alert in SlowMovingAlertState.objects.filter(
                workspace_id=run.workspace_id, id__in=alert_ids,
            )
        }
        created = 0
        existing = 0
        opened = 0
        for assessment in assessments:
            evidence = assessment.evidence or {}
            alert = alert_states.get(str(evidence.get('alert_state_id')))
            opened_alert = bool(evidence.get('alert_opened_this_run'))
            defaults = {
                'workspace_id': run.workspace_id,
                'assessment_run': run,
                'assessment': assessment,
                'alert_state': alert,
                'source_type': run.source_type,
                'source_key': run.source_key,
                'source_scope': run.source_scope or {},
                'source_scope_fingerprint': run.source_scope_fingerprint,
                'policy_version': run.policy_version,
                'policy_checksum': run.policy_checksum,
                'source_assessment_key': f'csv:{assessment.id}',
                'source_sku': assessment.sku,
                'canonical_sku': assessment.canonical_sku_id,
                'decision_cutoff': run.analysis_as_of,
                'predicted_risk_class': assessment.risk_class,
                'opened_alert': opened_alert,
                'opening_stock_quantity': cls._decimal(evidence.get('stock_quantity')),
                'opening_inventory_verified': (
                    (evidence.get('inventory_readiness') or {}).get('status') in {'READY', 'STOCK_VERIFIED_COST_MISSING'}
                ),
                'opening_capital_exposure': cls._opening_capital_exposure(evidence),
                'rule_snapshot_json': cls._rule_snapshot(assessment),
                'segment_json': cls._segment_snapshot(run, assessment),
                'outcome_30_ends_at': run.analysis_as_of + timedelta(days=30),
                'outcome_60_ends_at': run.analysis_as_of + timedelta(days=60),
                'outcome_90_ends_at': run.analysis_as_of + timedelta(days=90),
                'maturity_eligible_at': run.analysis_as_of + timedelta(days=60 + grace),
            }
            _, was_created = SlowMovingOutcomeCohort.objects.get_or_create(
                workspace_id=run.workspace_id,
                source_key=run.source_key,
                source_assessment_key=defaults['source_assessment_key'],
                defaults=defaults,
            )
            created += int(was_created)
            existing += int(not was_created)
            opened += int(was_created and opened_alert)
        return {
            'eligible_cohorts_created': created,
            'eligible_cohorts_existing': existing,
            'opened_alert_cohorts_created': opened,
        }

    @classmethod
    def capture_odoo_run(cls, run, assessments) -> dict[str, int]:
        """Freeze Odoo snapshot assessments before the next refresh replaces them.

        Odoo's current read model intentionally deletes and recreates its row
        set. A cohort therefore retains the immutable source key and source
        SKU rather than relying on that transient technical row.
        """
        if run.source_type != run.SOURCE_ODOO:
            raise SlowMovingOutcomeError('ODOO_CAPTURE_REQUIRES_ODOO_RUN')
        if not run.source_snapshot_fingerprint:
            raise SlowMovingOutcomeError('ODOO_SOURCE_SNAPSHOT_FINGERPRINT_MISSING')
        policy, _ = load_slow_moving_quality_policy()
        grace = int(policy['label_grace_days'])
        created = existing = opened = 0
        for assessment in assessments:
            evidence = assessment.evidence or {}
            external_sku_digest = __import__('hashlib').sha256(
                str(assessment.external_sku).encode('utf-8')
            ).hexdigest()[:24]
            source_assessment_key = f'odoo:{run.source_snapshot_fingerprint}:{external_sku_digest}'
            alert = None
            alert_id = evidence.get('alert_state_id')
            if alert_id:
                alert = SlowMovingAlertState.objects.filter(
                    workspace_id=run.workspace_id, id=alert_id,
                ).first()
            opened_alert = bool(evidence.get('alert_opened_this_run'))
            defaults = {
                'workspace_id': run.workspace_id,
                'assessment_run': run,
                'integration_assessment': assessment,
                'alert_state': alert,
                'source_type': run.source_type,
                'source_key': run.source_key,
                'source_scope': run.source_scope or {},
                'source_scope_fingerprint': run.source_scope_fingerprint,
                'policy_version': run.policy_version,
                'policy_checksum': run.policy_checksum,
                'source_assessment_key': source_assessment_key,
                'source_sku': assessment.external_sku,
                'canonical_sku': assessment.canonical_sku,
                'decision_cutoff': run.analysis_as_of,
                'predicted_risk_class': assessment.risk_class,
                'opened_alert': opened_alert,
                'opening_stock_quantity': cls._decimal(evidence.get('stock_quantity')),
                'opening_inventory_verified': (
                    (evidence.get('inventory_readiness') or {}).get('status') == 'READY'
                ),
                'opening_capital_exposure': cls._opening_capital_exposure(evidence),
                'rule_snapshot_json': cls._rule_snapshot(assessment),
                'segment_json': cls._segment_snapshot(run, assessment),
                'outcome_30_ends_at': run.analysis_as_of + timedelta(days=30),
                'outcome_60_ends_at': run.analysis_as_of + timedelta(days=60),
                'outcome_90_ends_at': run.analysis_as_of + timedelta(days=90),
                'maturity_eligible_at': run.analysis_as_of + timedelta(days=60 + grace),
            }
            _, was_created = SlowMovingOutcomeCohort.objects.get_or_create(
                workspace_id=run.workspace_id,
                source_key=run.source_key,
                source_assessment_key=source_assessment_key,
                defaults=defaults,
            )
            created += int(was_created)
            existing += int(not was_created)
            opened += int(was_created and opened_alert)
        return {
            'eligible_cohorts_created': created,
            'eligible_cohorts_existing': existing,
            'opened_alert_cohorts_created': opened,
        }

    @classmethod
    def _scope_has_coverage(cls, cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> bool:
        """Ensure zero demand is not inferred from a source that ended early."""
        if cohort.source_type == cohort.assessment_run.SOURCE_ODOO:
            return cls._odoo_scope_has_coverage(cohort, outcome_end)
        return cls._csv_scope_has_coverage(cohort, outcome_end)

    @classmethod
    def _csv_scope_has_coverage(cls, cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> bool:
        """Require one scope-matched CSV lineage with no daily coverage gap.

        A later active file is not proof that the merchant observed every day
        since an earlier decision.  Only the active DatasetVersion and its
        parent chain may supply coverage; every interval must declare the same
        source/channel/warehouse/return scope as the frozen cohort.
        """
        scope = cohort.source_scope if isinstance(cohort.source_scope, dict) else {}
        if scope.get('return_handling') != 'NET_SALES_MINUS_RETURN_EVENTS':
            raise SlowMovingOutcomeError('CSV_LEGACY_RETURN_POLICY_AUDIT_ONLY')
        if not cohort.source_scope_fingerprint:
            raise SlowMovingOutcomeError('CSV_SCOPE_FINGERPRINT_MISSING')
        policy, _ = SlowMovingRunService.load_policy()
        active_versions = list(
            DatasetVersion.objects.filter(
                workspace_id=cohort.workspace_id,
                status=DatasetVersion.STATUS_ACTIVE,
            ).select_related('ingestion_session', 'parent_version', 'parent_version__ingestion_session')
        )
        if not active_versions:
            raise SlowMovingOutcomeError('CSV_ACTIVE_DATASET_MISSING')
        if len(active_versions) != 1:
            raise SlowMovingOutcomeError('CSV_ACTIVE_DATASET_AMBIGUOUS')

        required_start = cohort.decision_cutoff.date() + timedelta(days=1)
        required_end = outcome_end.date()
        if required_start > required_end:
            return False
        saw_scope_mismatch = False
        for active in active_versions:
            intervals: list[tuple[Any, Any]] = []
            current = active
            visited = set()
            chain_valid = True
            while current and current.id not in visited:
                visited.add(current.id)
                if current.workspace_id != cohort.workspace_id:
                    chain_valid = False
                    break
                try:
                    version_end = SlowMovingRunService.analysis_as_of(current)
                except SlowMovingRunError:
                    chain_valid = False
                    break
                version_scope = SlowMovingRunService.source_scope(current, version_end, policy)
                if SlowMovingRunService.source_scope_fingerprint(version_scope) != cohort.source_scope_fingerprint:
                    saw_scope_mismatch = True
                    chain_valid = False
                    break
                version_start = current.ingestion_session.date_range_start
                if version_start is None:
                    chain_valid = False
                    break
                intervals.append((version_start, version_end.date()))
                current = current.parent_version
            if current is not None and current.id in visited:
                chain_valid = False
            if not chain_valid:
                continue

            cursor = required_start
            for interval_start, interval_end in sorted(intervals):
                if interval_end < cursor:
                    continue
                if interval_start > cursor:
                    break
                cursor = max(cursor, interval_end + timedelta(days=1))
                if cursor > required_end:
                    return True
        if saw_scope_mismatch:
            raise SlowMovingOutcomeError('CSV_OUTCOME_SCOPE_MISMATCH')
        return False

    @staticmethod
    def _odoo_scope_metrics(cohort: SlowMovingOutcomeCohort):
        scope = cohort.source_scope or {}
        connection_id = scope.get('integration_connection_id')
        if not connection_id:
            raise SlowMovingOutcomeError('SOURCE_SCOPE_CONNECTION_MISSING')
        warehouse_ids = [str(value) for value in scope.get('warehouse_ids') or [] if str(value)]
        if not warehouse_ids:
            raise SlowMovingOutcomeError('SOURCE_SCOPE_WAREHOUSE_MISSING')
        return IntegrationSkuDailyMetric.objects.filter(
            connection_id=connection_id,
        ).filter(Q(warehouse_id='') | Q(warehouse_id__in=warehouse_ids))

    @classmethod
    def _odoo_scope_has_coverage(cls, cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> bool:
        """Require daily ERP facts through the outcome end, not merely a max date.

        A missing sales row is normal, but a missing daily source observation
        is not evidence that demand was zero. Inventory snapshots written by
        the Odoo projection make this continuity check possible.
        """
        decision_day = cohort.decision_cutoff.date()
        outcome_day = outcome_end.date()
        if outcome_day <= decision_day:
            return False
        observed_dates = set(
            cls._odoo_scope_metrics(cohort)
            .filter(metric_date__gt=decision_day, metric_date__lte=outcome_day)
            .values_list('metric_date', flat=True)
            .distinct()
        )
        required_days = (outcome_day - decision_day).days
        return len(observed_dates) == required_days

    @classmethod
    def _future_net_fulfilled_units(cls, cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> Decimal:
        if cohort.source_type == cohort.assessment_run.SOURCE_ODOO:
            return cls._odoo_future_net_fulfilled_units(cohort, outcome_end)
        return cls._csv_future_net_fulfilled_units(cohort, outcome_end)

    @staticmethod
    def _outcome_confounders(
        cohort: SlowMovingOutcomeCohort, outcome_end: datetime,
    ) -> list[str]:
        """Return operational events that invalidate a clean demand label."""
        return list(
            SlowMovingDispositionEvent.objects.filter(
                workspace_id=cohort.workspace_id,
                source_type=cohort.source_type,
                source_key=cohort.source_key,
                source_scope_fingerprint=cohort.source_scope_fingerprint,
                canonical_sku=cohort.canonical_sku,
                occurred_at__gt=cohort.decision_cutoff,
                occurred_at__lte=outcome_end,
            ).order_by('occurred_at', 'id').values_list('event_type', flat=True)
        )

    @staticmethod
    def _csv_future_net_fulfilled_units(cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> Decimal:
        scope = cohort.source_scope or {}
        platforms = tuple(str(value) for value in scope.get('order_platforms') or () if str(value))
        if not platforms:
            raise SlowMovingOutcomeError('SOURCE_SCOPE_ORDER_PLATFORM_MISSING')
        items = (
            OrderItem.objects.filter(
                order__workspace_id=cohort.workspace_id,
                canonical_sku=cohort.canonical_sku,
                quantity__gt=0,
                order__status__in=('COMPLETED', 'SHIPPED'),
                order__return_identifier__isnull=True,
                order__is_accounting=True,
                order__demand_eligibility_verified=True,
            )
            .filter(Q(order__platform__in=platforms) | Q(order__platform__isnull=True))
            .annotate(event_at=Coalesce(
                F('order__source_event_at'), F('order__created_at'), output_field=DateTimeField(),
            ))
            .filter(
                event_at__isnull=False,
                event_at__gt=cohort.decision_cutoff,
                event_at__lte=outcome_end,
            )
        )
        sales = Decimal(items.aggregate(total=Sum('quantity'))['total'] or 0)
        returns = DemandReturnEvent.objects.filter(
            workspace_id=cohort.workspace_id,
            canonical_sku=cohort.canonical_sku,
            quantity__gt=0,
            occurred_at__gt=cohort.decision_cutoff,
            occurred_at__lte=outcome_end,
            platform__in=platforms,
        )
        returned = Decimal(returns.aggregate(total=Sum('quantity'))['total'] or 0)
        # A correction can never manufacture negative demand. It can only
        # lower fulfilled demand down to the label's zero boundary.
        return max(Decimal('0'), sales - returned)

    @classmethod
    def _odoo_future_net_fulfilled_units(cls, cohort: SlowMovingOutcomeCohort, outcome_end: datetime) -> Decimal:
        totals = cls._odoo_scope_metrics(cohort).filter(
            external_sku=cohort.source_sku,
            warehouse_id='',
            metric_date__gt=cohort.decision_cutoff.date(),
            metric_date__lte=outcome_end.date(),
        ).aggregate(sales=Sum('sales_quantity'), returned=Sum('returned_quantity'))
        # A returned unit is not fulfilled demand. Do not make a negative
        # correction look like negative demand; the low-demand label is zero.
        return max(Decimal('0'), Decimal(totals['sales'] or 0) - Decimal(totals['returned'] or 0))

    @classmethod
    def _mature_horizon(
        cls,
        cohort: SlowMovingOutcomeCohort,
        *,
        horizon: int,
        observed_at: datetime,
        grace_days: int,
    ) -> tuple[bool, bool]:
        end_field = f'outcome_{horizon}_ends_at'
        quantity_field = f'future_net_fulfilled_units_{horizon}'
        observed_field = f'outcome_{horizon}_observed_at'
        outcome_end = getattr(cohort, end_field)
        if observed_at < outcome_end + timedelta(days=grace_days):
            return False, False
        if not cls._scope_has_coverage(cohort, outcome_end):
            return False, True
        quantity = cls._future_net_fulfilled_units(cohort, outcome_end)
        previous = getattr(cohort, quantity_field)
        if previous is not None and previous != quantity:
            cohort.label_revision += 1
            cohort.label_revision_reason = 'LATE_SOURCE_CORRECTION'
        setattr(cohort, quantity_field, quantity)
        setattr(cohort, observed_field, observed_at)
        return True, False

    @classmethod
    def mature_outcomes(
        cls,
        *,
        workspace_id: int | None = None,
        as_of: datetime | None = None,
        batch_size: int = 500,
    ) -> dict[str, int]:
        """Materialize mature 30/60/90-day labels without assuming no data is zero."""
        policy, _ = load_slow_moving_quality_policy()
        observed_at = cls._aware(as_of) if as_of else timezone.now()
        grace = int(policy['label_grace_days'])
        cohorts = SlowMovingOutcomeCohort.objects.filter(
            outcome_30_ends_at__lte=observed_at - timedelta(days=grace),
        ).select_related('assessment_run')
        if workspace_id is not None:
            cohorts = cohorts.filter(workspace_id=workspace_id)
        counts = {'matured_now': 0, 'blocked_now': 0, 'confounded_now': 0, 'revised_now': 0}
        for cohort in cohorts.iterator(chunk_size=batch_size):
            before_revision = cohort.label_revision
            if observed_at >= cohort.outcome_60_ends_at + timedelta(days=grace):
                confounders = cls._outcome_confounders(cohort, cohort.outcome_60_ends_at)
                if confounders:
                    was_confounded = cohort.status == SlowMovingOutcomeCohort.STATUS_CONFOUNDED
                    cohort.status = SlowMovingOutcomeCohort.STATUS_CONFOUNDED
                    cohort.confounder_types = sorted(set(confounders))
                    cohort.block_reason = f'CONFOUNDED_{cohort.confounder_types[0]}'[:128]
                    counts['confounded_now'] += int(not was_confounded)
                    cohort.save(update_fields=[
                        'status', 'block_reason', 'confounder_types', 'updated_at',
                    ])
                    continue
            try:
                matured_30, blocked_30 = cls._mature_horizon(
                    cohort, horizon=30, observed_at=observed_at, grace_days=grace,
                )
                matured_60, blocked_60 = cls._mature_horizon(
                    cohort, horizon=60, observed_at=observed_at, grace_days=grace,
                )
                matured_90, blocked_90 = cls._mature_horizon(
                    cohort, horizon=90, observed_at=observed_at, grace_days=grace,
                )
            except SlowMovingOutcomeError as exc:
                matured_30 = matured_60 = matured_90 = False
                blocked_30 = blocked_90 = False
                blocked_60 = True
                cohort.block_reason = str(exc)[:128]
            if matured_60:
                was_mature = cohort.status == SlowMovingOutcomeCohort.STATUS_MATURED
                cohort.status = SlowMovingOutcomeCohort.STATUS_MATURED
                cohort.block_reason = ''
                counts['matured_now'] += int(not was_mature)
            elif blocked_60 and cohort.status != SlowMovingOutcomeCohort.STATUS_MATURED:
                was_blocked = cohort.status == SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED
                cohort.status = SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED
                cohort.block_reason = cohort.block_reason or 'OUTCOME_SOURCE_COVERAGE_INCOMPLETE'
                counts['blocked_now'] += int(not was_blocked)
            if cohort.label_revision > before_revision:
                counts['revised_now'] += 1
            cohort.save(update_fields=[
                'status', 'block_reason', 'future_net_fulfilled_units_30',
                'future_net_fulfilled_units_60', 'future_net_fulfilled_units_90',
                'outcome_30_observed_at', 'outcome_60_observed_at',
                'outcome_90_observed_at', 'label_revision', 'label_revision_reason', 'updated_at',
                'confounder_types',
            ])

        total = SlowMovingOutcomeCohort.objects.all()
        if workspace_id is not None:
            total = total.filter(workspace_id=workspace_id)
        return {
            **counts,
            'matured_total': total.filter(status=SlowMovingOutcomeCohort.STATUS_MATURED).count(),
            'blocked_total': total.filter(status=SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED).count(),
            'confounded_total': total.filter(status=SlowMovingOutcomeCohort.STATUS_CONFOUNDED).count(),
            'pending_total': total.filter(status=SlowMovingOutcomeCohort.STATUS_PENDING).count(),
        }
