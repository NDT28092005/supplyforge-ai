"""
SupplyForge AI — High-Speed Query Service Architecture
========================================================
Read-Through Caching layer ensuring <0.1s UI response time with Cache Stampede Lock & Strict Data Integrity.
"""

import logging
import time
from collections.abc import Iterable

from django.core.cache import cache
from django.db.models import Count

from supplyforge.models import (
    CapitalExposureAnalysisRecord,
    DatasetVersion,
    IngestionSession,
    SlowMovingRiskAssessment,
)
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.metrics import record_cache

logger = logging.getLogger(__name__)

class DashboardQueryService:
    RISK_CLASSES = ('CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK')

    @staticmethod
    def _active_dataset_version(workspace_id: int):
        """Return the current immutable dataset lineage for one workspace."""
        return (
            DatasetVersion.objects.filter(
                workspace_id=workspace_id,
                status=DatasetVersion.STATUS_ACTIVE,
            )
            .only(
                'id', 'ingestion_session_id', 'version_label', 'data_as_of',
                'manifest_json', 'version_number',
            )
            .order_by('-version_number')
            .first()
        )

    @staticmethod
    def _latest_risk_session(workspace_id: int):
        """Find the latest persisted risk snapshot for legacy import flows.

        Older synchronous ingestion paths predate immutable DatasetVersion
        publication but still persist a tenant-scoped risk assessment session.
        This is a bounded compatibility lookup used only when no active
        dataset version exists.
        """
        return (
            IngestionSession.objects.filter(
                workspace_id=workspace_id,
                risk_assessments__isnull=False,
            )
            .only('id', 'dataset_version', 'created_at', 'updated_at')
            .order_by('-created_at')
            .distinct()
            .first()
        )

    @staticmethod
    def _dataset_metadata(workspace_id: int) -> dict:
        """Attach the exact dataset freshness used by the dashboard response."""
        version = DashboardQueryService._active_dataset_version(workspace_id)
        return {
            'datasetVersion': version.version_label if version else None,
            'dataAsOf': version.data_as_of.isoformat() if version and version.data_as_of else None,
            'isStale': version is None,
        }

    @classmethod
    def _active_gold_dashboard_summary(cls, workspace_id: int) -> dict | None:
        """Return the compact gold read model for the current dataset version."""
        version = cls._active_dataset_version(workspace_id)
        if not version:
            return None

        dashboard = ((version.manifest_json or {}).get('gold') or {}).get('dashboard')
        summary = dashboard.get('summary') if isinstance(dashboard, dict) else None
        if not dashboard or not dashboard.get('completed') or not isinstance(summary, dict):
            return None

        payload = dict(summary)
        payload.update({
            'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
            'calculatedAt': dashboard.get('generatedAt') or time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'datasetVersion': version.version_label,
            'dataAsOf': version.data_as_of.isoformat() if version.data_as_of else None,
            'isStale': False,
        })
        return payload

    @staticmethod
    def _as_non_negative_float(value: object) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _risk_distribution_capital(cls, distribution: object) -> dict[str, float]:
        """Normalize the persisted capital read-model distribution.

        The financial pipeline has used both ``inventory_value`` and
        ``capital_exposure`` across versions. This compatibility boundary keeps
        the dashboard contract stable without recalculating a portfolio.
        """
        capital = {risk_class: 0.0 for risk_class in cls.RISK_CLASSES}
        if not isinstance(distribution, Iterable) or isinstance(distribution, (str, bytes, dict)):
            return capital

        for row in distribution:
            if not isinstance(row, dict):
                continue
            risk_class = row.get('group') or row.get('risk_class')
            if risk_class not in capital:
                continue
            value = row.get('inventory_value')
            if value is None:
                value = row.get('capital_exposure')
            capital[risk_class] += cls._as_non_negative_float(value)
        return capital

    @classmethod
    def _aged_capital(cls, aging_distribution: object) -> tuple[float, int]:
        """Read the >90-day portfolio total from the persisted aging aggregate."""
        if not isinstance(aging_distribution, Iterable) or isinstance(
            aging_distribution, (str, bytes, dict),
        ):
            return 0.0, 0

        capital = 0.0
        sku_count = 0
        for row in aging_distribution:
            if not isinstance(row, dict):
                continue
            # The capital model defines AT_RISK as 91-180 days and
            # CRITICAL_AGING as over 180 days / no observed sale.
            if row.get('group') not in {'AT_RISK', 'CRITICAL_AGING'}:
                continue
            value = row.get('inventory_value')
            if value is None:
                value = row.get('capital_exposure')
            capital += cls._as_non_negative_float(value)
            try:
                sku_count += max(0, int(row.get('sku_count') or 0))
            except (TypeError, ValueError):
                continue
        return capital, sku_count

    @classmethod
    def _top_risk_skus_from_assessments(cls, assessments) -> list[dict]:
        """Return a bounded queue when a capital analysis has not finished."""
        top_risk_skus = []
        for risk_class in ('CRITICAL', 'HIGH_RISK'):
            records = (
                assessments.filter(risk_class=risk_class)
                .only('sku', 'product_name', 'risk_class', 'risk_score', 'evidence')
                .order_by('-risk_score', 'sku')[:5 - len(top_risk_skus)]
            )
            for record in records:
                evidence = record.evidence if isinstance(record.evidence, dict) else {}
                capital = cls._as_non_negative_float(evidence.get('capital_exposure_vnd'))
                top_risk_skus.append({
                    'sku': record.sku,
                    'name': record.product_name,
                    'riskClass': record.risk_class,
                    'riskScore': record.risk_score,
                    'capitalExposureVnd': capital,
                    'daysInInventory': evidence.get('dsls', 0),
                })
            if len(top_risk_skus) == 5:
                break
        return top_risk_skus

    @classmethod
    def _persisted_dashboard_summary(cls, workspace_id: int) -> dict | None:
        """Serve an active portfolio from persisted read models after cache loss.

        Gold is the preferred dashboard source. This fallback intentionally uses
        only the active dataset session, a grouped risk query, and the compact
        capital-analysis aggregate. It never performs the historical, all-SKU
        Python calculation that is reserved for workers.
        """
        version = cls._active_dataset_version(workspace_id)
        session = version.ingestion_session if version else cls._latest_risk_session(workspace_id)
        if not session:
            return None

        assessments = SlowMovingRiskAssessment.objects.filter(
            session_id=session.id,
        )
        risk_counts = {risk_class: 0 for risk_class in cls.RISK_CLASSES}
        for row in assessments.values('risk_class').annotate(total=Count('id')):
            risk_class = row['risk_class']
            if risk_class in risk_counts:
                risk_counts[risk_class] = int(row['total'])
        total_skus = sum(risk_counts.values())
        if total_skus == 0:
            return None

        analysis = (
            CapitalExposureAnalysisRecord.objects.filter(
                merchant_id=f'workspace:{workspace_id}',
                dataset_version=f'session:{session.id}',
                status='COMPLETED',
            )
            .only(
                'analysis_id', 'total_inventory_value', 'risk_distribution',
                'aging_distribution',
            )
            .order_by('-created_at')
            .first()
        )

        capital_by_class = {risk_class: 0.0 for risk_class in cls.RISK_CLASSES}
        total_capital = 0.0
        aged_capital = 0.0
        aged_sku_count = 0
        capital_status = 'RISK_READ_MODEL_ONLY'
        if analysis:
            capital_by_class = cls._risk_distribution_capital(analysis.risk_distribution)
            total_capital = cls._as_non_negative_float(analysis.total_inventory_value)
            aged_capital, aged_sku_count = cls._aged_capital(analysis.aging_distribution)
            capital_status = 'PERSISTED_READ_MODEL'

            top_risk_skus = []
            for risk_class in ('CRITICAL', 'HIGH_RISK'):
                items = (
                    analysis.items.filter(slow_moving_risk_class=risk_class)
                    .only(
                        'sku', 'product_name', 'slow_moving_risk_class',
                        'risk_probability', 'capital_exposure', 'aging_days',
                    )
                    .order_by('-capital_exposure', 'sku')[:5 - len(top_risk_skus)]
                )
                top_risk_skus.extend({
                    'sku': item.sku,
                    'name': item.product_name,
                    'riskClass': item.slow_moving_risk_class,
                    'riskScore': item.risk_probability,
                    'capitalExposureVnd': cls._as_non_negative_float(item.capital_exposure),
                    'daysInInventory': item.aging_days or 0,
                } for item in items)
                if len(top_risk_skus) == 5:
                    break
            if not top_risk_skus:
                top_risk_skus = cls._top_risk_skus_from_assessments(assessments)
        else:
            top_risk_skus = cls._top_risk_skus_from_assessments(assessments)

        return {
            'hasData': True,
            'totalSkus': total_skus,
            'criticalCount': risk_counts['CRITICAL'],
            'highRiskCount': risk_counts['HIGH_RISK'],
            'mediumRiskCount': risk_counts['MEDIUM_RISK'],
            'lowRiskCount': risk_counts['LOW_RISK'],
            'totalCapitalExposureVnd': total_capital,
            'atRiskCapitalVnd': (
                capital_by_class['CRITICAL'] + capital_by_class['HIGH_RISK']
            ),
            'agedCapitalVnd': aged_capital,
            'agedSkuCount': aged_sku_count,
            'riskCapitalByClassVnd': capital_by_class,
            'capitalStatus': capital_status,
            'topRiskSkus': top_risk_skus,
            'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
            'calculatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'datasetVersion': version.version_label if version else session.dataset_version,
            'dataAsOf': (
                version.data_as_of.isoformat()
                if version and version.data_as_of
                else session.updated_at.isoformat()
            ),
            'isStale': False,
            'isDegraded': True,
        }

    @classmethod
    def _stale_dashboard_payload(cls, workspace_id: int) -> dict:
        """Return a safe contract while the worker builds the gold read model."""
        metadata = cls._dataset_metadata(workspace_id)
        return {
            'hasData': False,
            'totalSkus': 0,
            'criticalCount': 0,
            'highRiskCount': 0,
            'mediumRiskCount': 0,
            'lowRiskCount': 0,
            'totalCapitalExposureVnd': 0.0,
            'atRiskCapitalVnd': 0.0,
            'agedCapitalVnd': 0.0,
            'agedSkuCount': 0,
            'riskCapitalByClassVnd': {
                'CRITICAL': 0.0,
                'HIGH_RISK': 0.0,
                'MEDIUM_RISK': 0.0,
                'LOW_RISK': 0.0,
            },
            'capitalStatus': 'PENDING_READ_MODEL',
            'topRiskSkus': [],
            'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
            'calculatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            **metadata,
            'isStale': True,
        }

    @classmethod
    def get_executive_summary(cls, workspace_id: int, force_refresh: bool = False) -> tuple[dict, str]:
        """
        Retrieves pre-calculated Executive Dashboard summary.
        Only cache warming workers may set ``force_refresh``. HTTP requests
        either return a cached/gold aggregate or a clearly marked stale
        payload; they must never scan the SKU table.
        """
        version = CachePolicy.get_workspace_version(workspace_id)
        cache_key = f"sf:v2:ws:{workspace_id}:v{version}:dashboard:summary"
        if force_refresh:
            summary = cls._calculate_executive_summary(workspace_id)
            try:
                cache.set(cache_key, summary, CachePolicy.TTL_DASHBOARD_SUMMARY)
                record_cache(cache_area='dashboard', operation='set', result='refresh')
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
                record_cache(cache_area='dashboard', operation='set', result='error')
            return summary, 'REFRESHED'

        # 1. Cache is an optimization, not a permission to calculate in HTTP.
        try:
            val = cache.get(cache_key)
            if val is not None:
                record_cache(cache_area='dashboard', operation='get', result='hit')
                # A negative response can have been cached while a worker was
                # publishing the read model. Never let that old cache entry
                # force a user with a valid active portfolio back to import.
                if isinstance(val, dict) and not val.get('hasData'):
                    repaired_summary = (
                        cls._active_gold_dashboard_summary(workspace_id)
                        or cls._persisted_dashboard_summary(workspace_id)
                    )
                    if repaired_summary is not None:
                        try:
                            cache.set(
                                cache_key,
                                repaired_summary,
                                CachePolicy.TTL_DASHBOARD_SUMMARY,
                            )
                        except Exception as e:
                            logger.warning(
                                'Redis set failed while repairing dashboard cache: %s',
                                e,
                            )
                        return repaired_summary, 'HIT_REPAIRED'
                return val, 'HIT'
        except Exception as e:
            logger.warning('Redis read failure for dashboard summary: %s', e)
            record_cache(cache_area='dashboard', operation='get', result='error')
            gold_summary = cls._active_gold_dashboard_summary(workspace_id)
            if gold_summary is not None:
                return gold_summary, 'STALE_GOLD'
            persisted_summary = cls._persisted_dashboard_summary(workspace_id)
            return (
                persisted_summary or cls._stale_dashboard_payload(workspace_id),
                'STALE_PERSISTED',
            )

        # 2. A cache miss reads the compact gold aggregate only. The worker
        # populates this model at import finalization and warms Redis.
        record_cache(cache_area='dashboard', operation='get', result='miss')
        summary = cls._active_gold_dashboard_summary(workspace_id)
        if summary is None:
            summary = cls._persisted_dashboard_summary(workspace_id)
            if summary is None:
                return cls._stale_dashboard_payload(workspace_id), 'STALE_GOLD'
            cache_status = 'MISS_PERSISTED'
        else:
            cache_status = 'MISS_GOLD'
        try:
            cache.set(cache_key, summary, CachePolicy.TTL_DASHBOARD_SUMMARY)
        except Exception as e:
            logger.warning('Redis set failed for dashboard summary: %s', e)
        return summary, cache_status

    @classmethod
    def _calculate_executive_summary(cls, workspace_id: int) -> dict:
        """
        Reads the active gold aggregate first. Legacy data without an aggregate
        falls back to the ORM calculation until the next completed import.
        """
        gold_summary = cls._active_gold_dashboard_summary(workspace_id)
        if gold_summary is not None:
            return gold_summary

        persisted_summary = cls._persisted_dashboard_summary(workspace_id)
        if persisted_summary is not None:
            return persisted_summary

        all_assessments = SlowMovingRiskAssessment.objects.filter(session__workspace_id=workspace_id)
        total_skus = all_assessments.count()
        dataset_metadata = cls._dataset_metadata(workspace_id)

        if total_skus == 0:
            return {
                'hasData': False,
                'totalSkus': 0,
                'criticalCount': 0,
                'highRiskCount': 0,
                'mediumRiskCount': 0,
                'lowRiskCount': 0,
                'totalCapitalExposureVnd': 0.0,
                'atRiskCapitalVnd': 0.0,
                'agedCapitalVnd': 0.0,
                'agedSkuCount': 0,
                'riskCapitalByClassVnd': {
                    'CRITICAL': 0.0,
                    'HIGH_RISK': 0.0,
                    'MEDIUM_RISK': 0.0,
                    'LOW_RISK': 0.0,
                },
                'capitalStatus': 'NO_DATA',
                'topRiskSkus': [],
                'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
                'calculatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                **dataset_metadata,
            }

        critical_count = all_assessments.filter(risk_class='CRITICAL').count()
        high_count = all_assessments.filter(risk_class='HIGH_RISK').count()
        medium_count = all_assessments.filter(risk_class='MEDIUM_RISK').count()
        low_count = all_assessments.filter(risk_class='LOW_RISK').count()

        # 1. Aggregate capital & metrics across ALL SKUs (NOT [:5])
        total_capital = 0.0
        at_risk_capital = 0.0
        aged_capital = 0.0
        aged_sku_count = 0
        risk_capital_by_class = {
            'CRITICAL': 0.0,
            'HIGH_RISK': 0.0,
            'MEDIUM_RISK': 0.0,
            'LOW_RISK': 0.0,
        }
        has_observed_inventory = False

        for a in all_assessments:
            ev = a.evidence if isinstance(a.evidence, dict) else {}
            stock_qty = ev.get('stock_quantity')
            unit_cost = ev.get('unit_cost')
            real_cap = ev.get('capital_exposure_vnd')

            if real_cap is not None and real_cap > 0:
                cap_val = float(real_cap)
                has_observed_inventory = True
            elif stock_qty is not None and unit_cost is not None and stock_qty > 0 and unit_cost > 0:
                cap_val = float(stock_qty * unit_cost)
                has_observed_inventory = True
            elif ev.get('sold_90d'):
                cap_val = float(ev['sold_90d'] * 150000)
            else:
                cap_val = 0.0

            total_capital += cap_val
            if a.risk_class in risk_capital_by_class:
                risk_capital_by_class[a.risk_class] += cap_val
            if a.risk_class in ['CRITICAL', 'HIGH_RISK']:
                at_risk_capital += cap_val
            if (ev.get('dsls') or 0) > 90:
                aged_capital += cap_val
                aged_sku_count += 1

        # 2. Extract Top 5 priority SKUs separately (highest capital exposure among CRITICAL/HIGH risk SKUs)
        assessments_list = list(all_assessments)
        assessments_list.sort(
            key=lambda item: (
                float(item.evidence.get('capital_exposure_vnd', 0) if isinstance(item.evidence, dict) else 0),
                1 if item.risk_class == 'CRITICAL' else (0.5 if item.risk_class == 'HIGH_RISK' else 0)
            ),
            reverse=True
        )
        top_risk_skus = []
        for a in (
            item for item in assessments_list
            if item.risk_class in {'CRITICAL', 'HIGH_RISK'}
        ):
            if len(top_risk_skus) == 5:
                break
            ev = a.evidence if isinstance(a.evidence, dict) else {}
            cap_val = float(ev.get('capital_exposure_vnd') or 0.0)
            top_risk_skus.append({
                'sku': a.sku,
                'name': a.product_name,
                'riskClass': a.risk_class,
                'riskScore': a.risk_score,
                'capitalExposureVnd': cap_val,
                'daysInInventory': ev.get('dsls', 0)
            })

        # Determine capital status (STRICT DATA INTEGRITY — No fake fallbacks)
        capital_status = 'OBSERVED' if has_observed_inventory else 'ESTIMATED'

        return {
            'hasData': True,
            'totalSkus': total_skus,
            'criticalCount': critical_count,
            'highRiskCount': high_count,
            'mediumRiskCount': medium_count,
            'lowRiskCount': low_count,
            'totalCapitalExposureVnd': total_capital,
            'atRiskCapitalVnd': at_risk_capital,
            'agedCapitalVnd': aged_capital,
            'agedSkuCount': aged_sku_count,
            'riskCapitalByClassVnd': risk_capital_by_class,
            'capitalStatus': capital_status,
            'topRiskSkus': top_risk_skus,
            'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
            'calculatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            **dataset_metadata,
        }
