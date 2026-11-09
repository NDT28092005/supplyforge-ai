"""Runtime implementation of the versioned temporal demand feature contract.

This service intentionally reads only canonical SKU, fulfilled order events and
their quantities. It neither loads buyer PII nor substitutes a mutable product
stock field for a historical demand feature.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.db.models import DateTimeField, F, Max, Min, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from supplyforge.models import DemandReturnEvent, OrderItem, Workspace


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = PROJECT_ROOT / "config" / "temporal_demand_risk_feature_contract.json"


class FeatureContractIncomplete(Exception):
    """Raised when live merchant data cannot truthfully reproduce the contract."""


@dataclass(frozen=True)
class TemporalFeatureSnapshot:
    canonical_sku: str
    user_id: str
    decision_cutoff: datetime
    values: dict[str, float]
    historical_total_qty: float
    first_sale_at: datetime
    last_sale_at: datetime
    qualifying_order_count: int


class TemporalFeatureService:
    """Build the exact 19-feature vector used by the temporal benchmark."""

    def __init__(self, contract_path: Path = CONTRACT_PATH):
        self.contract_path = Path(contract_path)
        self.contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        self.feature_columns = tuple(self.contract["feature_columns"])
        self.valid_statuses = tuple(self.contract["source_policy"]["accepted_order_statuses"])

    @staticmethod
    def workspace_owner_user_id(workspace_id: int | str) -> str:
        workspace = Workspace.objects.filter(id=workspace_id).only("owner_id").first()
        if not workspace or not workspace.owner_id:
            raise FeatureContractIncomplete("Workspace has no owner identity for demand-event scoping.")
        return str(workspace.owner_id)

    @staticmethod
    def _as_aware_cutoff(as_of: datetime | None) -> datetime:
        cutoff = as_of or timezone.now()
        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff, timezone.get_current_timezone())
        # A decision cutoff includes fulfilled events through that calendar day,
        # matching the offline benchmark's feature window convention.
        return cutoff.replace(hour=23, minute=59, second=59, microsecond=999999)

    def extract(
        self,
        canonical_sku: str,
        *,
        user_id: str,
        workspace_id: int | str | None = None,
        as_of: datetime | None = None,
    ) -> TemporalFeatureSnapshot:
        canonical_sku = str(canonical_sku or "").strip()
        if not canonical_sku:
            raise FeatureContractIncomplete("Canonical SKU is required for temporal inference.")
        cutoff = self._as_aware_cutoff(as_of)

        # `demand_eligibility_verified` prevents legacy generic CSV records
        # from being treated as completed/non-returned ERP events by default.
        filters = {
            "canonical_sku": canonical_sku,
            "quantity__gt": 0,
            "order__user_id": str(user_id),
            "order__status__in": self.valid_statuses,
            "order__return_identifier__isnull": True,
            "order__is_accounting": True,
            "order__demand_eligibility_verified": True,
        }
        if workspace_id is not None:
            filters["order__workspace_id"] = int(workspace_id)
        qualifying = (
            OrderItem.objects.filter(**filters)
            .annotate(
                event_time=Coalesce(
                    F("order__source_event_at"),
                    F("order__created_at"),
                    output_field=DateTimeField(),
                )
            )
            .filter(event_time__isnull=False, event_time__lte=cutoff)
        )
        aggregate = qualifying.aggregate(
            total=Sum("quantity"),
            first_event=Min("event_time"),
            last_event=Max("event_time"),
        )
        returns = DemandReturnEvent.objects.filter(
            workspace_id=workspace_id,
            canonical_sku=canonical_sku,
            quantity__gt=0,
            occurred_at__lte=cutoff,
        )
        returned_total = float(returns.aggregate(total=Sum('quantity'))['total'] or 0.0)
        historical_total = max(0.0, float(aggregate["total"] or 0.0) - returned_total)
        if historical_total <= 5 or not aggregate["first_event"] or not aggregate["last_event"]:
            raise FeatureContractIncomplete(
                "At least 6 net fulfilled accounting units with verified source semantics are required."
            )

        daily_rows = (
            qualifying.annotate(event_day=TruncDate("event_time"))
            .values("event_day")
            .annotate(quantity=Sum("quantity"))
            .order_by("event_day")
        )
        daily = {row["event_day"]: float(row["quantity"] or 0.0) for row in daily_rows}
        return_rows = (
            returns.annotate(event_day=TruncDate('occurred_at'))
            .values('event_day').annotate(quantity=Sum('quantity')).order_by('event_day')
        )
        for row in return_rows:
            event_day = row['event_day']
            daily[event_day] = max(0.0, daily.get(event_day, 0.0) - float(row['quantity'] or 0.0))
        cutoff_day = cutoff.date()

        def window(days: int) -> list[float]:
            start = cutoff_day - timedelta(days=days - 1)
            return [daily.get(start + timedelta(days=offset), 0.0) for offset in range(days)]

        recent_7, recent_30, recent_60, recent_90 = (window(days) for days in (7, 30, 60, 90))
        sum_7, sum_30, sum_60, sum_90 = (sum(values) for values in (recent_7, recent_30, recent_60, recent_90))
        nonzero_90 = [value for value in recent_90 if value > 0]
        nonzero_count = len(nonzero_90)
        positive_mean = sum_90 / nonzero_count if nonzero_count else 0.0
        if nonzero_count > 1 and positive_mean > 0:
            variance = sum((value - positive_mean) ** 2 for value in nonzero_90) / (nonzero_count - 1)
            cv2 = variance / (positive_mean ** 2)
        else:
            cv2 = 0.0

        first_sale = aggregate["first_event"]
        last_sale = aggregate["last_event"]
        lifetime_days = max(1, (cutoff_day - first_sale.date()).days + 1)
        dsls = max(0, (cutoff_day - last_sale.date()).days)
        values = {
            "historical_total_qty": historical_total,
            "sales_qty_7d": sum_7,
            "sales_qty_30d": sum_30,
            "sales_qty_60d": sum_60,
            "sales_qty_90d": sum_90,
            "sales_velocity_7d": sum_7 / 7,
            "sales_velocity_30d": sum_30 / 30,
            "sales_velocity_60d": sum_60 / 60,
            "sales_velocity_90d": sum_90 / 90,
            "zero_rate_30d": sum(value == 0 for value in recent_30) / 30,
            "zero_rate_60d": sum(value == 0 for value in recent_60) / 60,
            "zero_rate_90d": sum(value == 0 for value in recent_90) / 90,
            "dsls": float(dsls),
            "adi_90d": 90 / nonzero_count if nonzero_count else 90.0,
            "cv2_90d": cv2,
            "lifetime_days": float(lifetime_days),
            "lifetime_velocity": historical_total / lifetime_days,
            "recent_7_to_30_ratio": (sum_7 / 7) / (sum_30 / 30) if sum_30 else 0.0,
            "recent_30_to_90_ratio": (sum_30 / 30) / (sum_90 / 90) if sum_90 else 0.0,
        }
        missing = [name for name in self.feature_columns if name not in values]
        if missing:
            raise FeatureContractIncomplete(f"Feature implementation is incomplete: {missing}")
        return TemporalFeatureSnapshot(
            canonical_sku=canonical_sku,
            user_id=str(user_id),
            decision_cutoff=cutoff,
            values={name: float(values[name]) for name in self.feature_columns},
            historical_total_qty=historical_total,
            first_sale_at=first_sale,
            last_sale_at=last_sale,
            qualifying_order_count=qualifying.count(),
        )

    def extract_for_workspace(
        self, canonical_sku: str, workspace_id: int | str, as_of: datetime | None = None
    ) -> TemporalFeatureSnapshot:
        return self.extract(
            canonical_sku,
            user_id=self.workspace_owner_user_id(workspace_id),
            workspace_id=workspace_id,
            as_of=as_of,
        )
