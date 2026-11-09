"""Provider-neutral, non-causal reconciliation of completed action plans."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Sum
from django.utils import timezone

from supplyforge.models import (
    ActionPlanOutcomeObservation,
    ActionPlanRecord,
    IntegrationConnection,
    IntegrationSkuDailyMetric,
    IntegrationSkuMapping,
)


class ActionOutcomeReconciliationService:
    """Attach ERP measurements without claiming that an action caused them."""

    ACTIVE_MAPPING_STATUSES = (
        IntegrationSkuMapping.STATUS_AUTO,
        IntegrationSkuMapping.STATUS_CONFIRMED,
    )

    @classmethod
    def reconcile_connection(cls, *, connection: IntegrationConnection, as_of: date | None = None) -> dict[str, Any]:
        as_of = as_of or timezone.localdate()
        plans = ActionPlanRecord.objects.filter(
            workspace_id=connection.workspace_id,
            status="COMPLETED",
        )
        summary = {
            "connection_id": str(connection.id),
            "workspace_id": connection.workspace_id,
            "as_of": as_of.isoformat(),
            "completed_plans_considered": 0,
            "observed": 0,
            "partial": 0,
            "unavailable": 0,
        }
        for plan in plans.iterator(chunk_size=500):
            summary["completed_plans_considered"] += 1
            observation = cls._observe_plan(plan=plan, connection=connection, as_of=as_of)
            ActionPlanOutcomeObservation.objects.update_or_create(plan=plan, defaults=observation)
            if observation["status"] == ActionPlanOutcomeObservation.STATUS_OBSERVED:
                summary["observed"] += 1
            elif observation["status"] == ActionPlanOutcomeObservation.STATUS_PARTIAL:
                summary["partial"] += 1
            else:
                summary["unavailable"] += 1
        return summary

    @classmethod
    def reconcile_workspace(cls, *, workspace_id: int, as_of: date | None = None) -> dict[str, Any]:
        connections = IntegrationConnection.objects.filter(workspace_id=workspace_id, status=IntegrationConnection.STATUS_ACTIVE)
        reports = [cls.reconcile_connection(connection=connection, as_of=as_of) for connection in connections.iterator()]
        return {
            "workspace_id": workspace_id,
            "connection_count": len(reports),
            "connections": reports,
            "scope": "Read-only ERP observations; no causal attribution or automatic overwrite of merchant-entered outcomes.",
        }

    @classmethod
    def _observe_plan(cls, *, plan: ActionPlanRecord, connection: IntegrationConnection, as_of: date) -> dict[str, Any]:
        end = min(as_of, (plan.completed_at.date() if plan.completed_at else plan.due_date or as_of))
        start = plan.start_date
        missing: list[str] = []
        if end < start:
            missing.append("observation_window_not_started")
            return cls._unavailable(connection, start, end, missing)
        mapping = (
            IntegrationSkuMapping.objects.filter(
                connection=connection,
                canonical_sku=plan.sku,
                status__in=cls.ACTIVE_MAPPING_STATUSES,
            ).order_by("id").first()
        )
        if not mapping:
            return cls._unavailable(connection, start, end, ["confirmed_erp_sku_mapping"])
        metrics = IntegrationSkuDailyMetric.objects.filter(connection=connection, external_sku=mapping.external_sku)
        period = metrics.filter(metric_date__gte=start, metric_date__lte=end)
        observed_dates = set(period.values_list("metric_date", flat=True).distinct())
        source_start = min(observed_dates) if observed_dates else None
        source_end = max(observed_dates) if observed_dates else None
        if not source_start or not source_end:
            return cls._unavailable(connection, start, end, ["erp_daily_metrics_in_observation_window"], mapping=mapping)
        expected_dates = {start + timedelta(days=offset) for offset in range((end - start).days + 1)}
        missing_dates = sorted(expected_dates - observed_dates)
        if missing_dates:
            missing.append('continuous_erp_daily_metrics')
        sales = period.aggregate(
            sold=Sum("sales_quantity"),
            returned=Sum("returned_quantity"),
            revenue=Sum("revenue"),
            receipts=Sum("receipt_quantity"),
        )
        net_units = Decimal(sales["sold"] or 0) - Decimal(sales["returned"] or 0)
        sales_value = Decimal(sales["revenue"] or 0)
        opening = cls._inventory_state(metrics, start)
        closing = cls._inventory_state(metrics, end)
        if not opening or opening['date'] != start:
            missing.append("opening_inventory_snapshot")
        if not closing or closing['date'] != end:
            missing.append("closing_inventory_snapshot")
        inventory_change = None
        inventory_value_change = None
        if opening and closing and opening['date'] == start and closing['date'] == end:
            inventory_change = closing["quantity"] - opening["quantity"]
            unit_cost = closing["unit_cost"] if closing["unit_cost"] is not None else opening["unit_cost"]
            if unit_cost is None or unit_cost < 0:
                missing.append("unit_cost_for_inventory_value_change")
            else:
                inventory_value_change = inventory_change * unit_cost
        lineage = {
            "provider": connection.provider,
            "connection_id": str(connection.id),
            "mapping_id": mapping.id,
            "external_sku": mapping.external_sku,
            "canonical_sku": mapping.canonical_sku,
            "source_metric_window": {"start": source_start.isoformat(), "end": source_end.isoformat()},
            "coverage": {
                "expected_day_count": len(expected_dates),
                "observed_day_count": len(observed_dates),
                "continuous": not missing_dates,
                "missing_dates": [item.isoformat() for item in missing_dates[:31]],
                "missing_date_count": len(missing_dates),
            },
            "receipt_quantity_in_window": float(sales["receipts"] or 0),
            "return_quantity_in_window": float(sales["returned"] or 0),
            "confounders": {
                "receipts_in_window": float(sales["receipts"] or 0) > 0,
                "returns_in_window": float(sales["returned"] or 0) > 0,
                "concurrent_campaigns_unknown": True,
            },
            "interpretation": (
                "Sales and stock changes are observed ERP facts. Receipts, returns, concurrent campaigns and other "
                "confounders prevent causal attribution to this action plan."
            ),
        }
        status = ActionPlanOutcomeObservation.STATUS_OBSERVED if not missing else ActionPlanOutcomeObservation.STATUS_PARTIAL
        # A partial daily series can be useful for support investigation but
        # cannot safely be aggregated into a plan outcome. Withhold measured
        # values so dashboards do not silently compare a partial window with a
        # full-window forecast.
        coverage_complete = not missing_dates
        return {
            "connection": connection,
            "observation_start": start,
            "observation_end": end,
            "observed_net_units_sold": net_units if coverage_complete else None,
            "observed_sales_value": sales_value if coverage_complete else None,
            "opening_inventory_quantity": opening["quantity"] if opening and opening['date'] == start else None,
            "closing_inventory_quantity": closing["quantity"] if closing and closing['date'] == end else None,
            "observed_inventory_change": inventory_change if coverage_complete else None,
            "observed_inventory_value_change": inventory_value_change if coverage_complete else None,
            "status": status,
            "missing_fields_json": missing,
            "source_lineage_json": lineage,
        }

    @staticmethod
    def _inventory_state(metrics, through: date) -> dict[str, Decimal | date | None] | None:
        row = (
            metrics.filter(metric_date__lte=through, on_hand_quantity__isnull=False)
            .values("metric_date")
            .annotate(quantity=Sum("on_hand_quantity"), unit_cost=Avg("unit_cost"))
            .order_by("-metric_date")
            .first()
        )
        if not row:
            return None
        return {
            "date": row["metric_date"],
            "quantity": Decimal(row["quantity"] or 0),
            "unit_cost": Decimal(row["unit_cost"]) if row["unit_cost"] is not None else None,
        }

    @staticmethod
    def _unavailable(connection, start: date, end: date, missing: list[str], mapping=None) -> dict[str, Any]:
        return {
            "connection": connection,
            "observation_start": start,
            "observation_end": end,
            "observed_net_units_sold": None,
            "observed_sales_value": None,
            "opening_inventory_quantity": None,
            "closing_inventory_quantity": None,
            "observed_inventory_change": None,
            "observed_inventory_value_change": None,
            "status": ActionPlanOutcomeObservation.STATUS_UNAVAILABLE,
            "missing_fields_json": missing,
            "source_lineage_json": {
                "provider": connection.provider,
                "connection_id": str(connection.id),
                "mapping_id": mapping.id if mapping else None,
                "external_sku": mapping.external_sku if mapping else None,
                "interpretation": "No ERP outcome is inferred when mapping or the observation window is incomplete.",
            },
        }
