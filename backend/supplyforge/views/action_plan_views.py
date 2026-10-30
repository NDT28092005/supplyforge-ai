"""Tenant-scoped operational action queue for SKU recovery plans."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models.action_plan import ActionPlanEventRecord, ActionPlanRecord
from supplyforge.models.decision import DecisionRecord
from supplyforge.models.mlops import TenantFeatureSnapshot
from supplyforge.models.risk_assessment import SlowMovingRiskAssessment
from supplyforge.models.user import User, Workspace, WorkspaceMember
from supplyforge.permissions import PERM_EXECUTE_ACTION, has_permission
from supplyforge.services.decision_service import DecisionStatusService


FINAL_STATUSES = {'COMPLETED', 'CANCELLED'}
HIGH_RISK_CLASSES = {'CRITICAL', 'HIGH_RISK'}
STATUS_TRANSITIONS = {
    'DRAFT': {'CONFIRMED', 'CANCELLED'},
    'CONFIRMED': {'IN_PROGRESS', 'CANCELLED'},
    'IN_PROGRESS': {'CANCELLED'},
    'COMPLETED': set(),
    'CANCELLED': set(),
}


def _workspace_id(request) -> int:
    return int(request.workspace_id) if getattr(request, 'tenant_context_validated', False) else 1


def _actor(request) -> str:
    return str(
        request.data.get('actor')
        or request.data.get('confirmed_by')
        or getattr(request, 'user_email', None)
        or 'merchant'
    )[:128]


def _write_permission_error(request):
    if (
        getattr(request, 'tenant_context_validated', False)
        and not has_permission(getattr(request, 'user_role', None), PERM_EXECUTE_ACTION)
    ):
        return Response({
            'success': False,
            'error': {
                'code': 'PERMISSION_DENIED',
                'message': 'Tài khoản hiện tại không có quyền thực hiện kế hoạch xử lý SKU.',
            },
        }, status=status.HTTP_403_FORBIDDEN)
    return None


def _parse_date(value, field_name: str, default: date | None = None) -> date:
    if value in (None, ''):
        if default is None:
            raise ValueError(f'{field_name} là bắt buộc.')
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).split('T')[0], '%Y-%m-%d').date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} phải có định dạng YYYY-MM-DD.') from exc


def _non_negative_int(data, *keys, default=0) -> int:
    value = next((data[key] for key in keys if key in data and data[key] not in (None, '')), default)
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{keys[0]} phải là số nguyên không âm.') from exc
    if value < 0:
        raise ValueError(f'{keys[0]} không được âm.')
    return value


def _positive_int_param(value, *, default: int, maximum: int, field_name: str) -> int:
    """Bound list controls so an API caller cannot request an unbounded page."""
    if value in (None, ''):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} phải là số nguyên dương.') from exc
    if parsed < 1:
        raise ValueError(f'{field_name} phải lớn hơn 0.')
    return min(parsed, maximum)


def _assignee_for_workspace(workspace_id: int, assignee_user_id):
    """Resolve an assignee only when the user belongs to this workspace."""
    if not assignee_user_id:
        return None
    try:
        user_id = int(assignee_user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Người phụ trách không hợp lệ.') from exc
    workspace = Workspace.objects.filter(id=workspace_id).only('id', 'owner_id').first()
    is_owner = bool(workspace and workspace.owner_id == user_id)
    is_member = WorkspaceMember.objects.filter(workspace_id=workspace_id, user_id=user_id).exists()
    if not (is_owner or is_member):
        raise ValueError('Người phụ trách phải là thành viên của workspace hiện tại.')
    return User.objects.filter(id=user_id).first()


def _serialize_plan(plan: ActionPlanRecord) -> dict:
    today = timezone.localdate()
    due_date = plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1)))
    recovery_accuracy = (
        round((plan.actual_recovery_value / plan.expected_recovery_value) * 100, 1)
        if plan.actual_recovery_value is not None and plan.expected_recovery_value > 0
        else None
    )
    unit_accuracy = (
        round((plan.actual_units_sold / plan.expected_units_sold) * 100, 1)
        if plan.actual_units_sold is not None and plan.expected_units_sold > 0
        else None
    )
    return {
        'plan_id': plan.plan_id,
        'workspace_id': plan.workspace_id,
        'decision_id': plan.decision_id,
        'campaign': plan.campaign_name,
        'campaign_name': plan.campaign_name,
        'sku': plan.sku,
        'duration_days': plan.duration_days,
        'duration': f'{plan.duration_days} days',
        'strategy': plan.strategy,
        'owner': plan.owner,
        'assignee': ({
            'user_id': plan.assignee_user_id,
            'display_name': plan.assignee_user.display_name or plan.assignee_user.email,
            'email': plan.assignee_user.email,
        } if plan.assignee_user_id and plan.assignee_user else None),
        'start_date': plan.start_date.isoformat(),
        'start': plan.start_date.isoformat(),
        'due_date': due_date.isoformat(),
        'days_remaining': (due_date - today).days,
        'is_overdue': plan.status not in FINAL_STATUSES and due_date < today,
        'status': plan.status,
        'confirmed_by': plan.confirmed_by,
        'confirmed_at': plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        'completed_at': plan.completed_at.isoformat() if plan.completed_at else None,
        'expected_recovery_value': plan.expected_recovery_value,
        'actual_recovery_value': plan.actual_recovery_value,
        'expected_sales_value': plan.expected_sales_value,
        'actual_sales_value': plan.actual_sales_value,
        'expected_units_sold': plan.expected_units_sold,
        'actual_units_sold': plan.actual_units_sold,
        'recovery_accuracy_pct': recovery_accuracy,
        'units_accuracy_pct': unit_accuracy,
        'notes': plan.notes,
        'outcome_notes': plan.outcome_notes,
        'outcome_recorded_at': plan.outcome_recorded_at.isoformat() if plan.outcome_recorded_at else None,
        'created_at': plan.created_at.isoformat(),
        'updated_at': plan.updated_at.isoformat(),
    }


def _plan_or_404(request, plan_id: str):
    return ActionPlanRecord.objects.filter(
        plan_id=plan_id,
        workspace_id=_workspace_id(request),
    ).first()


def _record_event(plan, event_type, actor, old_status=None, new_status=None, notes='', metadata=None):
    ActionPlanEventRecord.objects.create(
        plan=plan,
        event_type=event_type,
        actor=actor,
        old_status=old_status,
        new_status=new_status,
        notes=notes or '',
        metadata=metadata or {},
    )


def _decision_effectiveness(workspace_id: int, requested_k: int) -> dict:
    """Evaluate ranked predictions only against frozen, observed risk labels."""
    cache_key = f'decision-effectiveness:v1:{workspace_id}:{requested_k}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    snapshots = list(
        TenantFeatureSnapshot.objects.filter(
            workspace_id=workspace_id,
            actual_risk_level__isnull=False,
            label_frozen_at__isnull=False,
        ).exclude(actual_risk_level='').only(
            'actual_risk_level', 'source_lineage_json', 'feature_vector_json',
        )
    )
    assessment_ids = [
        (snapshot.source_lineage_json or {}).get('riskAssessmentId')
        for snapshot in snapshots
        if (snapshot.source_lineage_json or {}).get('riskAssessmentId')
    ]
    assessments = SlowMovingRiskAssessment.objects.in_bulk(assessment_ids)
    assessment_by_id = {str(assessment_id): row for assessment_id, row in assessments.items()}

    observations = []
    for snapshot in snapshots:
        lineage = snapshot.source_lineage_json or {}
        feature_vector = snapshot.feature_vector_json or {}
        assessment = assessment_by_id.get(str(lineage.get('riskAssessmentId') or ''))
        predicted_class = str(
            (assessment.risk_class if assessment else feature_vector.get('predictedRiskClass')) or ''
        ).upper()
        if not predicted_class:
            continue
        score = assessment.risk_score if assessment else feature_vector.get('riskScore', 0)
        try:
            score = float(score or 0)
        except (TypeError, ValueError):
            score = 0.0
        actual_class = str(snapshot.actual_risk_level or '').upper()
        observations.append({
            'score': score,
            'predicted_high_risk': predicted_class in HIGH_RISK_CLASSES,
            'actual_high_risk': actual_class in HIGH_RISK_CLASSES,
        })

    labeled_count = len(observations)
    unmatched_count = max(0, len(snapshots) - labeled_count)
    if not observations:
        payload = {
            'status': 'PENDING_GROUND_TRUTH',
            'definition': 'Chỉ dùng nhãn rủi ro thực tế đã được đóng băng sau cửa sổ quan sát; không suy ra từ dự đoán.',
            'labeled_snapshots': 0,
            'unmatched_labeled_snapshots': unmatched_count,
            'k': requested_k,
            'evaluated_k': 0,
            'precision_at_k': None,
            'recall_high_risk_at_k': None,
            'high_risk_precision': None,
            'high_risk_recall': None,
            'actual_high_risk_count': 0,
        }
        cache.set(cache_key, payload, timeout=60)
        return payload

    ranked = sorted(observations, key=lambda item: item['score'], reverse=True)
    evaluated_k = min(requested_k, labeled_count)
    top_k = ranked[:evaluated_k]
    top_k_true_positives = sum(item['actual_high_risk'] for item in top_k)
    actual_high_count = sum(item['actual_high_risk'] for item in observations)
    predicted_high_count = sum(item['predicted_high_risk'] for item in observations)
    true_positives = sum(
        item['predicted_high_risk'] and item['actual_high_risk'] for item in observations
    )
    payload = {
        'status': 'READY',
        'definition': 'Chỉ dùng nhãn rủi ro thực tế đã được đóng băng sau cửa sổ quan sát; không suy ra từ dự đoán.',
        'labeled_snapshots': labeled_count,
        'unmatched_labeled_snapshots': unmatched_count,
        'k': requested_k,
        'evaluated_k': evaluated_k,
        'precision_at_k': round(top_k_true_positives / evaluated_k, 4) if evaluated_k else None,
        'recall_high_risk_at_k': round(top_k_true_positives / actual_high_count, 4) if actual_high_count else None,
        'high_risk_precision': round(true_positives / predicted_high_count, 4) if predicted_high_count else None,
        'high_risk_recall': round(true_positives / actual_high_count, 4) if actual_high_count else None,
        'actual_high_risk_count': actual_high_count,
    }
    cache.set(cache_key, payload, timeout=60)
    return payload


class ActionPlanListCreateView(APIView):
    """Create and list tenant-scoped operational SKU plans."""

    def post(self, request, *args, **kwargs):
        permission_error = _write_permission_error(request)
        if permission_error:
            return permission_error

        data = request.data or {}
        workspace_id = _workspace_id(request)
        decision_id = str(data.get('decision_id') or '').strip() or None
        decision = None
        if decision_id:
            decision = DecisionRecord.objects.filter(
                decision_id=decision_id,
                workspace_id=workspace_id,
            ).first()
            if not decision:
                return Response({'success': False, 'error': {'code': 'DECISION_NOT_FOUND', 'message': 'Không tìm thấy đề xuất trong workspace hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)

        sku = str(data.get('sku') or (decision.sku if decision else '')).strip()
        if not sku:
            return Response({'success': False, 'error': {'code': 'SKU_REQUIRED', 'message': 'Cần chọn mã SKU cho kế hoạch xử lý.'}}, status=status.HTTP_400_BAD_REQUEST)
        if decision and sku != decision.sku:
            return Response({'success': False, 'error': {'code': 'SKU_DECISION_MISMATCH', 'message': 'SKU phải khớp với đề xuất đã chọn.'}}, status=status.HTTP_400_BAD_REQUEST)

        try:
            duration_days = int(data.get('duration_days') or data.get('duration') or 14)
            if not 1 <= duration_days <= 365:
                raise ValueError('Thời gian thực hiện phải từ 1 đến 365 ngày.')
            start_date = _parse_date(data.get('start_date') or data.get('start'), 'Ngày bắt đầu', date.today())
            due_date = _parse_date(data.get('due_date'), 'Hạn xử lý', start_date + timedelta(days=duration_days))
            if due_date < start_date:
                raise ValueError('Hạn xử lý không thể sớm hơn ngày bắt đầu.')
            expected_recovery = _non_negative_int(data, 'expected_recovery_value', 'expected_recovery', default=round(decision.expected_recovery_value) if decision else 0)
            expected_sales = _non_negative_int(data, 'expected_sales_value', 'expected_sales', default=0)
            expected_units = _non_negative_int(data, 'expected_units_sold', 'expected_units', default=0)
            assignee = _assignee_for_workspace(workspace_id, data.get('assignee_user_id'))
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_ACTION_PLAN', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)

        if str(data.get('status') or 'DRAFT').upper() != 'DRAFT':
            return Response({'success': False, 'error': {'code': 'INVALID_INITIAL_STATUS', 'message': 'Kế hoạch mới luôn bắt đầu ở trạng thái Bản nháp để chờ phê duyệt.'}}, status=status.HTTP_400_BAD_REQUEST)

        strategy = str(data.get('strategy') or (decision.action_type if decision else '')).strip()
        owner = str(data.get('owner') or (assignee.display_name if assignee else '') or '').strip()
        if not strategy:
            return Response({'success': False, 'error': {'code': 'STRATEGY_REQUIRED', 'message': 'Cần xác định phương án xử lý.'}}, status=status.HTTP_400_BAD_REQUEST)
        if not owner:
            return Response({'success': False, 'error': {'code': 'OWNER_REQUIRED', 'message': 'Cần chỉ định người phụ trách.'}}, status=status.HTTP_400_BAD_REQUEST)

        campaign_name = str(data.get('campaign_name') or data.get('campaign') or f'Xử lý SKU {sku}').strip()
        plan = ActionPlanRecord.objects.create(
            workspace_id=workspace_id,
            campaign_name=campaign_name[:255], sku=sku[:64], duration_days=duration_days,
            strategy=strategy[:128], owner=owner[:128], assignee_user=assignee, start_date=start_date,
            due_date=due_date, status='DRAFT', decision_id=decision_id,
            notes=str(data.get('notes') or ''), expected_recovery_value=expected_recovery,
            expected_sales_value=expected_sales, expected_units_sold=expected_units,
        )
        _record_event(plan, 'PLAN_CREATED', _actor(request), new_status='DRAFT', notes=plan.notes, metadata={'decision_id': decision_id, 'due_date': due_date.isoformat()})
        return Response({'success': True, **_serialize_plan(plan)}, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        qs = ActionPlanRecord.objects.filter(
            workspace_id=_workspace_id(request)
        ).select_related('assignee_user')
        sku = request.query_params.get('sku')
        status_param = request.query_params.get('status')
        owner = request.query_params.get('owner')
        search = str(request.query_params.get('q') or '').strip()
        if sku:
            qs = qs.filter(sku__icontains=sku.strip())
        if status_param and status_param.upper() != 'ALL':
            qs = qs.filter(status=status_param.upper())
        if owner:
            qs = qs.filter(owner__icontains=owner.strip())
        if search:
            qs = qs.filter(
                Q(plan_id__icontains=search)
                | Q(sku__icontains=search)
                | Q(campaign_name__icontains=search)
                | Q(owner__icontains=search)
                | Q(strategy__icontains=search)
            )
        if str(request.query_params.get('overdue')).lower() in {'1', 'true', 'yes'}:
            qs = qs.filter(due_date__lt=timezone.localdate()).exclude(status__in=FINAL_STATUSES)
        ordered_qs = qs.order_by('due_date', '-created_at')

        # Preserve the prior array contract for integrations not asking for a
        # page. The dashboard always requests server-side pagination.
        if 'page' not in request.query_params and 'page_size' not in request.query_params:
            return Response([_serialize_plan(plan) for plan in ordered_qs], status=status.HTTP_200_OK)
        try:
            page = _positive_int_param(request.query_params.get('page'), default=1, maximum=1_000_000, field_name='page')
            page_size = _positive_int_param(request.query_params.get('page_size'), default=10, maximum=100, field_name='page_size')
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_PAGINATION', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        total = ordered_qs.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        plans = list(ordered_qs[start:start + page_size])
        return Response({
            'items': [_serialize_plan(plan) for plan in plans],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_items': total,
                'total_pages': total_pages,
                'has_previous': page > 1,
                'has_next': page < total_pages,
            },
        }, status=status.HTTP_200_OK)


class ActionPlanSummaryView(APIView):
    """Portfolio workload and observed-outcome indicators for the action queue."""

    def get(self, request, *args, **kwargs):
        qs = ActionPlanRecord.objects.filter(workspace_id=_workspace_id(request))
        open_qs = qs.exclude(status__in=FINAL_STATUSES)
        completed = qs.filter(status='COMPLETED')
        observed = completed.filter(outcome_recorded_at__isnull=False)
        totals = observed.aggregate(
            expected=Sum('expected_recovery_value'),
            actual=Sum('actual_recovery_value'),
            expected_sales=Sum('expected_sales_value'),
            actual_sales=Sum('actual_sales_value'),
        )
        return Response({
            'total_plans': qs.count(), 'open_plans': open_qs.count(),
            'overdue_plans': open_qs.filter(due_date__lt=timezone.localdate()).count(),
            'in_progress_plans': qs.filter(status='IN_PROGRESS').count(),
            'completed_plans': completed.count(),
            'completed_sku_count': completed.values('sku').distinct().count(),
            'outcome_coverage_pct': round((observed.count() / completed.count()) * 100, 1) if completed.exists() else 0.0,
            'expected_recovery_value': int(totals['expected'] or 0),
            'actual_recovery_value': int(totals['actual'] or 0),
            'expected_sales_value': int(totals['expected_sales'] or 0),
            'actual_sales_value': int(totals['actual_sales'] or 0),
        }, status=status.HTTP_200_OK)


class DecisionEffectivenessView(APIView):
    """Expose model-quality measures separately from operational outcomes."""

    def get(self, request, *args, **kwargs):
        try:
            requested_k = _positive_int_param(
                request.query_params.get('k'), default=100, maximum=10_000, field_name='k'
            )
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_K', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            _decision_effectiveness(_workspace_id(request), requested_k),
            status=status.HTTP_200_OK,
        )


class ActionPlanAssigneeListView(APIView):
    """Return the bounded directory that may receive SKU assignments."""

    def get(self, request, *args, **kwargs):
        workspace_id = _workspace_id(request)
        member_ids = set(
            WorkspaceMember.objects.filter(workspace_id=workspace_id).values_list('user_id', flat=True)
        )
        owner_id = Workspace.objects.filter(id=workspace_id).values_list('owner_id', flat=True).first()
        if owner_id:
            member_ids.add(owner_id)
        users = User.objects.filter(id__in=member_ids).order_by('display_name', 'email')
        return Response({'assignees': [{
            'user_id': user.id,
            'display_name': user.display_name or user.email,
            'email': user.email,
            'role': user.role,
        } for user in users]}, status=status.HTTP_200_OK)


class ActionPlanStatusUpdateView(APIView):
    """Advance a plan only through explicit approval and execution states."""

    def patch(self, request, plan_id, *args, **kwargs):
        permission_error = _write_permission_error(request)
        if permission_error:
            return permission_error
        plan = _plan_or_404(request, plan_id)
        if not plan:
            return Response({'success': False, 'error': {'code': 'PLAN_NOT_FOUND', 'message': 'Không tìm thấy kế hoạch trong workspace hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)

        new_status = str(request.data.get('status') or '').upper()
        if new_status == 'COMPLETED':
            return Response({'success': False, 'error': {'code': 'OUTCOME_REQUIRED', 'message': 'Chỉ có thể hoàn tất sau khi ghi nhận kết quả thực tế.'}}, status=status.HTTP_400_BAD_REQUEST)
        valid_statuses = {choice[0] for choice in ActionPlanRecord.STATUS_CHOICES}
        if new_status not in valid_statuses:
            return Response({'success': False, 'error': {'code': 'INVALID_STATUS', 'message': 'Trạng thái kế hoạch không hợp lệ.'}}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == plan.status:
            return Response({'success': True, **_serialize_plan(plan)}, status=status.HTTP_200_OK)
        if new_status not in STATUS_TRANSITIONS.get(plan.status, set()):
            return Response({'success': False, 'error': {'code': 'INVALID_STATUS_TRANSITION', 'message': f'Không thể chuyển từ {plan.status} sang {new_status}.'}}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == 'CONFIRMED' and plan.decision_id:
            decision = DecisionRecord.objects.filter(decision_id=plan.decision_id, workspace_id=plan.workspace_id).first()
            if not decision or decision.status not in {'ACCEPTED', 'EXECUTED', 'COMPLETED'}:
                return Response({'success': False, 'error': {'code': 'DECISION_APPROVAL_REQUIRED', 'message': 'Cần phê duyệt đề xuất trước khi xác nhận kế hoạch xử lý.'}}, status=status.HTTP_409_CONFLICT)

        old_status, actor = plan.status, _actor(request)
        plan.status = new_status
        if 'notes' in request.data:
            plan.notes = str(request.data['notes'])
        if new_status == 'CONFIRMED':
            plan.confirmed_by, plan.confirmed_at = actor, timezone.now()
        plan.save()
        if new_status == 'IN_PROGRESS' and plan.decision_id:
            decision = DecisionRecord.objects.filter(decision_id=plan.decision_id, workspace_id=plan.workspace_id).first()
            if decision and decision.status == 'ACCEPTED':
                DecisionStatusService.update_status(decision.decision_id, 'EXECUTED', actor=actor, notes='Action plan started.')
        _record_event(plan, f'PLAN_{new_status}', actor, old_status, new_status, plan.notes)
        return Response({'success': True, **_serialize_plan(plan)}, status=status.HTTP_200_OK)


class ActionPlanOutcomeView(APIView):
    """Record observed results, complete the plan, and preserve evaluation evidence."""

    def patch(self, request, plan_id, *args, **kwargs):
        permission_error = _write_permission_error(request)
        if permission_error:
            return permission_error
        plan = _plan_or_404(request, plan_id)
        if not plan:
            return Response({'success': False, 'error': {'code': 'PLAN_NOT_FOUND', 'message': 'Không tìm thấy kế hoạch trong workspace hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)
        if plan.status not in {'IN_PROGRESS', 'COMPLETED'}:
            return Response({'success': False, 'error': {'code': 'PLAN_NOT_EXECUTED', 'message': 'Chỉ có thể ghi nhận kết quả cho kế hoạch đang triển khai hoặc đã hoàn tất.'}}, status=status.HTTP_409_CONFLICT)

        data = request.data or {}
        if not any(key in data for key in (
            'actual_recovery_value', 'actual_recovery', 'actual_sales_value',
            'actual_sales', 'actual_units_sold', 'actual_units',
        )):
            return Response({'success': False, 'error': {'code': 'OUTCOME_REQUIRED', 'message': 'Cần nhập ít nhất một kết quả thực tế.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            actual_recovery = _non_negative_int(data, 'actual_recovery_value', 'actual_recovery', default=plan.actual_recovery_value or 0)
            actual_sales = _non_negative_int(data, 'actual_sales_value', 'actual_sales', default=plan.actual_sales_value or 0)
            actual_units = _non_negative_int(data, 'actual_units_sold', 'actual_units', default=plan.actual_units_sold or 0)
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_OUTCOME', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)

        actor, old_status = _actor(request), plan.status
        plan.actual_recovery_value = actual_recovery
        plan.actual_sales_value = actual_sales
        plan.actual_units_sold = actual_units
        plan.outcome_notes = str(data.get('outcome_notes') or data.get('notes') or plan.outcome_notes)
        plan.outcome_recorded_at = timezone.now()
        plan.status = 'COMPLETED'
        plan.completed_at = plan.completed_at or timezone.now()
        plan.save()
        if plan.decision_id:
            decision = DecisionRecord.objects.filter(decision_id=plan.decision_id, workspace_id=plan.workspace_id).first()
            if decision and decision.status == 'EXECUTED':
                DecisionStatusService.update_status(decision.decision_id, 'COMPLETED', actor=actor, notes='Action plan outcome recorded.')
        _record_event(plan, 'OUTCOME_RECORDED', actor, old_status, 'COMPLETED', plan.outcome_notes, {
            'actual_recovery_value': actual_recovery,
            'actual_sales_value': actual_sales,
            'actual_units_sold': actual_units,
        })
        payload = _serialize_plan(plan)
        recovery_accuracy = payload['recovery_accuracy_pct'] or 0.0
        unit_accuracy = payload['units_accuracy_pct'] or 0.0
        payload['outcome'] = {
            'expected_recovery_value': plan.expected_recovery_value,
            'actual_recovery_value': plan.actual_recovery_value,
            'recovery_accuracy_pct': recovery_accuracy,
            'expected_units_sold': plan.expected_units_sold,
            'actual_units_sold': plan.actual_units_sold,
            'units_accuracy_pct': unit_accuracy,
            'expected_sales_value': plan.expected_sales_value,
            'actual_sales_value': plan.actual_sales_value,
            'decision_usefulness': 'HIGH' if recovery_accuracy >= 75 and unit_accuracy >= 75 else ('MEDIUM' if recovery_accuracy >= 50 else 'LOW'),
        }
        return Response({'success': True, **payload}, status=status.HTTP_200_OK)


class ActionPlanHistoryView(APIView):
    """Return immutable lifecycle events for an operational plan."""

    def get(self, request, plan_id, *args, **kwargs):
        plan = _plan_or_404(request, plan_id)
        if not plan:
            return Response({'success': False, 'error': {'code': 'PLAN_NOT_FOUND', 'message': 'Không tìm thấy kế hoạch trong workspace hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)
        return Response({'plan_id': plan.plan_id, 'history': [{
            'event_type': event.event_type, 'old_status': event.old_status,
            'new_status': event.new_status, 'actor': event.actor,
            'notes': event.notes, 'metadata': event.metadata,
            'timestamp': event.timestamp.isoformat(),
        } for event in plan.events.all()]}, status=status.HTTP_200_OK)
