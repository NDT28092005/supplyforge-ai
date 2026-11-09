"""Truth gate for stock and capital-impact claims.

Demand risk can be assessed from verified sales events. Capital impact is a
separate claim and is withheld unless an explicit, recent inventory snapshot
contains available quantity, cost and lifecycle state for the canonical SKU.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections import defaultdict
from typing import Any

from django.db.models import OuterRef, Subquery

from supplyforge.models import InventoryRecord


@dataclass(frozen=True)
class InventoryReadiness:
    ready: bool
    status: str
    reasons: tuple[str, ...]
    available_quantity: float | None = None
    unit_cost: float | None = None
    unit_selling_price: float | None = None
    capital_exposure: float | None = None
    record_date: date | None = None
    lifecycle_status: str | None = None
    warehouse_count: int = 0


class InventoryReadinessGate:
    """Evaluate availability of the minimum data needed for capital claims."""

    MAX_SNAPSHOT_AGE_DAYS = 1
    KNOWN_LIFECYCLE_STATES = {"ACTIVE", "DISCONTINUED", "ARCHIVED", "INACTIVE"}

    @staticmethod
    def has_source_lineage(record: InventoryRecord) -> bool:
        """Require at least one durable reference to the source snapshot."""
        return bool(
            record.source_snapshot_id
            or record.source_checksum
            or record.source_lineage_json
            or record.data_source_id
        )

    @classmethod
    def evaluate(cls, *, workspace_id: int | str, canonical_sku: str, as_of: date) -> InventoryReadiness:
        base = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id,
            canonical_sku=str(canonical_sku),
            record_date__lte=as_of,
        )
        # A SKU may have stock at multiple warehouses. Selecting a single
        # newest row would silently understate its available stock and tied-up
        # capital, so use the newest evidence independently per warehouse.
        latest_for_warehouse = (
            InventoryRecord.objects.filter(
                sku__workspace_id=workspace_id,
                canonical_sku=str(canonical_sku),
                warehouse_code=OuterRef("warehouse_code"),
                record_date__lte=as_of,
            )
            .order_by("-record_date", "-updated_at", "-id")
            .values("id")[:1]
        )
        records = list(
            base.filter(id=Subquery(latest_for_warehouse))
            .order_by("warehouse_code", "-record_date", "-updated_at", "-id")
        )
        if not records:
            return InventoryReadiness(False, "INVENTORY_UNAVAILABLE", ("No as-of inventory snapshot for canonical SKU.",))

        reasons: list[str] = []
        available = 0.0
        capital = 0.0
        unit_costs: set[float] = set()
        selling_prices: set[float] = set()
        lifecycle_states: set[str] = set()
        record_dates: list[date] = []
        for record in records:
            warehouse = (record.warehouse_code or "UNSPECIFIED").strip() or "UNSPECIFIED"
            prefix = f"Warehouse {warehouse}: "
            record_dates.append(record.record_date)
            if not record.as_of_verified:
                reasons.append(prefix + "inventory snapshot source has not been verified.")
            if not cls.has_source_lineage(record):
                reasons.append(prefix + "inventory snapshot has no source lineage or source snapshot identifier.")
            if (as_of - record.record_date).days > cls.MAX_SNAPSHOT_AGE_DAYS:
                reasons.append(prefix + "inventory snapshot is older than the allowed as-of freshness window.")
            if record.available_quantity is None or record.available_quantity < 0:
                reasons.append(prefix + "available inventory quantity is missing.")
            if record.cost_price is None or record.cost_price < 0:
                reasons.append(prefix + "unit cost is missing or invalid.")
            lifecycle = (record.lifecycle_status or "UNKNOWN").upper()
            lifecycle_states.add(lifecycle)
            if lifecycle not in cls.KNOWN_LIFECYCLE_STATES:
                reasons.append(prefix + "SKU lifecycle status is missing or unknown.")
            if record.available_quantity is not None and record.available_quantity >= 0:
                available += float(record.available_quantity)
            if record.cost_price is not None and record.cost_price >= 0:
                cost = float(record.cost_price)
                unit_costs.add(cost)
                if record.available_quantity is not None and record.available_quantity >= 0:
                    capital += float(record.available_quantity) * cost
            if record.selling_price is not None and record.selling_price >= 0:
                selling_prices.add(float(record.selling_price))
        if reasons:
            return InventoryReadiness(
                False,
                "INVENTORY_INCOMPLETE",
                tuple(reasons),
                record_date=min(record_dates),
                lifecycle_status=", ".join(sorted(lifecycle_states)),
                warehouse_count=len(records),
            )
        return InventoryReadiness(
            True,
            "READY",
            (),
            available_quantity=available,
            # A portfolio-level unit cost has no single truthful value when
            # warehouses carry different costs. Consumers must use the
            # aggregate capital value in that case.
            unit_cost=next(iter(unit_costs)) if len(unit_costs) == 1 else None,
            unit_selling_price=next(iter(selling_prices)) if len(selling_prices) == 1 else None,
            capital_exposure=max(0.0, capital),
            record_date=min(record_dates),
            lifecycle_status=", ".join(sorted(lifecycle_states)),
            warehouse_count=len(records),
        )


class InventoryReadinessReportService:
    """Report observed inventory evidence without fabricating stock or cost coverage."""

    @classmethod
    def _latest_records(cls, *, workspace_id: int | str, as_of: date):
        base = InventoryRecord.objects.filter(
            sku__workspace_id=workspace_id,
            record_date__lte=as_of,
        )
        latest_for_pair = (
            InventoryRecord.objects.filter(
                sku__workspace_id=workspace_id,
                record_date__lte=as_of,
                canonical_sku=OuterRef("canonical_sku"),
                warehouse_code=OuterRef("warehouse_code"),
            )
            .order_by("-record_date", "-updated_at", "-id")
            .values("id")[:1]
        )
        return base.filter(id=Subquery(latest_for_pair)).select_related("sku", "data_source")

    @classmethod
    def report(cls, *, workspace_id: int | str, as_of: date) -> dict[str, Any]:
        """Summarise the latest SKU/warehouse snapshot at or before ``as_of``.

        This is a data-completeness report. A high coverage value does not
        imply the model caused an inventory or capital outcome.
        """
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        total: dict[str, int] = defaultdict(int)
        records = cls._latest_records(workspace_id=workspace_id, as_of=as_of)
        for record in records.iterator(chunk_size=2_000):
            warehouse = (record.warehouse_code or "").strip() or "UNSPECIFIED"
            total["snapshot_pairs"] += 1
            total["distinct_sku_warehouse_pairs"] += 1
            bucket = buckets[warehouse]
            bucket["snapshot_pairs"] += 1
            canonical_sku = (record.canonical_sku or "").strip()
            lifecycle = (record.lifecycle_status or "UNKNOWN").upper()
            stale = (as_of - record.record_date).days > InventoryReadinessGate.MAX_SNAPSHOT_AGE_DAYS
            lineage = InventoryReadinessGate.has_source_lineage(record)
            available = record.available_quantity is not None and record.available_quantity >= 0
            cost = record.cost_price is not None and record.cost_price >= 0
            lifecycle_known = lifecycle in InventoryReadinessGate.KNOWN_LIFECYCLE_STATES
            markdown_valid = record.markdown_rate is not None and 0 <= record.markdown_rate <= 1
            checks = {
                "missing_canonical_sku": not canonical_sku,
                "unverified_as_of": not record.as_of_verified,
                "stale_snapshot": stale,
                "missing_available_quantity": not available,
                "missing_or_invalid_unit_cost": not cost,
                "missing_or_unknown_lifecycle": not lifecycle_known,
                "missing_source_lineage": not lineage,
                "missing_source_observed_at": record.source_observed_at is None,
                "missing_or_invalid_markdown_rate": not markdown_valid,
            }
            capital_ready = not any(
                checks[key]
                for key in (
                    "missing_canonical_sku", "unverified_as_of", "stale_snapshot",
                    "missing_available_quantity", "missing_or_invalid_unit_cost",
                    "missing_or_unknown_lifecycle", "missing_source_lineage",
                )
            )
            for name, missing in checks.items():
                if missing:
                    total[name] += 1
                    bucket[name] += 1
            if capital_ready:
                total["ready_for_capital_claims"] += 1
                bucket["ready_for_capital_claims"] += 1

        pair_count = total["snapshot_pairs"]
        metric_names = (
            "ready_for_capital_claims", "missing_canonical_sku", "unverified_as_of", "stale_snapshot",
            "missing_available_quantity", "missing_or_invalid_unit_cost", "missing_or_unknown_lifecycle",
            "missing_source_lineage", "missing_source_observed_at", "missing_or_invalid_markdown_rate",
        )

        def serialise(name: str, values: dict[str, int]) -> dict[str, Any]:
            rows = values["snapshot_pairs"]
            return {
                "warehouse_code": name,
                "snapshot_pairs": rows,
                **{metric: int(values[metric]) for metric in metric_names},
                "capital_claim_coverage_pct": round(values["ready_for_capital_claims"] / rows * 100, 1) if rows else 0.0,
            }

        return {
            "scope": (
                "Latest explicit SKU/warehouse inventory records at or before the requested date. "
                "Coverage is a data-quality measure, not evidence of capital reduction or causal model impact."
            ),
            "workspace_id": int(workspace_id),
            "as_of": as_of.isoformat(),
            "portfolio": {
                "snapshot_pairs": pair_count,
                **{metric: int(total[metric]) for metric in metric_names},
                "capital_claim_coverage_pct": round(total["ready_for_capital_claims"] / pair_count * 100, 1) if pair_count else 0.0,
            },
            "by_warehouse": [
                serialise(name, buckets[name]) for name in sorted(buckets)
            ],
        }
