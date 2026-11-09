"""Capacity- and budget-aware portfolio queue for merchant decisions.

The individual decision engine answers *what may be appropriate for one SKU*.
This service answers *what the team can safely review this week*.  It never
turns a ranking signal into a probability/ROI and never creates an action plan
or mutates a marketplace/ERP record.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from supplyforge.models.decision import DecisionPortfolioRun, DecisionRecord
from supplyforge.services.action_plan_compatibility import ActionPlanCompatibilityService


POLICY_PATH = Path(__file__).resolve().parents[3] / 'config' / 'decision_portfolio_policy.json'


class PortfolioInputError(ValueError):
    """The queue is safe to display, but required planning inputs are invalid."""


class DecisionPortfolioService:
    """Build immutable current-decision queue snapshots."""

    MAX_WINDOW_DAYS = 31

    @staticmethod
    def _policy() -> tuple[dict[str, Any], str]:
        try:
            content = POLICY_PATH.read_bytes()
            policy = json.loads(content.decode('utf-8'))
            if not isinstance(policy, dict):
                raise ValueError('policy must be an object')
        except (OSError, ValueError, json.JSONDecodeError):
            policy = {
                'version': 'fallback-1',
                'candidate_statuses': ['GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW', 'REVIEWED'],
                'actionable_strategies': ['DISCOUNT', 'CLEARANCE', 'PROMOTION', 'BUNDLE', 'REPOSITION', 'RETURN_TO_SUPPLIER', 'STOP_REPLENISHMENT'],
                'review_strategies': ['CLEARANCE', 'STOP_REPLENISHMENT', 'RETURN_TO_SUPPLIER'],
                'campaign_cost_required_strategies': ['PROMOTION', 'BUNDLE'],
                'default_window_days': 7,
                'sort_contract': ['urgency', 'priority_tier', 'capital_exposure', 'risk_signal', 'decision_id'],
                'semantics': 'Priority score is an ordering signal only.',
            }
            content = json.dumps(policy, sort_keys=True).encode('utf-8')
        return policy, hashlib.sha256(content).hexdigest()

    @staticmethod
    def _as_non_negative_int(value: Any, field: str) -> int:
        if isinstance(value, bool):
            raise PortfolioInputError(f'{field} phải là số nguyên không âm.')
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise PortfolioInputError(f'{field} phải là số nguyên không âm.') from exc
        if parsed < 0:
            raise PortfolioInputError(f'{field} phải là số nguyên không âm.')
        return parsed

    @staticmethod
    def _as_non_negative_money(value: Any, field: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PortfolioInputError(f'{field} phải là số tiền không âm.') from exc
        if not parsed.is_finite() or parsed < 0:
            raise PortfolioInputError(f'{field} phải là số tiền không âm.')
        return parsed

    @classmethod
    def _normalise_config(cls, raw: Any, policy: dict[str, Any]) -> dict[str, Any]:
        config = raw if isinstance(raw, dict) else {}
        capacity = config.get('capacity') if isinstance(config.get('capacity'), dict) else {}
        team_value = capacity.get('max_actions', config.get('team_capacity'))
        owner_limits_raw = capacity.get('owner_limits', config.get('owner_capacities', {}))
        owner_limits_raw = owner_limits_raw if isinstance(owner_limits_raw, dict) else {}
        owner_limits = {
            str(owner).strip()[:128]: cls._as_non_negative_int(limit, f'capacity.owner_limits.{owner}')
            for owner, limit in owner_limits_raw.items()
            if str(owner).strip()
        }
        team_capacity = cls._as_non_negative_int(team_value, 'capacity.max_actions') if team_value not in (None, '') else None
        if team_capacity is None and not owner_limits:
            capacity_state = 'MISSING'
        else:
            capacity_state = 'READY'

        owners_raw = config.get('decision_owners', {})
        owners_raw = owners_raw if isinstance(owners_raw, dict) else {}
        decision_owners = {
            str(decision_id): str(owner).strip()[:128]
            for decision_id, owner in owners_raw.items()
            if str(decision_id).strip() and str(owner).strip()
        }

        costs_raw = config.get('campaign_costs', {})
        costs_raw = costs_raw if isinstance(costs_raw, dict) else {}
        campaign_costs = {
            str(decision_id): cls._as_non_negative_money(cost, f'campaign_costs.{decision_id}')
            for decision_id, cost in costs_raw.items()
        }
        budget_raw = config.get('campaign_budget')
        budget = None
        if budget_raw not in (None, ''):
            if not isinstance(budget_raw, dict):
                raise PortfolioInputError('campaign_budget phải gồm amount và currency.')
            currency = str(budget_raw.get('currency') or 'VND').upper()
            if currency != 'VND':
                raise PortfolioInputError('Portfolio hiện chỉ cộng ngân sách cùng tiền tệ VND; không tự quy đổi ngoại tệ.')
            budget = {'amount': cls._as_non_negative_money(budget_raw.get('amount'), 'campaign_budget.amount'), 'currency': currency}

        window_days = cls._as_non_negative_int(
            config.get('window_days', policy.get('default_window_days', 7)), 'window_days',
        )
        if not 1 <= window_days <= cls.MAX_WINDOW_DAYS:
            raise PortfolioInputError(f'window_days phải từ 1 đến {cls.MAX_WINDOW_DAYS}.')
        return {
            'capacity_state': capacity_state,
            'team_capacity': team_capacity,
            'owner_limits': owner_limits,
            'decision_owners': decision_owners,
            'campaign_costs': campaign_costs,
            'campaign_budget': budget,
            'window_days': window_days,
        }

    @staticmethod
    def _scope(decision: DecisionRecord) -> dict[str, str]:
        parameters = decision.action_parameters if isinstance(decision.action_parameters, dict) else {}
        explicit = parameters.get('execution_scope') if isinstance(parameters.get('execution_scope'), dict) else {}
        evidence = decision.decision_evidence_snapshot if isinstance(decision.decision_evidence_snapshot, dict) else {}
        source_scope = evidence.get('source_scope') if isinstance(evidence.get('source_scope'), dict) else {}

        def first_text(*values: Any) -> str:
            for value in values:
                if isinstance(value, (list, tuple)):
                    if len(value) == 1:
                        value = value[0]
                    else:
                        continue
                text = str(value or '').strip()
                if text:
                    return text[:128]
            return ''

        return {
            'warehouse_code': first_text(explicit.get('warehouse_code'), source_scope.get('warehouse_code'), source_scope.get('warehouse')),
            'channel': first_text(explicit.get('channel'), source_scope.get('channel')),
        }

    @staticmethod
    def _sort_key(decision: DecisionRecord) -> tuple:
        urgency_rank = {'URGENT': 0, 'HIGH': 1, 'ACT_NOW': 0, 'THIS_WEEK': 1, 'SOON': 2, 'MONITOR': 3}
        priority_rank = {'P1': 0, 'P2': 1, 'P3': 2, 'P4': 3}
        # priority_score only provides a deterministic final signal within the
        # policy queue. It is intentionally not shown or interpreted as a
        # probability, lift or financial return.
        return (
            urgency_rank.get(str(decision.urgency).upper(), 9),
            priority_rank.get(str(decision.priority_tier).upper(), 9),
            -float(decision.capital_exposure or 0),
            -float(decision.risk_score or 0),
            str(decision.decision_id),
        )

    @classmethod
    def _candidate_row(
        cls, decision: DecisionRecord, *, normalised: dict[str, Any], policy: dict[str, Any], start_date, due_date,
    ) -> dict[str, Any]:
        action = str(decision.action_type or '').upper()
        evidence = decision.decision_evidence_snapshot if isinstance(decision.decision_evidence_snapshot, dict) else {}
        parameters = decision.action_parameters if isinstance(decision.action_parameters, dict) else {}
        row = {
            'decision_id': decision.decision_id,
            'sku': decision.sku,
            'strategy': action,
            'decision_status': decision.status,
            'risk_class': decision.risk_class,
            'urgency': decision.urgency,
            'capital_exposure': float(decision.capital_exposure or 0),
            'scope': cls._scope(decision),
            'owner': normalised['decision_owners'].get(decision.decision_id),
            'requires_approval': bool(parameters.get('approval_required')) or action in set(policy.get('review_strategies') or ()),
            'queue_state': 'PENDING',
            'reasons': [],
            'campaign_cost': None,
            'conflicting_plans': [],
        }
        if not decision.assessment_run_id or not getattr(decision.assessment_run, 'is_current', False):
            row.update(queue_state='BLOCKED_STALE', reasons=['Khuyến nghị không còn thuộc lần đánh giá vận hành hiện tại.'])
            return row
        if action not in set(policy.get('actionable_strategies') or ()):
            row.update(queue_state='REVIEW_REQUIRED', reasons=['Khuyến nghị này là theo dõi/rà soát, không tiêu thụ năng lực thực thi như một chiến dịch.'])
            return row
        readiness = evidence.get('readiness') if isinstance(evidence.get('readiness'), dict) else {}
        # A stop-buy review is useful even when a selling price/cost profile
        # is absent.  It still needs observed stock and demand; price-facing
        # actions remain blocked unless the complete commercial snapshot is
        # ready.  This avoids both a harmful extra PO and an ungrounded price
        # recommendation.
        stop_buy_evidence_ready = bool(
            readiness.get('inventory_observed') and readiness.get('demand_observed')
        )
        if evidence.get('state') != 'READY' and not (action == 'STOP_REPLENISHMENT' and stop_buy_evidence_ready):
            row.update(queue_state='DATA_NEEDED', reasons=['Dữ liệu nguồn của khuyến nghị chưa đủ để đưa vào lịch thực thi.'])
            return row

        conflicts = ActionPlanCompatibilityService.find_conflicts(
            workspace_id=decision.workspace_id, sku=decision.sku, strategy=action,
            start_date=start_date, due_date=due_date, execution_scope=row['scope'],
        )
        if conflicts:
            row.update(queue_state='BLOCKED_CONFLICT', reasons=['SKU đã có kế hoạch chồng lấn, không tương thích trong cùng phạm vi.'], conflicting_plans=conflicts)
            return row

        requires_cost = action in set(policy.get('campaign_cost_required_strategies') or ())
        explicit_cost = normalised['campaign_costs'].get(decision.decision_id)
        if explicit_cost is None and parameters.get('campaign_budget_required') not in (None, ''):
            explicit_cost = cls._as_non_negative_money(parameters.get('campaign_budget_required'), 'action_parameters.campaign_budget_required')
        if requires_cost and explicit_cost is None:
            row.update(queue_state='DATA_NEEDED', reasons=['Cần nhập chi phí chiến dịch trước khi dùng ngân sách danh mục.'])
            return row
        if explicit_cost is not None:
            row['campaign_cost'] = float(explicit_cost)
            if explicit_cost > 0 and normalised['campaign_budget'] is None:
                row.update(queue_state='DATA_NEEDED', reasons=['Chi phí chiến dịch đã khai báo nhưng chưa có ngân sách VND để đối chiếu.'])
                return row
        return row

    @classmethod
    @transaction.atomic
    def build(cls, *, workspace_id: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
        policy, checksum = cls._policy()
        normalised = cls._normalise_config(config, policy)
        start_date = timezone.localdate()
        due_date = start_date + timedelta(days=normalised['window_days'] - 1)
        candidates = list(
            DecisionRecord.objects.select_related('assessment_run').filter(
                workspace_id=workspace_id,
                status__in=policy.get('candidate_statuses') or (),
                assessment_run__status='COMPLETED',
                assessment_run__is_current=True,
            ).order_by('decision_id')
        )
        candidates.sort(key=cls._sort_key)
        rows = [
            cls._candidate_row(
                decision, normalised=normalised, policy=policy, start_date=start_date, due_date=due_date,
            )
            for decision in candidates
        ]

        selected_count = 0
        selected_budget = Decimal('0')
        owner_selected: dict[str, int] = {}
        for row in rows:
            if row['queue_state'] != 'PENDING':
                continue
            if normalised['capacity_state'] != 'READY':
                row.update(queue_state='DATA_NEEDED', reasons=['Chưa khai báo năng lực xử lý của nhóm hoặc chủ sở hữu; hệ thống không tự coi năng lực bằng 0.'])
                continue
            owner = row['owner']
            owner_limit = normalised['owner_limits'].get(owner) if owner else None
            if normalised['owner_limits'] and not owner:
                row.update(queue_state='REVIEW_REQUIRED', reasons=['Cần chỉ định chủ sở hữu để áp dụng giới hạn năng lực cá nhân.'])
                continue
            if normalised['team_capacity'] is not None and selected_count >= normalised['team_capacity']:
                row.update(queue_state='DEFERRED_CAPACITY', reasons=['Đã dùng hết năng lực xử lý đã khai báo cho kỳ này.'])
                continue
            if owner_limit is not None and owner_selected.get(owner, 0) >= owner_limit:
                row.update(queue_state='DEFERRED_CAPACITY', reasons=[f'Chủ sở hữu {owner} đã dùng hết năng lực xử lý cho kỳ này.'])
                continue
            campaign_cost = Decimal(str(row['campaign_cost'] or 0))
            budget = normalised['campaign_budget']
            if campaign_cost > 0 and budget and selected_budget + campaign_cost > budget['amount']:
                row.update(queue_state='DEFERRED_BUDGET', reasons=['Ngân sách chiến dịch còn lại không đủ; cần tăng ngân sách hoặc đổi thứ tự ưu tiên.'])
                continue
            row.update(
                queue_state='SELECTED',
                reasons=['Được chọn theo mức khẩn cấp, mức ưu tiên, giá trị tồn đang chịu rủi ro và các ràng buộc đã khai báo.'],
            )
            if row['requires_approval']:
                row['reasons'].append('Cần phê duyệt trước khi tạo hoặc bắt đầu kế hoạch thực thi.')
            selected_count += 1
            selected_budget += campaign_cost
            if owner:
                owner_selected[owner] = owner_selected.get(owner, 0) + 1

        groups = {
            'selected': [row for row in rows if row['queue_state'] == 'SELECTED'],
            'deferred': [row for row in rows if row['queue_state'].startswith('DEFERRED')],
            'blocked': [row for row in rows if row['queue_state'].startswith('BLOCKED')],
            'review_or_data_needed': [row for row in rows if row['queue_state'] in {'REVIEW_REQUIRED', 'DATA_NEEDED'}],
        }
        serialised_config = {
            'capacity': {
                'state': normalised['capacity_state'], 'team_capacity': normalised['team_capacity'],
                'owner_limits': normalised['owner_limits'], 'decision_owners': normalised['decision_owners'],
            },
            'campaign_budget': (
                {'amount': float(normalised['campaign_budget']['amount']), 'currency': normalised['campaign_budget']['currency']}
                if normalised['campaign_budget'] else None
            ),
            'campaign_costs': {key: float(value) for key, value in normalised['campaign_costs'].items()},
            'window_days': normalised['window_days'],
        }
        result = {
            'version': 'DECISION_PORTFOLIO_QUEUE_V1',
            'policy_version': str(policy.get('version') or 'unknown'),
            'policy_checksum': checksum,
            'planning_window': {'start_date': start_date.isoformat(), 'end_date': due_date.isoformat(), 'days': normalised['window_days']},
            'semantics': str(policy.get('semantics') or ''),
            'constraints': serialised_config,
            'budget': {
                'currency': (normalised['campaign_budget'] or {}).get('currency', 'VND'),
                'configured_amount': float((normalised['campaign_budget'] or {}).get('amount', 0)) if normalised['campaign_budget'] else None,
                'selected_campaign_cost': float(selected_budget),
                'remaining_amount': (
                    float(normalised['campaign_budget']['amount'] - selected_budget)
                    if normalised['campaign_budget'] else None
                ),
            },
            'summary': {key: len(value) for key, value in groups.items()} | {'candidates': len(rows)},
            # Audit/replay input: the exact current decision set considered,
            # including rows deliberately deferred or blocked.
            'input_decision_ids': [row['decision_id'] for row in rows],
            'items': rows,
            'sections': groups,
            'boundary': 'Danh sách chỉ sắp xếp việc cần review/làm. Nó không tự tạo action plan, đổi giá, phát sinh chi phí hay sửa PO.',
        }
        run = DecisionPortfolioRun.objects.create(
            workspace_id=workspace_id,
            policy_version=result['policy_version'],
            policy_checksum=checksum,
            input_config_json=serialised_config,
            input_decision_ids_json=result['input_decision_ids'],
            result_snapshot_json=result,
        )
        return {'run_id': str(run.id), 'created_at': run.created_at.isoformat(), **result}

    @staticmethod
    def latest(*, workspace_id: int) -> dict[str, Any] | None:
        run = DecisionPortfolioRun.objects.filter(workspace_id=workspace_id).first()
        if not run:
            return None
        snapshot = run.result_snapshot_json if isinstance(run.result_snapshot_json, dict) else {}
        return {'run_id': str(run.id), 'created_at': run.created_at.isoformat(), **snapshot}
