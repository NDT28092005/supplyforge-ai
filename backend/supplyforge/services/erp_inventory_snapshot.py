"""Project provider-neutral ERP inventory facts into auditable inventory snapshots."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from django.db.models import Max
from django.utils import timezone

from supplyforge.models import IntegrationConnection, IntegrationSkuDailyMetric, IntegrationSkuMapping, InventoryRecord, Sku


class ErpInventorySnapshotProjectionService:
    """Materialise only observed ERP inventory, never inferred stock values."""

    ACTIVE_MAPPING_STATUSES = (
        IntegrationSkuMapping.STATUS_AUTO,
        IntegrationSkuMapping.STATUS_CONFIRMED,
    )

    @staticmethod
    def _checksum(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def refresh(cls, connection: IntegrationConnection) -> dict[str, Any]:
        mappings = list(
            IntegrationSkuMapping.objects.filter(
                connection=connection,
                status__in=cls.ACTIVE_MAPPING_STATUSES,
                canonical_product__isnull=False,
            ).select_related("canonical_product")
        )
        reference_date = IntegrationSkuDailyMetric.objects.filter(connection=connection).aggregate(
            value=Max("metric_date")
        )["value"]
        summary = {
            "status": "READY",
            "connection_id": str(connection.id),
            "source_data_as_of": reference_date.isoformat() if reference_date else None,
            "mapped_skus": len(mappings),
            "projected_inventory_records": 0,
            "missing_on_hand_records": 0,
            "missing_unit_cost_records": 0,
            "markdown_rate_available_records": 0,
        }
        if not reference_date or not mappings:
            summary["status"] = "NO_MAPPED_ERP_FACTS"
            return summary

        mappings_by_external_sku = {mapping.external_sku: mapping for mapping in mappings}
        metric_rows = (
            IntegrationSkuDailyMetric.objects.filter(
                connection=connection,
                metric_date=reference_date,
                external_sku__in=mappings_by_external_sku,
            ).select_related("connection")
        )
        for metric in metric_rows.iterator(chunk_size=2_000):
            mapping = mappings_by_external_sku[metric.external_sku]
            canonical_sku = (mapping.canonical_sku or mapping.canonical_product.canonical_sku or mapping.external_sku).strip()
            if not canonical_sku:
                continue
            sku_record = (
                Sku.objects.filter(workspace=connection.workspace, normalized_name=canonical_sku)
                .order_by("id")
                .first()
            )
            if not sku_record:
                sku_record = Sku.objects.create(
                    workspace=connection.workspace,
                    original_name=mapping.canonical_product.product_name or canonical_sku,
                    normalized_name=canonical_sku,
                )
            warehouse_code = (metric.warehouse_id or metric.warehouse_name or "UNSPECIFIED").strip()
            source_snapshot_id = f"{connection.provider}:{connection.id}:{reference_date}:{metric.external_sku}:{warehouse_code}"
            source_lineage = {
                "provider": connection.provider,
                "connection_id": str(connection.id),
                "mapping_id": mapping.id,
                "external_sku": metric.external_sku,
                "warehouse_id": metric.warehouse_id,
                "warehouse_name": metric.warehouse_name,
                "metric_date": reference_date.isoformat(),
                "source_updated_at": metric.source_updated_at.isoformat() if metric.source_updated_at else None,
                "markdown_rate": "UNAVAILABLE_NO_VERIFIED_LIST_PRICE_HISTORY",
            }
            checksum = cls._checksum({
                "source_snapshot_id": source_snapshot_id,
                "on_hand_quantity": metric.on_hand_quantity,
                "unit_cost": metric.unit_cost,
                "unit_price": metric.unit_price,
                "source_metadata": metric.source_metadata,
            })
            values = {
                "quantity": metric.on_hand_quantity if metric.on_hand_quantity is not None else Decimal("0"),
                "cost_price": metric.unit_cost,
                "selling_price": metric.unit_price,
                "available_quantity": metric.on_hand_quantity,
                "reserved_quantity": None,
                "lifecycle_status": "ACTIVE" if mapping.canonical_product.active_on_web else "INACTIVE",
                "as_of_verified": True,
                "source_snapshot_id": source_snapshot_id,
                "source_observed_at": metric.source_updated_at or connection.last_successful_sync_at or timezone.now(),
                "source_checksum": checksum,
                "source_lineage_json": source_lineage,
                "markdown_rate": None,
            }
            record = (
                InventoryRecord.objects.filter(
                    sku=sku_record,
                    canonical_sku=canonical_sku,
                    warehouse_code=warehouse_code,
                    record_date=reference_date,
                ).order_by("-updated_at", "-id").first()
            )
            if record:
                for field, value in values.items():
                    setattr(record, field, value)
                record.save(update_fields=[*values, "updated_at"])
            else:
                InventoryRecord.objects.create(
                    sku=sku_record,
                    canonical_sku=canonical_sku,
                    warehouse_code=warehouse_code,
                    record_date=reference_date,
                    **values,
                )
            summary["projected_inventory_records"] += 1
            if metric.on_hand_quantity is None:
                summary["missing_on_hand_records"] += 1
            if metric.unit_cost is None or metric.unit_cost < 0:
                summary["missing_unit_cost_records"] += 1
        return summary
