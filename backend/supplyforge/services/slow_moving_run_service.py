"""Trusted, source-bound slow-moving assessment runs for CSV operations."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from django.db import transaction
from django.db.models import Count, DateTimeField, Max, Min, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from supplyforge.models import (
    DemandReturnEvent,
    DatasetVersion,
    InventoryRecord,
    OrderItem,
    Product,
    SlowMovingAlertState,
    SlowMovingAssessmentRun,
    SlowMovingRiskAssessment,
    Workspace,
)
from supplyforge.services.inventory_readiness import InventoryReadinessGate
from supplyforge.services.slow_moving_alert_trust import (
    SlowMovingAlertAttentionPolicy,
    SlowMovingAlertTrustService,
    SlowMovingCatalogContextResolver,
)


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = PROJECT_ROOT / 'config' / 'slow_moving_alert_policy.json'


class SlowMovingRunError(RuntimeError):
    """An operational run cannot be safely built or published."""


def _canonical(value: Any) -> str:
    return str(value or '').strip().upper()


def _as_aware_end_of_day(value: datetime | None, fallback_date) -> datetime:
    if value is not None:
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.replace(hour=23, minute=59, second=59, microsecond=999999)
    return timezone.make_aware(
        datetime.combine(fallback_date, time.max), timezone.get_current_timezone()
    )


class SlowMovingRunService:
    """Create and publish a run without allowing dashboard reads to mutate data."""

    SOURCE_KEY_CSV = 'CSV'

    @classmethod
    def load_policy(cls) -> tuple[dict[str, Any], str]:
        raw = POLICY_PATH.read_bytes()
        policy = json.loads(raw.decode('utf-8'))
        required = {
            'version', 'lookback_days', 'minimum_observed_days',
            'minimum_source_coverage_days', 'consecutive_runs_to_open',
            'accepted_order_statuses', 'active_lifecycle_statuses', 'source_scope',
        }
        missing = required - set(policy)
        if missing:
            raise SlowMovingRunError(f'Slow-moving policy is missing: {sorted(missing)}')
        return policy, hashlib.sha256(raw).hexdigest()

    @classmethod
    def active_csv_run(cls, workspace_id: int | str) -> SlowMovingAssessmentRun | None:
        return (
            SlowMovingAssessmentRun.objects.filter(
                workspace_id=workspace_id,
                source_type=SlowMovingAssessmentRun.SOURCE_CSV,
                source_key=cls.SOURCE_KEY_CSV,
                status=SlowMovingAssessmentRun.STATUS_COMPLETED,
                is_current=True,
            )
            .select_related('dataset_version', 'dataset_version__ingestion_session')
            .first()
        )

    @classmethod
    def run_csv_for_dataset(cls, dataset_version: DatasetVersion | str) -> SlowMovingAssessmentRun:
        """Build a CSV result set bound to one active DatasetVersion.

        The operational projection is current-state storage, so this method is
        invoked directly after dataset promotion by the import worker.  A run
        is only marked current after all rows and lifecycle state are durable.
        """
        version = (
            DatasetVersion.objects.select_related('workspace', 'ingestion_session')
            .get(id=dataset_version)
            if not isinstance(dataset_version, DatasetVersion)
            else dataset_version
        )
        if version.status != DatasetVersion.STATUS_ACTIVE:
            raise SlowMovingRunError('Only the active CSV dataset can publish merchant assessments.')

        policy, checksum = cls.load_policy()
        analysis_as_of = cls.analysis_as_of(version)
        source_scope = cls.source_scope(version, analysis_as_of, policy)
        existing = (
            SlowMovingAssessmentRun.objects.filter(
                workspace_id=version.workspace_id,
                dataset_version=version,
                source_type=SlowMovingAssessmentRun.SOURCE_CSV,
                status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            )
            .order_by('-completed_at')
            .first()
        )
        if existing:
            # A worker retry should never replace an already published result.
            return existing

        run = SlowMovingAssessmentRun.objects.create(
            workspace_id=version.workspace_id,
            source_type=SlowMovingAssessmentRun.SOURCE_CSV,
            source_key=cls.SOURCE_KEY_CSV,
            dataset_version=version,
            analysis_as_of=analysis_as_of,
            policy_version=str(policy['version'])[:64],
            policy_checksum=checksum,
            source_freshness=cls.source_freshness(version, analysis_as_of),
            source_scope=source_scope,
            source_scope_fingerprint=cls.source_scope_fingerprint(source_scope),
        )
        try:
            assessments, summary = cls._build_csv_assessments(run, policy)
            with transaction.atomic():
                SlowMovingRiskAssessment.objects.bulk_create(assessments, batch_size=1_000)
                lifecycle = cls._sync_alert_lifecycle(run, assessments, policy)
                summary['alert_lifecycle'] = lifecycle
                run.summary = summary
                run.save(update_fields=['summary', 'updated_at'])
                # Quality cohorts are part of the published operational
                # result, never a dashboard side effect. They include every
                # eligible SKU for recall, with a flag for real alert opens.
                from supplyforge.services.slow_moving_outcomes import SlowMovingOutcomeService

                summary['outcome_cohorts'] = SlowMovingOutcomeService.capture_run(run)
                run.save(update_fields=['summary', 'updated_at'])
                cls._publish(run)
                # Candidate diagnostics can be expensive and are never part
                # of the deterministic rule decision. Queue them only after
                # this immutable run and all denominator cohorts are durable.
                def enqueue_shadow_capture(run_id=str(run.id)):
                    try:
                        from supplyforge.tasks import capture_slow_moving_candidate_shadow

                        capture_slow_moving_candidate_shadow.delay(run_id)
                    except Exception:
                        logger.exception('Could not enqueue temporal shadow capture for run=%s', run_id)

                transaction.on_commit(enqueue_shadow_capture)
        except Exception as exc:
            logger.exception('Slow-moving assessment run failed: run=%s', run.id)
            SlowMovingAssessmentRun.objects.filter(id=run.id).update(
                status=SlowMovingAssessmentRun.STATUS_FAILED,
                failure_reason=str(exc)[:512],
                is_current=False,
            )
            raise
        return SlowMovingAssessmentRun.objects.get(id=run.id)

    @classmethod
    def analysis_as_of(cls, version: DatasetVersion) -> datetime:
        # ``data_as_of`` is derived from the source CSV end date on new
        # versions.  Keep the session fallback for data imported before that
        # contract was introduced.
        session_end = version.ingestion_session.date_range_end
        if session_end:
            return _as_aware_end_of_day(None, session_end)
        if version.data_as_of:
            return _as_aware_end_of_day(version.data_as_of, version.data_as_of.date())
        raise SlowMovingRunError('CSV dataset has no source end date for a reproducible assessment.')

    @classmethod
    def source_freshness(cls, version: DatasetVersion, analysis_as_of: datetime) -> dict[str, Any]:
        return {
            'source_type': 'CSV',
            'dataset_version_id': str(version.id),
            'dataset_label': version.version_label,
            'source_checksum': version.source_checksum or None,
            'data_as_of': analysis_as_of.isoformat(),
            'activated_at': version.activated_at.isoformat() if version.activated_at else None,
        }

    @classmethod
    def _source_range_start(cls, version: DatasetVersion):
        """Find the earliest declared range in this cumulative CSV lineage."""
        earliest = None
        current = version
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            candidate = current.ingestion_session.date_range_start
            if candidate and (earliest is None or candidate < earliest):
                earliest = candidate
            current = current.parent_version
        return earliest

    @classmethod
    def source_scope(cls, version: DatasetVersion, analysis_as_of: datetime, policy: dict[str, Any]) -> dict[str, Any]:
        scope_policy = dict(policy.get('source_scope') or {})
        start = cls._source_range_start(version)
        return {
            'scope_schema_version': 'slow-moving-source-scope-v2',
            'source_type': SlowMovingAssessmentRun.SOURCE_CSV,
            'workspace_id': version.workspace_id,
            'dataset_version_id': str(version.id),
            'dataset_checksum': version.source_checksum or None,
            'source_range_start': start.isoformat() if start else None,
            'source_range_end': analysis_as_of.date().isoformat(),
            'order_platforms': list(scope_policy.get('csv_order_platforms') or []),
            'warehouse_scope': str(scope_policy.get('warehouse_scope') or 'UNDECLARED'),
            'return_handling': str(scope_policy.get('return_handling') or 'UNDECLARED'),
        }

    @staticmethod
    def source_scope_fingerprint(scope: dict[str, Any]) -> str:
        stable_scope = {
            key: value for key, value in scope.items()
            # Dataset identity belongs in lineage but should not turn a daily
            # replacement import into an incomparable sales scope.
            if key not in {'dataset_version_id', 'dataset_checksum', 'source_range_end'}
        }
        raw = json.dumps(stable_scope, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _source_coverage_days(run: SlowMovingAssessmentRun, lookback_days: int) -> int:
        value = (run.source_scope or {}).get('source_range_start')
        if not value:
            return 0
        try:
            start = datetime.fromisoformat(str(value)).date()
        except ValueError:
            return 0
        return max(0, min(lookback_days, (run.analysis_as_of.date() - start).days + 1))

    @classmethod
    def _publish(cls, run: SlowMovingAssessmentRun) -> None:
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().get(id=run.workspace_id)
            locked_run = SlowMovingAssessmentRun.objects.select_for_update().get(id=run.id)
            version = DatasetVersion.objects.select_for_update().get(id=locked_run.dataset_version_id)
            if version.status != DatasetVersion.STATUS_ACTIVE:
                raise SlowMovingRunError('CSV source was superseded before this assessment run could publish.')
            SlowMovingAssessmentRun.objects.filter(
                workspace=workspace,
                source_key=locked_run.source_key,
                is_current=True,
            ).exclude(id=locked_run.id).update(is_current=False)
            locked_run.status = SlowMovingAssessmentRun.STATUS_COMPLETED
            locked_run.is_current = True
            locked_run.completed_at = timezone.now()
            locked_run.failure_reason = ''
            locked_run.save(update_fields=[
                'status', 'is_current', 'completed_at', 'failure_reason', 'updated_at',
            ])

    @classmethod
    def _build_csv_assessments(
        cls, run: SlowMovingAssessmentRun, policy: dict[str, Any]
    ) -> tuple[list[SlowMovingRiskAssessment], dict[str, Any]]:
        workspace_id = run.workspace_id
        as_of = run.analysis_as_of
        as_of_day = as_of.date()
        lookback_days = int(policy['lookback_days'])
        min_observed_days = int(policy['minimum_observed_days'])
        min_source_coverage = int(policy['minimum_source_coverage_days'])
        accepted_statuses = tuple(str(value).upper() for value in policy['accepted_order_statuses'])
        active_lifecycle = {str(value).upper() for value in policy['active_lifecycle_statuses']}

        inventory = cls._inventory_by_sku(
            workspace_id, as_of, active_lifecycle, source_key=run.source_key,
        )
        catalog = cls._catalog_by_sku(workspace_id, inventory)
        qualified = cls._qualified_demand_by_sku(
            workspace_id, as_of, lookback_days, accepted_statuses,
            tuple((run.source_scope or {}).get('order_platforms') or ()),
        )
        source_coverage_days = cls._source_coverage_days(run, lookback_days)
        statuses: Counter[str] = Counter()
        risk_classes: Counter[str] = Counter()
        records: list[SlowMovingRiskAssessment] = []

        for sku in sorted(set(catalog) | set(inventory)):
            product = catalog.get(sku, {})
            stock = inventory.get(sku)
            demand = qualified.get(sku)
            eligibility, reasons, observed_start, observed_start_source = cls._eligibility(
                product=product,
                stock=stock,
                demand=demand,
                as_of=as_of,
                source_coverage_days=source_coverage_days,
                min_observed_days=min_observed_days,
                min_source_coverage=min_source_coverage,
                require_verified_sellable_start_for_zero_sales=bool(
                    policy.get('require_verified_sellable_start_for_zero_sales', True)
                ),
            )
            statuses[eligibility] += 1
            evidence = cls._base_evidence(
                run=run,
                product=product,
                stock=stock,
                demand=demand,
                source_coverage_days=source_coverage_days,
                eligibility=eligibility,
                reasons=reasons,
                observed_start=observed_start,
                observed_start_source=observed_start_source,
            )
            if eligibility == 'ELIGIBLE':
                score, risk_class, score_components = cls._priority_score(
                    demand or {}, stock, as_of, lookback_days, observed_start,
                )
                primary, supporting = cls._signals(demand or {}, as_of, observed_start)
                evidence['priority_score'] = score
                evidence['priority_score_components'] = score_components
                evidence['score_semantics'] = 'RULE_PRIORITY_NOT_PROBABILITY'
                evidence['alert_lifecycle_status'] = SlowMovingAlertState.STATUS_CANDIDATE
                model_version = str(policy['version'])
                assessment_status = 'COMPLETE'
            else:
                score = 0.0
                risk_class = 'LOW_RISK'
                primary, supporting = [], []
                model_version = str(policy['version'])
                assessment_status = eligibility
                evidence['priority_score'] = None
                evidence['score_semantics'] = 'NOT_SCORED'
                evidence['alert_lifecycle_status'] = SlowMovingAlertState.STATUS_DATA_BLOCKED
            risk_classes[risk_class] += 1
            records.append(SlowMovingRiskAssessment(
                session=run.dataset_version.ingestion_session,
                assessment_run=run,
                sku=sku,
                canonical_sku_id=sku,
                product_name=product.get('product_name') or sku,
                category=product.get('category') or 'CSV',
                risk_class=risk_class,
                risk_probability=None,
                risk_score=score,
                priority_score=score if eligibility == 'ELIGIBLE' else None,
                sellable_stock_quantity=stock.get('available_quantity') if stock else None,
                capital_exposure_vnd=stock.get('capital_exposure') if stock else None,
                days_since_last_sale=evidence.get('dsls'),
                eligibility_status=eligibility,
                primary_signals=primary,
                supporting_signals=supporting,
                diagnostics=primary + supporting,
                evidence=evidence,
                decision_cutoff=as_of.isoformat(),
                model_version=model_version,
                calibration_version='not_applicable_rule_priority',
                diagnostic_rule_version=str(policy['version']),
                dataset_version=run.dataset_version.version_label,
                assessment_status=assessment_status,
                assessment_timestamp=timezone.now(),
            ))

        summary = {
            'total_skus_considered': len(records),
            'eligible_skus': statuses['ELIGIBLE'],
            'eligibility_status_counts': dict(sorted(statuses.items())),
            'risk_class_counts': dict(sorted(risk_classes.items())),
            'source_coverage_days': source_coverage_days,
            'lookback_days': lookback_days,
            'analysis_as_of': as_of.isoformat(),
            'policy_version': policy['version'],
        }
        return records, summary

    @classmethod
    def _catalog_by_sku(cls, workspace_id: int, inventory: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        products = Product.objects.filter(workspace_id=workspace_id).only(
            'item_sku', 'canonical_sku', 'third_party_id', 'product_name', 'platform', 'active_on_web', 'created_at'
        )
        for product in products.iterator(chunk_size=2_000):
            sku = _canonical(product.canonical_sku or product.item_sku or product.third_party_id)
            if not sku:
                continue
            # Prefer an active catalog row when a legacy import produced a
            # duplicate SKU.  The most recent inventory snapshot remains the
            # source of truth for stock and lifecycle.
            current = catalog.get(sku)
            if current and current['active_on_web']:
                continue
            catalog[sku] = {
                'product_name': product.product_name or sku,
                'category': product.platform or 'CSV',
                'active_on_web': bool(product.active_on_web),
                'sellable_start': product.created_at,
                'sellable_start_source': 'PRODUCT_ACTIVATION' if product.created_at else None,
            }
        for sku in inventory:
            catalog.setdefault(sku, {
                'product_name': sku,
                'category': 'CSV',
                'active_on_web': True,
                'sellable_start': None,
                'sellable_start_source': None,
            })
        return catalog

    @classmethod
    def _inventory_by_sku(
        cls, workspace_id: int, as_of, active_lifecycle: set[str], *, source_key: str = 'CSV'
    ) -> dict[str, dict[str, Any]]:
        as_of_day = as_of.date() if hasattr(as_of, 'date') else as_of
        context_resolver = SlowMovingCatalogContextResolver(
            workspace_id=workspace_id, source_key=source_key, as_of=as_of,
        )
        base = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id,
            canonical_sku__gt='',
            record_date__lte=as_of_day,
        )
        latest_for_warehouse = (
            InventoryRecord.objects.filter(
                sku__workspace_id=workspace_id,
                canonical_sku=OuterRef('canonical_sku'),
                warehouse_code=OuterRef('warehouse_code'),
                record_date__lte=as_of_day,
            )
            .order_by('-record_date', '-updated_at', '-id')
            .values('id')[:1]
        )
        rows = base.filter(id=Subquery(latest_for_warehouse)).order_by('canonical_sku', 'warehouse_code')
        grouped: dict[str, list[InventoryRecord]] = defaultdict(list)
        for row in rows.iterator(chunk_size=2_000):
            grouped[_canonical(row.canonical_sku)].append(row)

        sellable_starts: dict[str, Any] = {}
        verified_history = base.filter(
            as_of_verified=True,
            available_quantity__gt=0,
        ).only('canonical_sku', 'record_date', 'source_snapshot_id', 'source_checksum', 'source_lineage_json')
        for record in verified_history.order_by('canonical_sku', 'record_date', 'id').iterator(chunk_size=2_000):
            sku = _canonical(record.canonical_sku)
            if sku and sku not in sellable_starts and InventoryReadinessGate.has_source_lineage(record):
                sellable_starts[sku] = record.record_date

        result: dict[str, dict[str, Any]] = {}
        for sku, records in grouped.items():
            reasons: list[str] = []
            lifecycle_states: set[str] = set()
            available = 0.0
            capital = 0.0
            unit_costs: set[float] = set()
            unit_prices: set[float] = set()
            record_dates = []
            stock_ready = True
            capital_ready = True
            sellable_warehouses = 0
            context_data_needed = False
            context_not_sellable = False
            contexts: list[dict[str, Any]] = []
            for record in records:
                record_dates.append(record.record_date)
                lifecycle = str(record.lifecycle_status or 'UNKNOWN').upper()
                lifecycle_states.add(lifecycle)
                context = context_resolver.resolve(
                    canonical_sku=sku, warehouse_code=record.warehouse_code,
                )
                contexts.append({
                    'warehouse_code': record.warehouse_code or None,
                    **context.as_evidence(),
                })
                lineage = InventoryReadinessGate.has_source_lineage(record)
                if not record.as_of_verified or not lineage:
                    stock_ready = False
                    reasons.append('INVENTORY_SNAPSHOT_UNVERIFIED')
                if (as_of_day - record.record_date).days > InventoryReadinessGate.MAX_SNAPSHOT_AGE_DAYS:
                    stock_ready = False
                    reasons.append('INVENTORY_SNAPSHOT_STALE')
                if record.available_quantity is None or record.available_quantity < 0:
                    stock_ready = False
                    reasons.append('AVAILABLE_STOCK_MISSING')
                if lifecycle not in InventoryReadinessGate.KNOWN_LIFECYCLE_STATES:
                    stock_ready = False
                    reasons.append('LIFECYCLE_UNKNOWN')
                if context.status == 'DATA_NEEDED':
                    context_data_needed = True
                    reasons.extend(context.reasons)
                if context.status == 'NOT_SELLABLE':
                    context_not_sellable = True
                    reasons.extend(context.reasons)
                    continue
                if record.available_quantity is not None and record.available_quantity >= 0:
                    available += float(record.available_quantity)
                    sellable_warehouses += 1
                if record.cost_price is None or record.cost_price < 0:
                    capital_ready = False
                    reasons.append('UNIT_COST_MISSING')
                else:
                    cost = float(record.cost_price)
                    unit_costs.add(cost)
                    if record.available_quantity is not None and record.available_quantity >= 0:
                        capital += float(record.available_quantity) * cost
                if record.selling_price is not None and record.selling_price >= 0:
                    unit_prices.add(float(record.selling_price))
            lifecycle_active = bool(lifecycle_states) and lifecycle_states.issubset(active_lifecycle)
            if context_data_needed:
                stock_ready = False
            result[sku] = {
                'stock_ready': stock_ready,
                'capital_ready': stock_ready and capital_ready,
                'lifecycle_active': lifecycle_active,
                'lifecycle_status': ', '.join(sorted(lifecycle_states)) or 'UNKNOWN',
                'available_quantity': available if stock_ready else None,
                'unit_cost': next(iter(unit_costs)) if len(unit_costs) == 1 else None,
                'unit_price': next(iter(unit_prices)) if len(unit_prices) == 1 else None,
                'capital_exposure': max(0.0, capital) if stock_ready and capital_ready else None,
                'record_date': min(record_dates).isoformat() if record_dates else None,
                'warehouse_count': len(records),
                'sellable_warehouse_count': sellable_warehouses,
                'reasons': sorted(set(reasons)),
                'catalog_context': {
                    'status': 'DATA_NEEDED' if context_data_needed else (
                        'NOT_SELLABLE' if available <= 0 and context_not_sellable else 'READY'
                    ),
                    'sellable_warehouse_count': sellable_warehouses,
                    'contexts': contexts,
                },
                'context_data_needed': context_data_needed,
                'context_not_sellable': context_not_sellable and available <= 0,
                'sellable_start': sellable_starts.get(sku),
                'sellable_start_source': 'VERIFIED_POSITIVE_STOCK' if sellable_starts.get(sku) else None,
            }
        return result

    @classmethod
    def _qualified_demand_by_sku(
        cls, workspace_id: int, as_of: datetime, lookback_days: int, accepted_statuses: tuple[str, ...],
        order_platforms: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        base = (
            OrderItem.objects.filter(
                order__workspace_id=workspace_id,
                canonical_sku__isnull=False,
                canonical_sku__gt='',
                quantity__gt=0,
                order__status__in=accepted_statuses,
                order__return_identifier__isnull=True,
                order__is_accounting=True,
                order__demand_eligibility_verified=True,
            )
            .annotate(event_at=Coalesce(
                'order__source_event_at', 'order__created_at', output_field=DateTimeField(),
            ))
            .filter(event_at__isnull=False, event_at__lte=as_of)
        )
        if order_platforms:
            # Older operational fixtures predate the platform field. They are
            # kept only as a legacy CSV compatibility path; named non-CSV
            # sources such as Odoo are never mixed into a CSV outcome.
            base = base.filter(Q(order__platform__in=order_platforms) | Q(order__platform__isnull=True))
        all_rows = base.values('canonical_sku').annotate(
            first_sale=Min('event_at'),
            last_sale=Max('event_at'),
            total_quantity=Sum('quantity'),
            qualified_order_lines=Count('id'),
        )
        stats: dict[str, dict[str, Any]] = {
            _canonical(row['canonical_sku']): {
                'first_sale': row['first_sale'],
                'last_sale': row['last_sale'],
                'total_quantity': float(row['total_quantity'] or 0),
                'qualified_order_lines': int(row['qualified_order_lines'] or 0),
                'sold_90d': 0.0,
                'sold_30d': 0.0,
                'returned_90d': 0.0,
                'returned_30d': 0.0,
                'order_days_90d': 0,
            }
            for row in all_rows.iterator(chunk_size=2_000)
        }
        returns = DemandReturnEvent.objects.filter(
            workspace_id=workspace_id,
            canonical_sku__gt='',
            quantity__gt=0,
            occurred_at__lte=as_of,
        )
        if order_platforms:
            returns = returns.filter(platform__in=order_platforms)
        for row in returns.values('canonical_sku').annotate(total_quantity=Sum('quantity')).iterator(chunk_size=2_000):
            sku = _canonical(row['canonical_sku'])
            if sku in stats:
                stats[sku]['total_quantity'] = max(
                    0.0, stats[sku]['total_quantity'] - float(row['total_quantity'] or 0),
                )
        window_start = as_of - timedelta(days=lookback_days - 1)
        last_30_start = as_of - timedelta(days=29)
        recent = (
            base.filter(event_at__gte=window_start)
            .annotate(event_day=TruncDate('event_at'))
            .values('canonical_sku')
            .annotate(sold_90d=Sum('quantity'), order_days_90d=Count('event_day', distinct=True))
        )
        for row in recent.iterator(chunk_size=2_000):
            stats.setdefault(_canonical(row['canonical_sku']), {}).update({
                'sold_90d': float(row['sold_90d'] or 0),
                'order_days_90d': int(row['order_days_90d'] or 0),
            })
        for row in (
            returns.filter(occurred_at__gte=window_start)
            .values('canonical_sku').annotate(returned_90d=Sum('quantity'))
            .iterator(chunk_size=2_000)
        ):
            sku = _canonical(row['canonical_sku'])
            if sku in stats:
                returned = float(row['returned_90d'] or 0)
                stats[sku]['returned_90d'] = returned
                stats[sku]['sold_90d'] = max(0.0, stats[sku]['sold_90d'] - returned)
        last_30 = base.filter(event_at__gte=last_30_start).values('canonical_sku').annotate(sold_30d=Sum('quantity'))
        for row in last_30.iterator(chunk_size=2_000):
            stats.setdefault(_canonical(row['canonical_sku']), {})['sold_30d'] = float(row['sold_30d'] or 0)
        for row in (
            returns.filter(occurred_at__gte=last_30_start)
            .values('canonical_sku').annotate(returned_30d=Sum('quantity'))
            .iterator(chunk_size=2_000)
        ):
            sku = _canonical(row['canonical_sku'])
            if sku in stats:
                returned = float(row['returned_30d'] or 0)
                stats[sku]['returned_30d'] = returned
                stats[sku]['sold_30d'] = max(0.0, stats[sku]['sold_30d'] - returned)
        return stats

    @staticmethod
    def _eligibility(
        *, product, stock, demand, as_of, source_coverage_days, min_observed_days,
        min_source_coverage, require_verified_sellable_start_for_zero_sales,
    ):
        if not product.get('active_on_web', True):
            return 'LIFECYCLE_EXCLUDED', ['CATALOG_INACTIVE'], None, None
        if not stock:
            return 'DATA_INCOMPLETE', ['NO_VERIFIED_INVENTORY_SNAPSHOT'], None, None
        if stock.get('context_data_needed'):
            return 'DATA_INCOMPLETE', stock['reasons'] or ['CATALOG_CONTEXT_UNCONFIRMED'], None, None
        if stock.get('context_not_sellable'):
            return 'LIFECYCLE_EXCLUDED', stock['reasons'] or ['INVENTORY_NOT_SELLABLE'], None, None
        if not stock['stock_ready']:
            return 'DATA_INCOMPLETE', stock['reasons'] or ['INVENTORY_INCOMPLETE'], None, None
        if not stock['lifecycle_active']:
            return 'LIFECYCLE_EXCLUDED', ['INVENTORY_LIFECYCLE_NOT_ACTIVE'], None, None
        if (stock['available_quantity'] or 0) <= 0:
            return 'OUT_OF_STOCK', ['NO_POSITIVE_AVAILABLE_STOCK'], None, None
        if source_coverage_days < min_source_coverage:
            return 'INSUFFICIENT_HISTORY', ['SOURCE_COVERAGE_TOO_SHORT'], None, None

        starts = [
            (product.get('sellable_start'), product.get('sellable_start_source')),
            (stock.get('sellable_start'), stock.get('sellable_start_source')),
        ]
        verified_starts = [
            (value.date() if hasattr(value, 'date') else value, source)
            for value, source in starts
            if value and (value.date() if hasattr(value, 'date') else value) <= as_of.date()
        ]
        if demand and demand.get('first_sale'):
            # A completed, verified sale is a defensible lower bound for when
            # the SKU was sellable. Prefer the earliest proof rather than a
            # later inventory snapshot that would understate its age.
            first_sale = demand['first_sale']
            verified_starts.append((
                first_sale.date() if hasattr(first_sale, 'date') else first_sale,
                'FIRST_QUALIFIED_SALE',
            ))
        if verified_starts:
            observed_start, observed_start_source = min(verified_starts, key=lambda value: value[0])
        else:
            reason = 'SELLABLE_START_UNVERIFIED' if require_verified_sellable_start_for_zero_sales else 'NO_QUALIFIED_SALES_HISTORY'
            return 'DATA_INCOMPLETE', [reason], None, None

        observed_date = observed_start.date() if hasattr(observed_start, 'date') else observed_start
        observed_days = max(0, (as_of.date() - observed_date).days + 1)
        if observed_days < min_observed_days:
            return 'INSUFFICIENT_HISTORY', ['SKU_HISTORY_TOO_SHORT'], observed_start, observed_start_source
        return 'ELIGIBLE', [], observed_start, observed_start_source

    @staticmethod
    def _priority_score(demand, stock, as_of, lookback_days, observed_start):
        start_date = observed_start.date() if hasattr(observed_start, 'date') else observed_start
        last_sale = demand.get('last_sale')
        dsls = max(0, (as_of.date() - last_sale.date()).days) if last_sale else max(0, (as_of.date() - start_date).days + 1)
        observed_window = min(lookback_days, max(1, (as_of.date() - start_date).days + 1))
        velocity = float(demand.get('sold_90d') or 0) / observed_window
        zero_rate = max(0.0, min(1.0, 1 - int(demand.get('order_days_90d') or 0) / observed_window))
        inactivity = min(1.0, dsls / 90.0) * 40.0
        intermittent = zero_rate * 25.0
        no_recent = 20.0 if float(demand.get('sold_30d') or 0) <= 0 else 0.0
        stock_cover = min(1.0, (stock['available_quantity'] or 0) / max(1.0, velocity * 30.0)) * 15.0
        score = round(min(100.0, inactivity + intermittent + no_recent + stock_cover), 1)
        if float(demand.get('sold_90d') or 0) <= 0 or score >= 85:
            risk_class = 'CRITICAL'
        elif score >= 65:
            risk_class = 'HIGH_RISK'
        elif score >= 40:
            risk_class = 'MEDIUM_RISK'
        else:
            risk_class = 'LOW_RISK'
        return score, risk_class, {
            'inactivity': round(inactivity, 1),
            'intermittent_demand': round(intermittent, 1),
            'no_recent_sales': round(no_recent, 1),
            'stock_cover': round(stock_cover, 1),
        }

    @staticmethod
    def _signals(demand, as_of, observed_start):
        start_date = observed_start.date() if hasattr(observed_start, 'date') else observed_start
        last_sale = demand.get('last_sale')
        dsls = max(0, (as_of.date() - last_sale.date()).days) if last_sale else max(0, (as_of.date() - start_date).days + 1)
        primary, supporting = [], []
        if float(demand.get('sold_30d') or 0) <= 0:
            primary.append('NO_QUALIFIED_SALES_LAST_30_DAYS')
        if dsls >= 30:
            primary.append('LONG_TIME_SINCE_LAST_QUALIFIED_SALE')
        if int(demand.get('order_days_90d') or 0) <= 45:
            supporting.append('INTERMITTENT_QUALIFIED_DEMAND')
        if float(demand.get('sold_90d') or 0) / 90.0 < 1:
            supporting.append('LOW_QUALIFIED_SALES_VELOCITY')
        return primary or ['MONITOR_QUALIFIED_SALES_VELOCITY'], supporting

    @staticmethod
    def _base_evidence(
        *, run, product, stock, demand, source_coverage_days, eligibility, reasons,
        observed_start, observed_start_source,
    ):
        demand = demand or {}
        stock = stock or {}
        lookback = max(1, min(90, source_coverage_days))
        first_sale = demand.get('first_sale')
        last_sale = demand.get('last_sale')
        observed_date = observed_start.date() if hasattr(observed_start, 'date') else observed_start
        observed_days = max(0, (run.analysis_as_of.date() - observed_date).days + 1) if observed_date else 0
        sold_90 = float(demand.get('sold_90d') or 0)
        sold_30 = float(demand.get('sold_30d') or 0)
        order_days = int(demand.get('order_days_90d') or 0)
        return {
            'source': 'CSV',
            'source_data_as_of': run.analysis_as_of.isoformat(),
            'source_scope_fingerprint': run.source_scope_fingerprint,
            'source_scope': run.source_scope,
            'source_coverage_days': source_coverage_days,
            'sku_observed_days': observed_days,
            'sellable_start_at': observed_start.isoformat() if hasattr(observed_start, 'isoformat') else None,
            'sellable_start_source': observed_start_source,
            'qualified_order_lines': int(demand.get('qualified_order_lines') or 0),
            'first_qualified_sale_at': first_sale.isoformat() if first_sale else None,
            'last_qualified_sale_at': last_sale.isoformat() if last_sale else None,
            'sold_90d': round(sold_90, 4),
            'sold_30d': round(sold_30, 4),
            'returned_90d': round(float(demand.get('returned_90d') or 0), 4),
            'returned_30d': round(float(demand.get('returned_30d') or 0), 4),
            'sales_velocity_90d': round(sold_90 / min(90, max(1, observed_days)), 4),
            'sales_velocity_30d': round(sold_30 / min(30, max(1, observed_days)), 4),
            'zero_rate_90d': round(max(0.0, min(1.0, 1 - order_days / min(90, max(1, observed_days)))), 4),
            'dsls': max(0, (run.analysis_as_of.date() - last_sale.date()).days) if last_sale else None,
            'stock_quantity': stock.get('available_quantity'),
            'unit_cost': stock.get('unit_cost'),
            'unit_price': stock.get('unit_price'),
            'capital_exposure_vnd': stock.get('capital_exposure'),
            'inventory_readiness': {
                'status': 'READY' if stock.get('capital_ready') else (
                    'STOCK_VERIFIED_COST_MISSING' if stock.get('stock_ready') else 'INVENTORY_INCOMPLETE'
                ),
                'record_date': stock.get('record_date'),
                'lifecycle_status': stock.get('lifecycle_status'),
                'warehouse_count': stock.get('warehouse_count', 0),
                'sellable_warehouse_count': stock.get('sellable_warehouse_count', 0),
                'reasons': stock.get('reasons', []),
            },
            'catalog_context': stock.get('catalog_context') or {
                'status': 'UNKNOWN', 'contexts': [],
            },
            'eligibility_status': eligibility,
            'eligibility_reasons': reasons,
        }

    @classmethod
    def _sync_alert_lifecycle(cls, run, assessments, policy) -> dict[str, int]:
        threshold = int(policy['consecutive_runs_to_open'])
        attention_policy, _ = SlowMovingAlertAttentionPolicy.load()
        candidates = [
            assessment for assessment in assessments
            if assessment.assessment_status == 'COMPLETE' and assessment.risk_class in {'CRITICAL', 'HIGH_RISK'}
        ]
        candidate_skus = {assessment.canonical_sku_id for assessment in candidates}
        outcome = Counter()
        now = timezone.now()
        changed_assessments: list[SlowMovingRiskAssessment] = []
        for assessment in candidates:
            state, created = SlowMovingAlertState.objects.select_for_update().get_or_create(
                workspace_id=run.workspace_id,
                source_key=run.source_key,
                canonical_sku=assessment.canonical_sku_id,
                defaults={
                    'source_type': run.source_type,
                    'status': SlowMovingAlertState.STATUS_CANDIDATE,
                    'consecutive_eligible_runs': 0,
                    'first_detected_at': now,
                    'last_detected_at': now,
                },
            )
            prior_status = state.status
            prior_run = state.last_assessment_run_id
            previous_facts = dict(state.last_signal_snapshot or {})
            current_facts = SlowMovingAlertTrustService.snapshot_for_assessment(assessment, run)
            changes = SlowMovingAlertTrustService.changed_facts(
                previous_facts, current_facts, attention_policy,
            )
            material_change = SlowMovingAlertTrustService.has_material_change(changes)
            consecutive = state.consecutive_eligible_runs + 1 if prior_run and prior_run != run.id else 1
            # A merchant acknowledgement/snooze is a human state and must not
            # be overwritten by a fresh scoring run.
            if state.status == SlowMovingAlertState.STATUS_SNOOZED and state.snoozed_until and state.snoozed_until > now:
                lifecycle_status = SlowMovingAlertState.STATUS_SNOOZED
            elif state.status == SlowMovingAlertState.STATUS_ACKNOWLEDGED:
                lifecycle_status = SlowMovingAlertState.STATUS_ACKNOWLEDGED
            elif prior_status == SlowMovingAlertState.STATUS_RESOLVED and not material_change:
                # Closing an alert is a merchant decision. A later calculation
                # with the same operational facts cannot silently undo it.
                lifecycle_status = SlowMovingAlertState.STATUS_RESOLVED
                consecutive = 0
            elif prior_status == SlowMovingAlertState.STATUS_RESOLVED:
                # A material change starts a new confirmation sequence instead
                # of reopening an alert from one noisy snapshot.
                consecutive = 1
                lifecycle_status = (
                    SlowMovingAlertState.STATUS_OPEN
                    if threshold <= 1 else SlowMovingAlertState.STATUS_CANDIDATE
                )
            else:
                lifecycle_status = (
                    SlowMovingAlertState.STATUS_OPEN
                    if consecutive >= threshold else SlowMovingAlertState.STATUS_CANDIDATE
                )
            opened_now = (
                prior_status != SlowMovingAlertState.STATUS_OPEN
                and lifecycle_status == SlowMovingAlertState.STATUS_OPEN
            )
            event_type = SlowMovingAlertTrustService.event_type_for(
                prior_status=prior_status,
                status=lifecycle_status,
                changes=changes,
                opened_now=opened_now,
            )
            state.source_type = run.source_type
            state.status = lifecycle_status
            state.consecutive_eligible_runs = consecutive
            state.last_assessment_run = run
            state.last_detected_at = now
            state.resolved_at = None if lifecycle_status != SlowMovingAlertState.STATUS_RESOLVED else state.resolved_at
            state.last_signal_snapshot = current_facts
            state.last_signal_fingerprint = SlowMovingAlertTrustService.fingerprint(current_facts)
            state.last_material_change_at = now if material_change else state.last_material_change_at
            state.next_review_at = (
                SlowMovingAlertTrustService.next_review(now=now, policy=attention_policy)
                if lifecycle_status in {
                    SlowMovingAlertState.STATUS_CANDIDATE,
                    SlowMovingAlertState.STATUS_OPEN,
                    SlowMovingAlertState.STATUS_ACKNOWLEDGED,
                    SlowMovingAlertState.STATUS_SNOOZED,
                }
                else None
            )
            state.save(update_fields=[
                'source_type', 'status', 'consecutive_eligible_runs', 'last_assessment_run',
                'last_detected_at', 'resolved_at', 'last_signal_snapshot',
                'last_signal_fingerprint', 'last_material_change_at', 'next_review_at', 'updated_at',
            ])
            evidence = dict(assessment.evidence or {})
            evidence['alert_lifecycle_status'] = lifecycle_status
            evidence['alert_consecutive_runs'] = consecutive
            evidence['alert_state_id'] = str(state.id)
            evidence['alert_opened_this_run'] = opened_now
            evidence['alert_previous_facts'] = previous_facts
            evidence['alert_changed_facts'] = changes
            evidence['alert_event_type'] = event_type
            assessment.evidence = evidence
            changed_assessments.append(assessment)
            SlowMovingAlertTrustService.create_passport(
                run=run, alert=state, assessment=assessment, event_type=event_type,
                previous=previous_facts, current=current_facts, changes=changes,
            )
            outcome[lifecycle_status] += 1

        tracked = SlowMovingAlertState.objects.select_for_update().filter(
            workspace_id=run.workspace_id,
            source_key=run.source_key,
            status__in=[
                SlowMovingAlertState.STATUS_CANDIDATE,
                SlowMovingAlertState.STATUS_OPEN,
                SlowMovingAlertState.STATUS_ACKNOWLEDGED,
                SlowMovingAlertState.STATUS_SNOOZED,
            ],
        ).exclude(canonical_sku__in=candidate_skus)
        current_by_sku = {assessment.canonical_sku_id: assessment for assessment in assessments}
        for state in tracked:
            assessment = current_by_sku.get(state.canonical_sku)
            previous_facts = dict(state.last_signal_snapshot or {})
            current_facts = (
                SlowMovingAlertTrustService.snapshot_for_assessment(assessment, run)
                if assessment else previous_facts
            )
            changes = SlowMovingAlertTrustService.changed_facts(
                previous_facts, current_facts, attention_policy,
            )
            prior_status = state.status
            state.last_assessment_run = run
            state.last_detected_at = now
            if assessment and assessment.assessment_status != 'COMPLETE':
                state.status = SlowMovingAlertState.STATUS_DATA_BLOCKED
                state.consecutive_eligible_runs = 0
            elif assessment:
                state.status = SlowMovingAlertState.STATUS_RESOLVED
                state.resolved_at = now
                state.consecutive_eligible_runs = 0
            else:
                state.status = SlowMovingAlertState.STATUS_DATA_BLOCKED
                state.consecutive_eligible_runs = 0
            event_type = SlowMovingAlertTrustService.event_type_for(
                prior_status=prior_status,
                status=state.status,
                changes=changes,
                opened_now=False,
            )
            state.last_signal_snapshot = current_facts
            state.last_signal_fingerprint = SlowMovingAlertTrustService.fingerprint(current_facts)
            state.last_material_change_at = (
                now if SlowMovingAlertTrustService.has_material_change(changes) else state.last_material_change_at
            )
            state.next_review_at = None if state.status == SlowMovingAlertState.STATUS_RESOLVED else SlowMovingAlertTrustService.next_review(now=now, policy=attention_policy)
            state.save(update_fields=[
                'status', 'consecutive_eligible_runs', 'last_assessment_run',
                'last_detected_at', 'resolved_at', 'last_signal_snapshot',
                'last_signal_fingerprint', 'last_material_change_at', 'next_review_at', 'updated_at',
            ])
            if assessment:
                evidence = dict(assessment.evidence or {})
                evidence.update({
                    'alert_lifecycle_status': state.status,
                    'alert_consecutive_runs': state.consecutive_eligible_runs,
                    'alert_state_id': str(state.id),
                    'alert_opened_this_run': False,
                    'alert_previous_facts': previous_facts,
                    'alert_changed_facts': changes,
                    'alert_event_type': event_type,
                })
                assessment.evidence = evidence
                changed_assessments.append(assessment)
            SlowMovingAlertTrustService.create_passport(
                run=run, alert=state, assessment=assessment, event_type=event_type,
                previous=previous_facts, current=current_facts, changes=changes,
            )
            outcome[state.status] += 1

        if changed_assessments:
            SlowMovingRiskAssessment.objects.bulk_update(changed_assessments, ['evidence'], batch_size=1_000)
        return dict(sorted(outcome.items()))
