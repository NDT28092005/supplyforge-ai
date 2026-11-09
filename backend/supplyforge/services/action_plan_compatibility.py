"""Prevent overlapping SKU actions from issuing incompatible instructions."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from django.db import IntegrityError

from supplyforge.models.action_plan import ActionPlanRecord, ActionPlanScopeLock


POLICY_PATH = Path(__file__).resolve().parents[3] / 'config' / 'action_compatibility_policy.json'


class ActionPlanCompatibilityService:
    """Scope-and-window gate for operational plans.

    It intentionally fails closed for an unknown warehouse.  A plan with no
    warehouse scope could otherwise race a transfer, discount or clearance at
    a particular warehouse without the merchant seeing the overlap.
    """

    @staticmethod
    def _policy() -> dict[str, Any]:
        try:
            return json.loads(POLICY_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {
                'active_statuses': ['DRAFT', 'CONFIRMED', 'IN_PROGRESS'],
                'passive_strategies': ['HOLD', 'MONITOR', 'REVIEW', 'STOP_REPLENISHMENT'],
                'conflicting_strategy_groups': [
                    ['DISCOUNT', 'CLEARANCE', 'PROMOTION', 'BUNDLE'],
                    ['REPOSITION', 'DISCOUNT', 'CLEARANCE', 'PROMOTION', 'BUNDLE'],
                ],
            }

    @staticmethod
    def normalise_scope(value: Any) -> dict[str, str]:
        raw = value if isinstance(value, dict) else {}
        def clean(key: str) -> str:
            return str(raw.get(key) or '').strip()[:128]
        return {'warehouse_code': clean('warehouse_code'), 'channel': clean('channel')}

    @classmethod
    def scope_for_plan(cls, plan: ActionPlanRecord) -> dict[str, str]:
        parameters = plan.action_parameters if isinstance(plan.action_parameters, dict) else {}
        return cls.normalise_scope(parameters.get('execution_scope'))

    @classmethod
    def _strategies_conflict(cls, left: str, right: str) -> bool:
        policy = cls._policy()
        left, right = str(left or '').upper(), str(right or '').upper()
        if left in set(policy.get('passive_strategies') or ()) or right in set(policy.get('passive_strategies') or ()):
            return False
        return any(left in group and right in group for group in policy.get('conflicting_strategy_groups') or ())

    @staticmethod
    def _windows_overlap(start: date, end: date, other: ActionPlanRecord) -> bool:
        other_start = other.start_date
        other_end = other.due_date or (other.start_date + timedelta(days=max(1, other.duration_days or 1)))
        return other_start <= end and start <= other_end

    @classmethod
    def _scopes_conflict(cls, proposed: dict[str, str], existing: dict[str, str], *, strategy: str, existing_strategy: str) -> bool:
        proposed_warehouse = proposed.get('warehouse_code', '').casefold()
        existing_warehouse = existing.get('warehouse_code', '').casefold()
        # Different explicit warehouses are physically independent. Missing
        # warehouse is intentionally not considered a wildcard match.
        if proposed_warehouse and existing_warehouse and proposed_warehouse != existing_warehouse:
            return False
        if not proposed_warehouse or not existing_warehouse:
            return True

        proposed_channel = proposed.get('channel', '').casefold()
        existing_channel = existing.get('channel', '').casefold()
        price_strategies = {'DISCOUNT', 'CLEARANCE', 'PROMOTION'}
        if (
            proposed_channel and existing_channel and proposed_channel != existing_channel
            and str(strategy).upper() in price_strategies
            and str(existing_strategy).upper() in price_strategies
        ):
            return False
        return True

    @classmethod
    def find_conflicts(
        cls,
        *, workspace_id: int, sku: str, strategy: str, start_date: date,
        due_date: date, execution_scope: dict[str, str] | None = None,
        exclude_plan_id: str | None = None,
    ) -> list[dict[str, Any]]:
        policy = cls._policy()
        proposed_scope = cls.normalise_scope(execution_scope)
        rows = ActionPlanRecord.objects.filter(
            workspace_id=workspace_id,
            sku=sku,
            status__in=policy.get('active_statuses') or ['DRAFT', 'CONFIRMED', 'IN_PROGRESS'],
            start_date__lte=due_date,
        ).select_related('assignee_user').order_by('start_date', 'plan_id')
        if exclude_plan_id:
            rows = rows.exclude(plan_id=exclude_plan_id)
        conflicts = []
        for plan in rows:
            if not cls._windows_overlap(start_date, due_date, plan):
                continue
            if not cls._strategies_conflict(strategy, plan.strategy):
                continue
            existing_scope = cls.scope_for_plan(plan)
            if not cls._scopes_conflict(proposed_scope, existing_scope, strategy=strategy, existing_strategy=plan.strategy):
                continue
            conflicts.append({
                'plan_id': str(plan.plan_id),
                'campaign_name': plan.campaign_name,
                'strategy': plan.strategy,
                'status': plan.status,
                'start_date': plan.start_date.isoformat(),
                'due_date': (plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1)))).isoformat(),
                'execution_scope': existing_scope,
            })
        return conflicts

    @staticmethod
    def acquire_scope_lock(*, workspace_id: int, sku: str) -> None:
        """Acquire the per-SKU row inside an outer transaction."""
        try:
            ActionPlanScopeLock.objects.get_or_create(workspace_id=workspace_id, sku=sku)
        except IntegrityError:
            # A concurrent creator inserted it first; the unique constraint
            # gives us a durable lock identity to wait on/read afterwards.
            pass
        ActionPlanScopeLock.objects.select_for_update().get(workspace_id=workspace_id, sku=sku)
