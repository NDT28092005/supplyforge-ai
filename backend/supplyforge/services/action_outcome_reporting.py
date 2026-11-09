"""Evidence-first reporting for operational action outcomes."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from supplyforge.models.action_plan import ActionPlanRecord
from supplyforge.models.action_plan import ActionPlanOutcomeObservation


class ActionOutcomeEvidenceService:
    """Separate observed merchant outcomes from missing and estimated values."""

    @classmethod
    def report(cls, *, workspace_id: int | str) -> dict[str, Any]:
        plans = list(
            ActionPlanRecord.objects.filter(workspace_id=workspace_id).only(
                "status", "strategy", "outcome_recorded_at", "expected_recovery_value",
                "actual_recovery_value", "expected_sales_value", "actual_sales_value",
                "expected_units_sold", "actual_units_sold",
            )
        )
        observations = {
            str(row.plan_id): row
            for row in ActionPlanOutcomeObservation.objects.filter(
                plan__workspace_id=workspace_id,
            ).select_related("plan")
        }
        completed = [plan for plan in plans if plan.status == "COMPLETED"]
        portfolio: dict[str, int] = defaultdict(int)
        strategies: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        erp: dict[str, int] = defaultdict(int)

        def add(target: dict[str, int], plan: ActionPlanRecord) -> None:
            target["completed_plans"] += 1
            observed = plan.outcome_recorded_at is not None
            if observed:
                target["plans_with_recorded_outcome"] += 1
            else:
                target["completed_without_recorded_outcome"] += 1
            fields = (
                ("inventory_cost_rotation", plan.expected_recovery_value, plan.actual_recovery_value),
                ("sales", plan.expected_sales_value, plan.actual_sales_value),
                ("units", plan.expected_units_sold, plan.actual_units_sold),
            )
            for prefix, expected, actual in fields:
                if actual is None:
                    target[f"missing_{prefix}_outcome"] += 1
                    continue
                target[f"observed_{prefix}_outcome"] += 1
                target[f"observed_expected_{prefix}_total"] += int(expected or 0)
                target[f"observed_actual_{prefix}_total"] += int(actual)

        for plan in completed:
            add(portfolio, plan)
            add(strategies[(plan.strategy or "UNSPECIFIED").strip() or "UNSPECIFIED"], plan)
            observation = observations.get(str(plan.plan_id))
            if not observation:
                erp["no_reconciled_observation"] += 1
                continue
            erp[f"{observation.status.lower()}_observation"] += 1
            if observation.observed_net_units_sold is not None:
                erp["observed_net_units_sold"] += float(observation.observed_net_units_sold)
            if observation.observed_sales_value is not None:
                erp["observed_sales_value"] += float(observation.observed_sales_value)
            if observation.observed_inventory_change is not None:
                erp["observed_inventory_change"] += float(observation.observed_inventory_change)
            if observation.observed_inventory_value_change is not None:
                erp["observed_inventory_value_change"] += float(observation.observed_inventory_value_change)

        def serialise(label: str | None, values: dict[str, int]) -> dict[str, Any]:
            count = values["completed_plans"]
            payload = {
                "completed_plans": count,
                "plans_with_recorded_outcome": values["plans_with_recorded_outcome"],
                "completed_without_recorded_outcome": values["completed_without_recorded_outcome"],
                "outcome_coverage_pct": round(values["plans_with_recorded_outcome"] / count * 100, 1) if count else 0.0,
                "merchant_reported_inventory_cost_rotation_outcome": values["observed_inventory_cost_rotation_outcome"],
                "missing_inventory_cost_rotation_outcome": values["missing_inventory_cost_rotation_outcome"],
                "projected_inventory_cost_rotation_total": values["observed_expected_inventory_cost_rotation_total"],
                "merchant_reported_inventory_cost_rotation_total": values["observed_actual_inventory_cost_rotation_total"],
                # Compatibility aliases. These values are merchant-reported,
                # not verified cash/capital release totals.
                "observed_recovery_outcome": values["observed_inventory_cost_rotation_outcome"],
                "missing_recovery_outcome": values["missing_inventory_cost_rotation_outcome"],
                "observed_expected_recovery_total": values["observed_expected_inventory_cost_rotation_total"],
                "observed_actual_recovery_total": values["observed_actual_inventory_cost_rotation_total"],
                "observed_sales_outcome": values["observed_sales_outcome"],
                "missing_sales_outcome": values["missing_sales_outcome"],
                "observed_expected_sales_total": values["observed_expected_sales_total"],
                "observed_actual_sales_total": values["observed_actual_sales_total"],
                "observed_units_outcome": values["observed_units_outcome"],
                "missing_units_outcome": values["missing_units_outcome"],
                "observed_expected_units_total": values["observed_expected_units_total"],
                "observed_actual_units_total": values["observed_actual_units_total"],
            }
            if label is not None:
                payload["strategy"] = label
            return payload

        portfolio_payload = serialise(None, portfolio)
        if not completed:
            report_status = "NO_COMPLETED_ACTIONS"
        elif not portfolio["plans_with_recorded_outcome"]:
            report_status = "OUTCOME_COLLECTION_PENDING"
        elif portfolio["plans_with_recorded_outcome"] < len(completed):
            report_status = "PARTIALLY_OBSERVED"
        else:
            report_status = "OBSERVED_OUTCOMES_AVAILABLE"
        return {
            "status": report_status,
            "scope": (
                "Merchant-reported results, ERP observations and scenario projections are separate sources. Merchant-entered values are not accounting reconciliation; ERP observations require continuous daily coverage and neither source proves causal impact."
            ),
            "workspace_id": int(workspace_id),
            "portfolio": portfolio_payload,
            "by_strategy": [serialise(strategy, strategies[strategy]) for strategy in sorted(strategies)],
            "erp_reconciled_observations": {
                "observed": erp["observed_observation"],
                "partial": erp["partial_observation"],
                "unavailable": erp["unavailable_observation"],
                "missing": erp["no_reconciled_observation"],
                "observed_net_units_sold": round(erp["observed_net_units_sold"], 4),
                "observed_sales_value": round(erp["observed_sales_value"], 2),
                "observed_inventory_change": round(erp["observed_inventory_change"], 4),
                "observed_inventory_value_change": round(erp["observed_inventory_value_change"], 2),
                "interpretation": (
                    "Read-only ERP observations. Receipts, returns, concurrent campaigns and other confounders mean "
                    "these measurements do not establish causal action impact or capital released."
                ),
            },
        }
