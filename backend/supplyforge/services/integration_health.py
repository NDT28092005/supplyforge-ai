"""Data-health facts for an Odoo connection."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from supplyforge.models import (
    IntegrationConnection, IntegrationDataHealthSnapshot, IntegrationSkuDailyMetric,
    IntegrationSkuMapping,
)


ACTIVE_MAPPING_STATUSES = (
    IntegrationSkuMapping.STATUS_AUTO,
    IntegrationSkuMapping.STATUS_CONFIRMED,
)


class IntegrationHealthService:
    """Computes Odoo data health from persisted facts, never from guesses."""

    @classmethod
    def refresh(cls, connection: IntegrationConnection) -> dict:
        latest_date = IntegrationSkuDailyMetric.objects.filter(connection=connection).aggregate(value=Max('metric_date'))['value']
        latest_observed_at = IntegrationSkuDailyMetric.objects.filter(connection=connection).aggregate(value=Max('source_updated_at'))['value']
        total = connection.sku_mappings.exclude(status=IntegrationSkuMapping.STATUS_IGNORED).count()
        mapped = connection.sku_mappings.filter(status__in=ACTIVE_MAPPING_STATUSES).count()
        current_inventory = 0
        missing_cost = 0
        if latest_date:
            metrics = IntegrationSkuDailyMetric.objects.filter(connection=connection, metric_date=latest_date)
            current_inventory = metrics.filter(on_hand_quantity__isnull=False).values('external_sku').distinct().count()
            missing_cost = metrics.filter(on_hand_quantity__isnull=False, unit_cost__isnull=True).values('external_sku').distinct().count()
        overdue = (
            not connection.last_successful_sync_at
            or connection.last_successful_sync_at < timezone.now() - timedelta(minutes=max(1, connection.sync_interval_minutes) * 2)
        )
        health_status = (
            'NO_DATA' if not latest_date else
            'STALE' if overdue else
            'MAPPING_REQUIRED' if total and mapped < total else
            'INVENTORY_REQUIRED' if current_inventory == 0 else
            'READY'
        )
        coverage = Decimal(mapped) / Decimal(total) if total else Decimal('0')
        snapshot, _ = IntegrationDataHealthSnapshot.objects.update_or_create(
            connection=connection,
            defaults={
                'source_data_as_of': timezone.make_aware(datetime.combine(latest_date, time.max)) if latest_date else None,
                'source_observed_at': latest_observed_at,
                'status': health_status,
                'mapped_sku_count': mapped,
                'total_sku_count': total,
                'mapping_coverage_rate': coverage,
                'verified_inventory_sku_count': current_inventory,
                'missing_cost_sku_count': missing_cost,
                'details_json': {'sync_interval_minutes': connection.sync_interval_minutes},
            },
        )
        return cls.serialize(snapshot)

    @staticmethod
    def serialize(snapshot: IntegrationDataHealthSnapshot | None) -> dict | None:
        if not snapshot:
            return None
        return {
            'status': snapshot.status,
            'source_data_as_of': snapshot.source_data_as_of.isoformat() if snapshot.source_data_as_of else None,
            'source_observed_at': snapshot.source_observed_at.isoformat() if snapshot.source_observed_at else None,
            'mapping': {
                'mapped_sku_count': snapshot.mapped_sku_count,
                'total_sku_count': snapshot.total_sku_count,
                'coverage_rate': float(snapshot.mapping_coverage_rate),
            },
            'verified_inventory_sku_count': snapshot.verified_inventory_sku_count,
            'missing_cost_sku_count': snapshot.missing_cost_sku_count,
            'calculated_at': snapshot.calculated_at.isoformat(),
        }
