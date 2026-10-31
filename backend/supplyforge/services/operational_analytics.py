"""Materialised operational analytics for an ERP connection.

The operational source is deliberately rule based. It turns only approved ERP
SKU mappings and read-only Odoo facts into a live decision queue; it never
modifies, or combines with, the reproducible CSV/LightGBM research pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Max, Min, Sum
from django.utils import timezone

from supplyforge.models import (
    CapitalExposureAnalysisRecord,
    CapitalExposureItemRecord,
    IntegrationConnection,
    IntegrationOperationalRiskAssessment,
    IntegrationOperationalRiskSnapshot,
    IntegrationSkuDailyMetric,
    IntegrationSkuMapping,
)


LOOKBACK_DAYS = 90
ANNUAL_OPPORTUNITY_RATE = 0.12
ACTIVE_MAPPING_STATUSES = (
    IntegrationSkuMapping.STATUS_AUTO,
    IntegrationSkuMapping.STATUS_CONFIRMED,
)


def _number(value) -> float:
    return float(value or Decimal('0'))


def _aging(dsls: int) -> tuple[str, str]:
    if dsls > 90:
        return 'CRITICAL_AGING', 'P1'
    if dsls > 60:
        return 'AT_RISK', 'P1'
    if dsls > 30:
        return 'AGING', 'P2'
    return 'FRESH', 'P3'


class OdooOperationalAnalyticsService:
    """Build the latest Odoo operational source for one connection.

    A one-to-one snapshot prevents unbounded growth during the 15-minute
    polling cadence. The source daily facts and sync runs retain the full
    audit trail, while a dashboard always reads one stable materialised view.
    """

    LOCK_SECONDS = 15 * 60

    @classmethod
    def capital_dataset_version(cls, connection_id) -> str:
        return f'odoo:{connection_id}'

    @classmethod
    def get_snapshot(cls, connection_id, workspace_id: int | None = None):
        query = IntegrationOperationalRiskSnapshot.objects.select_related('connection')
        if workspace_id is not None:
            query = query.filter(connection__workspace_id=workspace_id)
        return query.filter(connection_id=connection_id).first()

    @classmethod
    def get_capital_analysis(cls, connection_id, workspace_id: int):
        return CapitalExposureAnalysisRecord.objects.filter(
            merchant_id=f'workspace:{workspace_id}',
            dataset_version=cls.capital_dataset_version(connection_id),
            status='COMPLETED',
        ).order_by('-created_at').first()

    @classmethod
    def refresh(cls, connection: IntegrationConnection) -> dict:
        """Rebuild risk and capital read models after a successful ERP sync.

        The calculation is deterministic and bounded by mapped SKU count.
        It is suitable for a worker, never a dashboard HTTP request.
        """
        lock_key = f'sf:odoo-operational-analytics:{connection.id}'
        try:
            acquired = cache.add(lock_key, '1', timeout=cls.LOCK_SECONDS)
        except Exception:
            acquired = True
        if not acquired:
            return {'status': 'SKIPPED', 'reason': 'refresh_already_running'}

        try:
            return cls._refresh_locked(connection)
        finally:
            try:
                cache.delete(lock_key)
            except Exception:
                pass

    @classmethod
    def _refresh_locked(cls, connection: IntegrationConnection) -> dict:
        mappings = list(
            IntegrationSkuMapping.objects.filter(
                connection=connection,
                status__in=ACTIVE_MAPPING_STATUSES,
                canonical_product__isnull=False,
            ).select_related('canonical_product')
        )
        mapped_skus = [mapping.external_sku for mapping in mappings]
        metrics = IntegrationSkuDailyMetric.objects.filter(connection=connection)
        reference_date = metrics.aggregate(value=Max('metric_date'))['value']
        total_mappings = connection.sku_mappings.count()
        needs_review = connection.sku_mappings.filter(status=IntegrationSkuMapping.STATUS_REVIEW).count()
        coverage = {
            'mapped_skus': len(mapped_skus),
            'total_source_skus': total_mappings,
            'unmapped_skus': needs_review,
            'excluded_ignored_skus': connection.sku_mappings.filter(status=IntegrationSkuMapping.STATUS_IGNORED).count(),
            'scored_skus': 0,
            'excluded_without_on_hand': 0,
            'missing_unit_cost_skus': 0,
            'lookback_days': LOOKBACK_DAYS,
        }

        if not reference_date or not mapped_skus:
            return cls._save_empty_snapshot(connection, reference_date, coverage)

        window_start = reference_date - timedelta(days=LOOKBACK_DAYS - 1)
        first_metric_date = metrics.aggregate(value=Min('metric_date'))['value']
        observed_days = max(1, min(LOOKBACK_DAYS, (reference_date - (first_metric_date or window_start)).days + 1))
        mapped_metrics = metrics.filter(external_sku__in=mapped_skus)

        sales_by_sku: dict[str, dict] = defaultdict(lambda: {'daily': {}, 'sold_30d': 0.0, 'sold_90d': 0.0, 'last_sale': None})
        sales_rows = (
            mapped_metrics.filter(metric_date__gte=window_start)
            .values('external_sku', 'metric_date')
            .annotate(quantity=Sum('sales_quantity'))
        )
        for row in sales_rows.iterator(chunk_size=2_000):
            sku = row['external_sku']
            quantity = max(0.0, _number(row['quantity']))
            metric_date = row['metric_date']
            item = sales_by_sku[sku]
            item['daily'][metric_date] = quantity
            item['sold_90d'] += quantity
            if metric_date >= reference_date - timedelta(days=29):
                item['sold_30d'] += quantity
            if quantity > 0 and (item['last_sale'] is None or metric_date > item['last_sale']):
                item['last_sale'] = metric_date

        inventory_rows = (
            mapped_metrics.filter(metric_date=reference_date, on_hand_quantity__isnull=False)
            .values('external_sku')
            .annotate(on_hand=Sum('on_hand_quantity'), unit_cost=Avg('unit_cost'), unit_price=Avg('unit_price'))
        )
        inventory_by_sku = {
            row['external_sku']: {
                'on_hand': max(0.0, _number(row['on_hand'])),
                'unit_cost': _number(row['unit_cost']),
                'unit_price': _number(row['unit_price']),
            }
            for row in inventory_rows.iterator(chunk_size=2_000)
        }

        records: list[dict] = []
        for mapping in mappings:
            inventory = inventory_by_sku.get(mapping.external_sku)
            if not inventory or inventory['on_hand'] <= 0:
                coverage['excluded_without_on_hand'] += 1
                continue
            sales = sales_by_sku[mapping.external_sku]
            last_sale = sales['last_sale']
            dsls = (reference_date - last_sale).days if last_sale else observed_days
            zero_days = observed_days - sum(1 for quantity in sales['daily'].values() if quantity > 0)
            zero_rate = max(0.0, min(1.0, zero_days / observed_days))
            velocity_90d = sales['sold_90d'] / observed_days
            velocity_30d = sales['sold_30d'] / min(30, observed_days)
            cost = inventory['unit_cost'] or _number(mapping.canonical_product.cost)
            if cost <= 0:
                coverage['missing_unit_cost_skus'] += 1
            capital = inventory['on_hand'] * max(0.0, cost)
            score, risk_class = cls._risk_score(
                sold_30d=sales['sold_30d'], sold_90d=sales['sold_90d'],
                dsls=dsls, zero_rate=zero_rate, on_hand=inventory['on_hand'], velocity=velocity_90d,
            )
            primary, supporting = cls._signals(
                sold_30d=sales['sold_30d'], dsls=dsls, zero_rate=zero_rate, velocity=velocity_90d,
            )
            records.append({
                'mapping': mapping,
                'external_sku': mapping.external_sku,
                'canonical_sku': mapping.canonical_sku,
                'product_name': mapping.canonical_product.product_name or mapping.external_name or mapping.external_sku,
                'category': mapping.canonical_product.platform or 'ERP / Odoo',
                'risk_class': risk_class,
                'risk_probability': score / 100.0,
                'risk_score': score,
                'primary_signals': primary,
                'supporting_signals': supporting,
                'evidence': {
                    'source': 'ODOO',
                    'source_data_as_of': reference_date.isoformat(),
                    'lookback_days': observed_days,
                    'sold_30d': round(sales['sold_30d'], 4),
                    'sold_90d': round(sales['sold_90d'], 4),
                    'sales_velocity_30d': round(velocity_30d, 4),
                    'sales_velocity_90d': round(velocity_90d, 4),
                    'zero_rate_90d': round(zero_rate, 6),
                    'dsls': int(dsls),
                    'last_sale_date': last_sale.isoformat() if last_sale else None,
                    'stock_quantity': round(inventory['on_hand'], 4),
                    'unit_cost': round(cost, 4),
                    'unit_price': round(inventory['unit_price'], 4),
                    'capital_exposure_vnd': round(capital, 2),
                    'risk_engine': 'odoo_operational_rules_v1',
                },
            })

        coverage['scored_skus'] = len(records)
        coverage['coverage_pct'] = round((len(records) / total_mappings * 100), 1) if total_mappings else 0.0
        with transaction.atomic():
            snapshot, _ = IntegrationOperationalRiskSnapshot.objects.select_for_update().get_or_create(
                connection=connection,
            )
            snapshot.source_data_as_of = reference_date
            snapshot.source_synced_at = connection.last_successful_sync_at or timezone.now()
            snapshot.risk_engine_version = 'odoo_operational_rules_v1'
            snapshot.coverage = coverage
            snapshot.status = 'READY'
            snapshot.save()
            snapshot.assessments.all().delete()
            IntegrationOperationalRiskAssessment.objects.bulk_create([
                IntegrationOperationalRiskAssessment(snapshot=snapshot, **record)
                for record in records
            ], batch_size=1_000)
            capital = cls._replace_capital_analysis(connection, records, reference_date, coverage)

        return {
            'status': 'READY',
            'source_data_as_of': reference_date.isoformat(),
            'scored_skus': len(records),
            'mapped_skus': len(mapped_skus),
            'capital_analysis_id': str(capital.analysis_id),
        }

    @classmethod
    def _save_empty_snapshot(cls, connection, reference_date, coverage):
        coverage['reason'] = 'NO_MAPPED_ERP_FACTS'
        with transaction.atomic():
            snapshot, _ = IntegrationOperationalRiskSnapshot.objects.select_for_update().get_or_create(connection=connection)
            snapshot.source_data_as_of = reference_date
            snapshot.source_synced_at = connection.last_successful_sync_at
            snapshot.coverage = coverage
            snapshot.status = 'EMPTY'
            snapshot.save()
            snapshot.assessments.all().delete()
            CapitalExposureAnalysisRecord.objects.filter(
                merchant_id=f'workspace:{connection.workspace_id}',
                dataset_version=cls.capital_dataset_version(connection.id),
            ).delete()
        return {'status': 'EMPTY', 'reason': coverage['reason'], 'mapped_skus': len(mapped_skus)}

    @staticmethod
    def _risk_score(*, sold_30d, sold_90d, dsls, zero_rate, on_hand, velocity) -> tuple[float, str]:
        # Transparent rule components: inactivity dominates, then intermittent
        # demand and the stock cover implied by recent consumption.
        inactivity = min(1.0, dsls / 90.0) * 35.0
        zero_component = zero_rate * 30.0
        no_recent_sales = 20.0 if sold_30d <= 0 else 0.0
        stock_cover = min(1.0, on_hand / max(1.0, velocity * 30.0)) * 15.0
        score = round(min(100.0, inactivity + zero_component + no_recent_sales + stock_cover), 1)
        if sold_90d <= 0 or score >= 85:
            return max(score, 90.0), 'CRITICAL'
        if score >= 65:
            return score, 'HIGH_RISK'
        if score >= 40:
            return score, 'MEDIUM_RISK'
        return score, 'LOW_RISK'

    @staticmethod
    def _signals(*, sold_30d, dsls, zero_rate, velocity) -> tuple[list[str], list[str]]:
        primary = []
        supporting = []
        if sold_30d <= 0:
            primary.append('NO_SALES_LAST_30D')
        if dsls >= 30:
            primary.append('LONG_TIME_SINCE_LAST_SALE')
        if zero_rate >= 0.5:
            supporting.append('HIGH_ZERO_SALES_RATE')
        if velocity < 1:
            supporting.append('LOW_SALES_VELOCITY')
        return primary or ['MONITOR_SALES_VELOCITY'], supporting

    @classmethod
    def _replace_capital_analysis(cls, connection, records, reference_date, coverage):
        dataset_version = cls.capital_dataset_version(connection.id)
        merchant_id = f'workspace:{connection.workspace_id}'
        CapitalExposureAnalysisRecord.objects.filter(
            merchant_id=merchant_id,
            dataset_version=dataset_version,
        ).delete()
        risk_groups = defaultdict(lambda: {'sku_count': 0, 'inventory_value': 0.0})
        aging_groups = defaultdict(lambda: {'sku_count': 0, 'inventory_value': 0.0})
        items = []
        total_inventory = total_rwce = total_opportunity = 0.0
        for record in records:
            evidence = record['evidence']
            inventory_value = float(evidence['capital_exposure_vnd'])
            risk_probability = float(record['risk_probability'])
            rwce = inventory_value * risk_probability
            opportunity = inventory_value * ANNUAL_OPPORTUNITY_RATE
            aging_bucket, priority = _aging(int(evidence['dsls']))
            total_inventory += inventory_value
            total_rwce += rwce
            total_opportunity += opportunity
            risk_groups[record['risk_class']]['sku_count'] += 1
            risk_groups[record['risk_class']]['inventory_value'] += inventory_value
            aging_groups[aging_bucket]['sku_count'] += 1
            aging_groups[aging_bucket]['inventory_value'] += inventory_value
            items.append(CapitalExposureItemRecord(
                sku=record['canonical_sku'],
                canonical_sku_id=record['canonical_sku'],
                product_name=record['product_name'],
                category=record['category'],
                inventory_value=inventory_value,
                capital_exposure=inventory_value,
                risk_weighted_exposure=rwce,
                probability_adjusted_exposure=rwce,
                aging_days=int(evidence['dsls']),
                aging_bucket=aging_bucket,
                aging_risk_level=aging_bucket,
                slow_moving_risk_class=record['risk_class'],
                risk_probability=risk_probability,
                aging_priority=priority,
                estimated_opportunity_cost=opportunity,
                aging_flags=record['primary_signals'] + record['supporting_signals'],
            ))
        summary = {
            'module_version': 'odoo_operational_capital_v1',
            'summary': {
                'sku_count': len(items),
                'total_inventory_value': total_inventory,
                'total_risk_weighted_exposure': total_rwce,
                'total_probability_adjusted_exposure': total_rwce,
                'total_opportunity_cost': total_opportunity,
                'annual_opportunity_rate': ANNUAL_OPPORTUNITY_RATE,
            },
            'source': {
                'type': 'ODOO_OPERATIONS',
                'connection_id': str(connection.id),
                'data_as_of': reference_date.isoformat(),
                'coverage': coverage,
            },
        }
        analysis = CapitalExposureAnalysisRecord.objects.create(
            merchant_id=merchant_id,
            dataset_version=dataset_version,
            status='COMPLETED',
            calculation_version='odoo_operational_capital_v1',
            total_skus=len(items),
            total_inventory_value=total_inventory,
            total_risk_weighted_exposure=total_rwce,
            total_probability_adjusted_exposure=total_rwce,
            total_opportunity_cost=total_opportunity,
            annual_opportunity_rate=ANNUAL_OPPORTUNITY_RATE,
            summary_payload=summary,
            risk_distribution=[{'group': key, **value} for key, value in risk_groups.items()],
            aging_distribution=[{'group': key, **value} for key, value in aging_groups.items()],
            reconciliation_status={'source': 'ODOO_OPERATIONS', 'data_as_of': reference_date.isoformat(), 'coverage': coverage},
        )
        for item in items:
            item.analysis = analysis
        CapitalExposureItemRecord.objects.bulk_create(items, batch_size=1_000)
        return analysis
