"""Turn an audited portfolio into a read-only, owner-aware operating week."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.db import transaction

from supplyforge.models.decision import DecisionPortfolioRun, DecisionRecord, WeeklyActionItem, WeeklyActionRun
from supplyforge.models.user import User, Workspace, WorkspaceMember


class WeeklyActionInputError(ValueError):
    pass


class WeeklyActionPlanningService:
    """Persist a week without automatically creating action plans or changes."""

    MAX_WINDOW_DAYS = 31

    @staticmethod
    def _date(value: Any, field: str, default: date) -> date:
        if value in (None, ''):
            return default
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError) as exc:
            raise WeeklyActionInputError(f'{field} phải theo định dạng YYYY-MM-DD.') from exc

    @staticmethod
    def _member(workspace_id: int, raw_user_id: Any) -> User | None:
        if raw_user_id in (None, ''):
            return None
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError) as exc:
            raise WeeklyActionInputError('Người phụ trách không hợp lệ.') from exc
        workspace = Workspace.objects.filter(id=workspace_id).only('owner_id').first()
        permitted = bool(workspace and workspace.owner_id == user_id) or WorkspaceMember.objects.filter(
            workspace_id=workspace_id, user_id=user_id,
        ).exists()
        user = User.objects.filter(id=user_id).first()
        if not permitted or not user:
            raise WeeklyActionInputError('Người phụ trách phải thuộc workspace hiện tại.')
        return user

    @staticmethod
    def _state(source_state: str, has_owner: bool) -> str:
        if source_state == 'SELECTED':
            return WeeklyActionItem.STATE_READY if has_owner else WeeklyActionItem.STATE_NEEDS_OWNER
        if source_state.startswith('DEFERRED'):
            return WeeklyActionItem.STATE_DEFERRED
        return WeeklyActionItem.STATE_BLOCKED

    @staticmethod
    def _next_step(state: str, source: dict[str, Any]) -> str:
        if state == WeeklyActionItem.STATE_NEEDS_OWNER:
            return 'Chỉ định người phụ trách trước khi lập kế hoạch thực thi.'
        if state == WeeklyActionItem.STATE_DEFERRED:
            return 'Xem lại ở kỳ tiếp theo hoặc điều chỉnh năng lực/ngân sách đã khai báo.'
        if state == WeeklyActionItem.STATE_BLOCKED:
            reasons = source.get('reasons') if isinstance(source.get('reasons'), list) else []
            return str(reasons[0]) if reasons else 'Rà soát điều kiện đang chặn trước khi thực hiện.'
        if bool(source.get('requires_approval')):
            return 'Mở hồ sơ quyết định, kiểm tra dữ liệu hiện tại và phê duyệt trước khi lập kế hoạch.'
        return 'Mở hồ sơ quyết định, kiểm tra điều kiện hiện tại rồi lập kế hoạch thực thi khi đã sẵn sàng.'

    @classmethod
    def _serialise(cls, run: WeeklyActionRun) -> dict[str, Any]:
        rows = list(run.items.select_related('owner').all())
        sections = {
            'today': [], 'needs_owner': [], 'blocked': [], 'deferred': [],
        }
        for item in rows:
            payload = {
                'decision_id': item.decision_id_snapshot,
                'sku': item.sku,
                'strategy': item.strategy,
                'state': item.state,
                'owner': ({
                    'user_id': item.owner_id,
                    'display_name': item.owner.display_name or item.owner.email,
                } if item.owner_id and item.owner else None),
                'owner_label': item.owner_label or None,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'reasons': item.reasons_json if isinstance(item.reasons_json, list) else [],
                'next_step': item.next_step,
            }
            if item.state == WeeklyActionItem.STATE_READY:
                sections['today'].append(payload)
            elif item.state == WeeklyActionItem.STATE_NEEDS_OWNER:
                sections['needs_owner'].append(payload)
            elif item.state == WeeklyActionItem.STATE_DEFERRED:
                sections['deferred'].append(payload)
            else:
                sections['blocked'].append(payload)
        return {
            'version': 'WEEKLY_ACTION_PLAN_V1',
            'run_id': str(run.id),
            'portfolio_run_id': str(run.portfolio_run_id) if run.portfolio_run_id else None,
            'week': {'start_date': run.week_start.isoformat(), 'end_date': run.week_end.isoformat()},
            'created_at': run.created_at.isoformat(),
            'sections': sections,
            'summary': {key: len(value) for key, value in sections.items()} | {'total': len(rows)},
            'boundary': 'Kế hoạch tuần chỉ giao việc để rà soát và thực thi có kiểm soát. Nó không tự tạo kế hoạch SKU, thay đổi giá, PO hoặc dữ liệu Odoo.',
        }

    @classmethod
    @transaction.atomic
    def create(cls, *, workspace_id: int, actor: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config if isinstance(config, dict) else {}
        requested_run_id = str(config.get('portfolio_run_id') or '').strip()
        portfolio = (
            DecisionPortfolioRun.objects.filter(id=requested_run_id, workspace_id=workspace_id).first()
            if requested_run_id else DecisionPortfolioRun.objects.filter(workspace_id=workspace_id).first()
        )
        if not portfolio:
            raise WeeklyActionInputError('Cần lập danh mục hành động trước khi tạo kế hoạch tuần này.')
        snapshot = portfolio.result_snapshot_json if isinstance(portfolio.result_snapshot_json, dict) else {}
        source_items = snapshot.get('items') if isinstance(snapshot.get('items'), list) else []
        if not source_items:
            raise WeeklyActionInputError('Danh mục hiện tại chưa có SKU để lập kế hoạch tuần.')
        planned_window = snapshot.get('planning_window') if isinstance(snapshot.get('planning_window'), dict) else {}
        default_start = cls._date(planned_window.get('start_date'), 'Ngày bắt đầu', date.today())
        week_start = cls._date(config.get('week_start'), 'Ngày bắt đầu tuần', default_start)
        week_end = cls._date(config.get('week_end'), 'Ngày kết thúc tuần', week_start + timedelta(days=6))
        if week_end < week_start or (week_end - week_start).days + 1 > cls.MAX_WINDOW_DAYS:
            raise WeeklyActionInputError('Kế hoạch tuần phải kéo dài từ 1 đến 31 ngày.')

        assignments = config.get('assignments') if isinstance(config.get('assignments'), dict) else {}
        due_dates = config.get('due_dates') if isinstance(config.get('due_dates'), dict) else {}
        member_cache: dict[str, User | None] = {}
        decisions = DecisionRecord.objects.filter(workspace_id=workspace_id).in_bulk(
            [str(item.get('decision_id') or '') for item in source_items], field_name='decision_id'
        )
        run = WeeklyActionRun.objects.create(
            workspace_id=workspace_id,
            portfolio_run=portfolio,
            week_start=week_start,
            week_end=week_end,
            source_snapshot_json={
                'portfolio_run_id': str(portfolio.id),
                'policy_version': snapshot.get('policy_version'),
                'policy_checksum': snapshot.get('policy_checksum'),
                'input_decision_ids': snapshot.get('input_decision_ids', []),
                'constraints': snapshot.get('constraints', {}),
            },
            created_by=(actor or 'merchant')[:128],
        )
        for index, source in enumerate(source_items, start=1):
            if not isinstance(source, dict):
                continue
            decision_id = str(source.get('decision_id') or '').strip()
            if not decision_id:
                continue
            raw_owner = assignments.get(decision_id)
            if decision_id not in member_cache:
                member_cache[decision_id] = cls._member(workspace_id, raw_owner)
            owner = member_cache[decision_id]
            source_state = str(source.get('queue_state') or '')
            state = cls._state(source_state, bool(owner))
            raw_due = due_dates.get(decision_id)
            due_date = cls._date(raw_due, f'Hạn xử lý của {decision_id}', week_end) if state in {
                WeeklyActionItem.STATE_READY, WeeklyActionItem.STATE_NEEDS_OWNER,
            } else None
            if due_date and not week_start <= due_date <= week_end:
                raise WeeklyActionInputError('Hạn xử lý phải nằm trong kỳ của kế hoạch tuần.')
            owner_label = (owner.display_name or owner.email) if owner else str(source.get('owner') or '')[:128]
            WeeklyActionItem.objects.create(
                run=run,
                decision=decisions.get(decision_id),
                decision_id_snapshot=decision_id,
                sku=str(source.get('sku') or '')[:128],
                strategy=str(source.get('strategy') or '')[:64],
                state=state,
                owner=owner,
                owner_label=owner_label,
                due_date=due_date,
                sort_order=index,
                reasons_json=list(source.get('reasons') or []),
                next_step=cls._next_step(state, source),
                source_item_json=source,
            )
        return cls._serialise(run)

    @classmethod
    def latest(cls, *, workspace_id: int) -> dict[str, Any] | None:
        run = WeeklyActionRun.objects.filter(workspace_id=workspace_id).first()
        return cls._serialise(run) if run else None
