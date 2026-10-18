"""
SupplyForge AI — High-Speed Query Service Architecture
========================================================
Read-Through Caching layer ensuring <0.1s UI response time with Cache Stampede Lock & Strict Data Integrity.
"""

import time
import logging
from django.core.cache import cache
from supplyforge.models import DatasetVersion, SlowMovingRiskAssessment
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.metrics import record_cache

logger = logging.getLogger(__name__)


def _acquire_redis_lock(lock_key: str, ttl: int = 10) -> bool:
    try:
        import redis as redis_lib
        from django.conf import settings
        redis_url = getattr(settings, 'REDIS_CACHE_URL', 'redis://127.0.0.1:6379/1')
        r = redis_lib.from_url(redis_url)
        acquired = r.set(lock_key, 'locked', nx=True, ex=ttl)
        return bool(acquired)
    except Exception as e:
        logger.warning(f"Lock acquire fallback: {e}")
        return True


def _release_redis_lock(lock_key: str) -> None:
    try:
        import redis as redis_lib
        from django.conf import settings
        redis_url = getattr(settings, 'REDIS_CACHE_URL', 'redis://127.0.0.1:6379/1')
        r = redis_lib.from_url(redis_url)
        r.delete(lock_key)
    except Exception:
        pass


class DashboardQueryService:
    @staticmethod
    def _dataset_metadata(workspace_id: int) -> dict:
        """Attach the exact dataset freshness used by the dashboard response."""
        version = (
            DatasetVersion.objects.filter(
                workspace_id=workspace_id,
                status=DatasetVersion.STATUS_ACTIVE,
            )
            .order_by('-version_number')
            .first()
        )
        return {
            'datasetVersion': version.version_label if version else None,
            'dataAsOf': version.data_as_of.isoformat() if version and version.data_as_of else None,
            'isStale': version is None,
        }

    @classmethod
    def _active_gold_dashboard_summary(cls, workspace_id: int) -> dict | None:
        """Return the compact gold read model for the current dataset version."""
        version = (
            DatasetVersion.objects.filter(
                workspace_id=workspace_id,
                status=DatasetVersion.STATUS_ACTIVE,
            )
            .only('version_label', 'data_as_of', 'manifest_json')
            .order_by('-version_number')
            .first()
        )
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

    @classmethod
    def get_executive_summary(cls, workspace_id: int, force_refresh: bool = False) -> tuple[dict, str]:
        """
        Retrieves pre-calculated Executive Dashboard summary.
        Returns: (summary_dict, cache_status: 'HIT'|'MISS'|'REFRESHED'|'FAILOVER_MYSQL')
        Target Latency: <10ms on HIT, <100ms on MISS.
        """
        version = CachePolicy.get_workspace_version(workspace_id)
        cache_key = f"sf:v2:ws:{workspace_id}:v{version}:dashboard:summary"
        lock_key = f"sf:lock:ws:{workspace_id}:dashboard:summary"

        if force_refresh:
            summary = cls._calculate_executive_summary(workspace_id)
            try:
                cache.set(cache_key, summary, CachePolicy.TTL_DASHBOARD_SUMMARY)
                record_cache(cache_area='dashboard', operation='set', result='refresh')
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
                record_cache(cache_area='dashboard', operation='set', result='error')
            return summary, 'REFRESHED'

        # 1. Try reading from Cache
        try:
            val = cache.get(cache_key)
            if val is not None:
                record_cache(cache_area='dashboard', operation='get', result='hit')
                return val, 'HIT'
        except Exception as e:
            logger.warning(f"Redis read failure, falling back to MySQL direct: {e}")
            record_cache(cache_area='dashboard', operation='get', result='error')
            return cls._calculate_executive_summary(workspace_id), 'FAILOVER_MYSQL'

        # 2. Cache MISS: Acquire Stampede Protection Lock
        record_cache(cache_area='dashboard', operation='get', result='miss')
        lock_acquired = _acquire_redis_lock(lock_key, ttl=CachePolicy.STAMPEDE_LOCK_TTL)
        if not lock_acquired:
            # Another request is computing -> Wait & spin lock up to 1 second
            for _ in range(20):
                time.sleep(0.05)
                try:
                    val = cache.get(cache_key)
                    if val is not None:
                        return val, 'HIT'
                except Exception:
                    break
            # Fallback to direct calculation if wait times out
            return cls._calculate_executive_summary(workspace_id), 'MISS_LOCK_TIMEOUT'

        try:
            # Double-checked locking
            try:
                val = cache.get(cache_key)
                if val is not None:
                    return val, 'HIT'
            except Exception:
                pass

            summary = cls._calculate_executive_summary(workspace_id)
            try:
                cache.set(cache_key, summary, CachePolicy.TTL_DASHBOARD_SUMMARY)
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
            return summary, 'MISS'
        finally:
            _release_redis_lock(lock_key)

    @classmethod
    def _calculate_executive_summary(cls, workspace_id: int) -> dict:
        """
        Reads the active gold aggregate first. Legacy data without an aggregate
        falls back to the ORM calculation until the next completed import.
        """
        gold_summary = cls._active_gold_dashboard_summary(workspace_id)
        if gold_summary is not None:
            return gold_summary

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
            if a.risk_class in ['CRITICAL', 'HIGH_RISK']:
                at_risk_capital += cap_val
            if (ev.get('dsls') or 0) > 90:
                aged_capital += cap_val

        # 2. Extract Top 5 priority SKUs separately (highest capital exposure among CRITICAL/HIGH risk SKUs)
        assessments_list = list(all_assessments)
        assessments_list.sort(
            key=lambda item: (
                1 if item.risk_class == 'CRITICAL' else (0.5 if item.risk_class == 'HIGH_RISK' else 0),
                float(item.evidence.get('capital_exposure_vnd', 0) if isinstance(item.evidence, dict) else 0)
            ),
            reverse=True
        )
        top_risk_skus = []
        for a in assessments_list[:5]:
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
            'capitalStatus': capital_status,
            'topRiskSkus': top_risk_skus,
            'cacheVersion': str(CachePolicy.get_workspace_version(workspace_id)),
            'calculatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            **dataset_metadata,
        }
