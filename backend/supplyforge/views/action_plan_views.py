"""Tenant-scoped operational action queue for SKU recovery plans."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models.action_plan import ActionPlanEventRecord, ActionPlanRecord, ActionPlanTask
from supplyforge.models.decision import DecisionRecord
from supplyforge.models.mlops import TenantFeatureSnapshot
from supplyforge.models.risk_assessment import SlowMovingRiskAssessment
from supplyforge.models.user import User, Workspace, WorkspaceMember
from supplyforge.permissions import PERM_EXECUTE_ACTION, ROLE_ADMIN, ROLE_OWNER, has_permission
from supplyforge.services.decision_service import DecisionStatusService
from supplyforge.services.decision_evidence_freshness import DecisionEvidenceFreshnessService
from supplyforge.services.decision_revalidation import DecisionRevalidationService
from supplyforge.services.action_outcome_reporting import ActionOutcomeEvidenceService
from supplyforge.services.model_runtime_guard import execution_runtime_status
from supplyforge.services.action_execution import ActionExecutionService
from supplyforge.services.action_plan_compatibility import ActionPlanCompatibilityService


FINAL_STATUSES = {'COMPLETED', 'CANCELLED'}
HIGH_RISK_CLASSES = {'CRITICAL', 'HIGH_RISK'}
PLAN_STRATEGY_ALIASES = {
    'DISCOUNT_CLEARANCE': 'CLEARANCE',
    'BUNDLE_PROMOTION': 'BUNDLE',
    'FLASH_SALE': 'PROMOTION',
    'MONITOR_INVENTORY': 'MONITOR',
    'SUPPLIER_RETURN': 'RETURN_TO_SUPPLIER',
}
PLAN_STRATEGIES = {
    'HOLD', 'MONITOR', 'PROMOTION', 'BUNDLE', 'DISCOUNT', 'CLEARANCE',
    'REPOSITION', 'RETURN_TO_SUPPLIER', 'STOP_REPLENISHMENT', 'REVIEW',
}
PRICE_STRATEGIES = {'DISCOUNT', 'CLEARANCE', 'PROMOTION'}
EVIDENCE_OVERRIDE_MIN_LENGTH = 16
PLAN_STRATEGY_LABELS = {
    'HOLD': 'Giữ nguyên và theo dõi định kỳ',
    'MONITOR': 'Theo dõi tín hiệu bán hàng',
    'PROMOTION': 'Khuyến mại có kiểm soát',
    'BUNDLE': 'Bán theo gói',
    'DISCOUNT': 'Điều chỉnh giá có kiểm soát',
    'CLEARANCE': 'Giải phóng tồn kho có phê duyệt',
    'REPOSITION': 'Điều chuyển hoặc tái định vị',
    'RETURN_TO_SUPPLIER': 'Hoàn trả nhà cung cấp',
    'STOP_REPLENISHMENT': 'Tạm dừng tái nhập',
    'REVIEW': 'Rà soát nghiệp vụ',
}
PLAN_OVERRIDE_REASON_LABELS = {
    'OWN_PLAN': 'Đã có kế hoạch xử lý phù hợp hơn',
    'STOCK_OR_PRICE_CHANGED': 'Tồn kho hoặc mức giá thực tế đã thay đổi',
    'SUPPLIER_CONSTRAINT': 'Điều kiện nhà cung cấp hoặc PO không cho phép',
    'SEASONAL_OR_STRATEGIC': 'Cần giữ hàng hoặc giữ giá theo kế hoạch kinh doanh',
    'OTHER': 'Lý do khác',
}
OUTCOME_NEXT_STEP_LABELS = {
    'MONITOR': 'Tiếp tục theo dõi',
    'NEW_DECISION': 'Lập quyết định mới',
    'CLOSE': 'Đóng kế hoạch',
}
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


def _override_reason_code(value) -> str:
    code = str(value or '').strip().upper()
    if not code:
        return ''
    if code not in PLAN_OVERRIDE_REASON_LABELS:
        raise ValueError('Lý do điều chỉnh phương án không hợp lệ.')
    return code


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


def _normalise_plan_strategy(value) -> str:
    """Accept persisted legacy values but never store a free-text action."""
    strategy = str(value or '').strip().upper().replace(' ', '_')
    strategy = PLAN_STRATEGY_ALIASES.get(strategy, strategy)
    if strategy not in PLAN_STRATEGIES:
        raise ValueError('Phương án xử lý không thuộc danh mục được kiểm soát.')
    return strategy


def _execution_parameters(data, decision, strategy: str, duration_days: int, override_reason: str) -> dict:
    """Validate the small, auditable execution contract for a plan.

    We intentionally do not accept arbitrary JSON.  The recommendation stays
    immutable; a plan can only record a discount rate and deployment duration,
    with an explicit rationale when a recommendation is changed.
    """
    raw = data.get('execution_parameters') or {}
    if not isinstance(raw, dict):
        raise ValueError('Thông số triển khai phải là một đối tượng hợp lệ.')
    unsupported = set(raw) - {'discount_rate'}
    if unsupported:
        raise ValueError('Thông số triển khai không được hỗ trợ: ' + ', '.join(sorted(unsupported)))

    decision_parameters = decision.action_parameters if decision and isinstance(decision.action_parameters, dict) else {}
    recommended_rate = decision.discount_rate if decision else None
    supplied_rate = raw.get('discount_rate')
    if supplied_rate in ('', None):
        supplied_rate = recommended_rate

    execution = {
        'source': 'DECISION_RECOMMENDATION' if decision else 'MANUAL_PLAN',
        'duration_days': duration_days,
        'recommended_strategy': decision.action_type if decision else None,
        'recommended_discount_rate': recommended_rate,
        'policy_version': decision.policy_version if decision else None,
    }
    if strategy in PRICE_STRATEGIES:
        if supplied_rate is not None:
            try:
                rate = float(supplied_rate)
            except (TypeError, ValueError) as exc:
                raise ValueError('Mức điều chỉnh giá phải là số hợp lệ.') from exc
            if not 0 <= rate <= 0.50:
                raise ValueError('Mức điều chỉnh giá phải nằm trong khoảng 0% đến 50%.')
            if recommended_rate is not None and abs(rate - float(recommended_rate)) > 0.000001 and len(override_reason) < 8:
                raise ValueError('Khi thay đổi mức điều chỉnh giá được đề xuất, cần nêu lý do tối thiểu 8 ký tự.')
            execution['discount_rate'] = rate
    elif supplied_rate not in ('', None):
        raise ValueError('Chỉ phương án liên quan đến giá mới có mức điều chỉnh giá.')

    # Snapshot enough decision context to make later plan review explainable
    # without copying large feature vectors into the action queue.
    if decision:
        execution['recommendation_parameters'] = {
            'strategy_id': decision_parameters.get('strategy_id', decision.action_type),
            'approval_required': bool(decision_parameters.get('approval_required', False)),
            'projection_status': (decision_parameters.get('projection') or {}).get('status'),
        }
    return execution


def _execution_scope(data) -> dict:
    """Keep channel/kho scope explicit and small enough for an audit record."""
    raw_scope = data.get('execution_scope')
    if raw_scope in (None, ''):
        raw_scope = {
            'warehouse_code': data.get('warehouse_code') or '',
            'channel': data.get('channel') or '',
        }
    if not isinstance(raw_scope, dict):
        raise ValueError('Phạm vi thực thi phải là một đối tượng hợp lệ.')
    unsupported = set(raw_scope) - {'warehouse_code', 'channel'}
    if unsupported:
        raise ValueError('Phạm vi thực thi không được hỗ trợ: ' + ', '.join(sorted(unsupported)))
    return ActionPlanCompatibilityService.normalise_scope(raw_scope)


def _decision_evidence_check(*, workspace_id: int, sku: str, strategy: str, decision=None) -> dict:
    """Return the current Odoo evidence check without mutating the decision."""
    if decision is None:
        return {
            'state': 'NOT_REQUIRED',
            'code': 'MANUAL_PLAN',
            'message': 'Kế hoạch thủ công không dùng ảnh chụp của một đề xuất để tái xác nhận.',
            'current': None,
            'expected': None,
            'changed_fields': [],
        }
    return DecisionEvidenceFreshnessService.evaluate_for_strategy(
        workspace_id=workspace_id,
        sku=sku,
        strategy=strategy,
        # An explicit re-approval is a new immutable record.  Prefer it over
        # the recommendation-time snapshot without changing that original
        # recommendation, so plan creation uses what the merchant last checked.
        expected_snapshot=DecisionRevalidationService.expected_snapshot(decision),
    )


def _evidence_override(request, evaluation: dict, *, field_name: str = 'data_evidence_override_reason') -> tuple[str | None, str | None]:
    """Only an accountable administrator can override changed, still-readable facts."""
    if evaluation.get('state') in {'READY', 'NOT_REQUIRED'}:
        return None, None
    if not DecisionEvidenceFreshnessService.controlled_override_allowed(evaluation):
        return None, evaluation.get('message') or 'Không thể tái xác nhận dữ liệu Odoo cho kế hoạch này.'
    role = str(getattr(request, 'user_role', '') or '').upper()
    if role not in {ROLE_OWNER, ROLE_ADMIN}:
        return None, 'Chỉ Owner hoặc Admin có thể phê duyệt ngoại lệ khi dữ liệu Odoo đã thay đổi.'
    reason = str((request.data or {}).get(field_name) or '').strip()
    if len(reason) < EVIDENCE_OVERRIDE_MIN_LENGTH:
        return None, (
            'Dữ liệu Odoo đã thay đổi. Hãy làm mới đề xuất hoặc nêu lý do ngoại lệ tối thiểu '
            f'{EVIDENCE_OVERRIDE_MIN_LENGTH} ký tự.'
        )
    return reason, None


def _evidence_error_payload(evaluation: dict, message: str) -> dict:
    return {
        'success': False,
        'error': {
            'code': 'DECISION_REVALIDATION_REQUIRED',
            'message': message,
        },
        'data_evidence': {
            'state': evaluation.get('state'),
            'code': evaluation.get('code'),
            'changed_fields': evaluation.get('changed_fields', []),
            'current': evaluation.get('current'),
            'override_allowed': DecisionEvidenceFreshnessService.controlled_override_allowed(evaluation),
        },
    }


def _record_execution_evidence(parameters: dict, evaluation: dict, *, stage: str, override_reason: str | None = None, actor: str = '') -> None:
    """Persist only the approved execution baseline, never mutate the recommendation."""
    current = evaluation.get('current') if isinstance(evaluation.get('current'), dict) else None
    if current and current.get('state') == 'READY':
        parameters['execution_evidence_snapshot'] = current
    parameters['data_evidence'] = {
        'state': 'OVERRIDDEN' if override_reason else evaluation.get('state'),
        'code': evaluation.get('code'),
        'checked_at': timezone.now().isoformat(),
        'stage': stage,
        'changed_fields': evaluation.get('changed_fields', []),
        'override_reason': override_reason or '',
        'override_actor': actor if override_reason else '',
    }


def _outcome_review(plan: ActionPlanRecord, data: dict) -> dict:
    """Create a close-out statement without turning observations into causality."""
    requested_next = str(data.get('outcome_next_step') or '').strip().upper()
    existing = plan.outcome_review_json if isinstance(plan.outcome_review_json, dict) else {}
    next_step = requested_next or str(existing.get('next_step') or 'MONITOR').upper()
    if next_step not in OUTCOME_NEXT_STEP_LABELS:
        raise ValueError('Bước tiếp theo sau khi rà soát kết quả không hợp lệ.')
    observed = getattr(plan, 'observed_outcome', None)
    if observed and observed.status == 'OBSERVED':
        observation_state = 'OBSERVED'
        observation_label = 'Odoo đã quan sát đủ dữ liệu trong kỳ đối soát'
    elif observed and observed.status == 'PARTIAL':
        observation_state = 'PARTIAL'
        observation_label = 'Odoo chỉ quan sát được một phần dữ liệu'
    else:
        observation_state = 'UNAVAILABLE'
        observation_label = 'Chưa đối soát được kết quả từ Odoo'
    return {
        'version': 'ACTION_OUTCOME_REVIEW_V1',
        'merchant_reported': bool(plan.outcome_recorded_at),
        'observation_state': observation_state,
        'observation_label': observation_label,
        'missing_fields': list(observed.missing_fields_json or []) if observed else [],
        'next_step': next_step,
        'next_step_label': OUTCOME_NEXT_STEP_LABELS[next_step],
        'business_context': str(data.get('outcome_business_context') or existing.get('business_context') or '').strip()[:2_000],
        'interpretation': (
            'Kết quả được dùng để rà soát vận hành. Hàng trả, nhập kho và hoạt động đồng thời có thể làm thay đổi số liệu; không kết luận phương án là nguyên nhân của kết quả.'
        ),
    }


def _serialize_plan(plan: ActionPlanRecord) -> dict:
    today = timezone.localdate()
    due_date = plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1)))
    inventory_cost_rotation_comparison = (
        round((plan.actual_recovery_value / plan.expected_recovery_value) * 100, 1)
        if plan.actual_recovery_value is not None and plan.expected_recovery_value > 0
        else None
    )
    unit_accuracy = (
        round((plan.actual_units_sold / plan.expected_units_sold) * 100, 1)
        if plan.actual_units_sold is not None and plan.expected_units_sold > 0
        else None
    )
    observed = getattr(plan, 'observed_outcome', None)
    observed_payload = None
    if observed:
        observed_payload = {
            'status': observed.status,
            'observation_start': observed.observation_start.isoformat() if observed.observation_start else None,
            'observation_end': observed.observation_end.isoformat() if observed.observation_end else None,
            'net_units_sold': float(observed.observed_net_units_sold) if observed.observed_net_units_sold is not None else None,
            'sales_value': float(observed.observed_sales_value) if observed.observed_sales_value is not None else None,
            'inventory_change': float(observed.observed_inventory_change) if observed.observed_inventory_change is not None else None,
            'inventory_value_change': float(observed.observed_inventory_value_change) if observed.observed_inventory_value_change is not None else None,
            'missing_fields': observed.missing_fields_json or [],
            'lineage': observed.source_lineage_json or {},
            'interpretation': (
                'Số liệu ERP quan sát theo cửa sổ dữ liệu liên tục; hàng trả, nhập kho và hoạt động đồng thời có thể làm nhiễu kết quả, nên không khẳng định quan hệ nhân quả.'
            ),
            'reconciled_at': observed.reconciled_at.isoformat() if observed.reconciled_at else None,
        }
    task_summary = ActionExecutionService.task_summary(plan)
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
        'strategy_label': PLAN_STRATEGY_LABELS.get(plan.strategy, plan.strategy),
        'action_parameters': plan.action_parameters or {},
        'execution_scope': ActionPlanCompatibilityService.scope_for_plan(plan),
        'strategy_override_reason_code': plan.strategy_override_reason_code or None,
        'strategy_override_reason_label': PLAN_OVERRIDE_REASON_LABELS.get(plan.strategy_override_reason_code, None),
        'strategy_override_reason': plan.strategy_override_reason,
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
        'projected_inventory_cost_rotation': plan.expected_recovery_value,
        'merchant_reported_inventory_cost_rotation': plan.actual_recovery_value,
        # Legacy field names kept while API consumers migrate.  Their values
        # are not presented as accounting cash or actual capital release.
        'expected_recovery_value': plan.expected_recovery_value,
        'actual_recovery_value': plan.actual_recovery_value,
        'expected_sales_value': plan.expected_sales_value,
        'actual_sales_value': plan.actual_sales_value,
        'expected_units_sold': plan.expected_units_sold,
        'actual_units_sold': plan.actual_units_sold,
        'inventory_cost_rotation_vs_projection_pct': inventory_cost_rotation_comparison,
        'recovery_accuracy_pct': inventory_cost_rotation_comparison,
        'outcome_provenance': {
            'projected_inventory_cost_rotation': 'SCENARIO_OR_MANUAL_PLAN_INPUT',
            'merchant_reported_inventory_cost_rotation': 'MERCHANT_REPORTED_NOT_ACCOUNTING_RECONCILED',
            'observed_erp_outcome': 'READ_ONLY_NON_CAUSAL_OBSERVATION',
        },
        'units_accuracy_pct': unit_accuracy,
        'notes': plan.notes,
        'outcome_notes': plan.outcome_notes,
        'outcome_recorded_at': plan.outcome_recorded_at.isoformat() if plan.outcome_recorded_at else None,
        'outcome_review': plan.outcome_review_json if isinstance(plan.outcome_review_json, dict) else {},
        'outcome_reviewed_at': plan.outcome_reviewed_at.isoformat() if plan.outcome_reviewed_at else None,
        'observed_outcome': observed_payload,
        'checklist': task_summary,
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
            if decision.status != 'ACCEPTED':
                return Response({
                    'success': False,
                    'error': {
                        'code': 'DECISION_APPROVAL_REQUIRED',
                        'message': 'Cần phê duyệt khuyến nghị trước khi lập kế hoạch triển khai.',
                    },
                }, status=status.HTTP_409_CONFLICT)

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
            assignee = _assignee_for_workspace(workspace_id, data.get('assignee_user_id'))
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_ACTION_PLAN', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)

        if str(data.get('status') or 'DRAFT').upper() != 'DRAFT':
            return Response({'success': False, 'error': {'code': 'INVALID_INITIAL_STATUS', 'message': 'Kế hoạch mới luôn bắt đầu ở trạng thái Bản nháp để chờ phê duyệt.'}}, status=status.HTTP_400_BAD_REQUEST)

        requested_strategy = data.get('strategy') or (decision.action_type if decision else '')
        override_reason = str(data.get('strategy_override_reason') or '').strip()
        try:
            strategy = _normalise_plan_strategy(requested_strategy)
            override_reason_code = _override_reason_code(data.get('strategy_override_reason_code'))
            if decision:
                recommended_strategy = _normalise_plan_strategy(decision.action_type)
                if strategy != recommended_strategy and len(override_reason) < 8:
                    raise ValueError(
                        'Khi thay đổi phương án được đề xuất, cần nêu lý do điều chỉnh tối thiểu 8 ký tự.'
                    )
                eligibility = decision.action_parameters.get('eligibility', {}) if isinstance(decision.action_parameters, dict) else {}
                allowed = set(eligibility.get('eligible_actions', [])) | set(eligibility.get('requires_review_actions', []))
                # Legacy decisions predate eligibility snapshots.  In that
                # case only their original action remains selectable.
                if not allowed:
                    allowed = {recommended_strategy}
                if strategy not in allowed:
                    raise ValueError('Phương án đã chọn không đạt điều kiện của khuyến nghị hiện tại.')
                if recommended_strategy == 'REVIEW' and strategy == 'REVIEW':
                    raise ValueError('Đề xuất này cần được rà soát trước khi tạo kế hoạch thực thi.')
            execution_parameters = _execution_parameters(
                data, decision, strategy, duration_days, override_reason,
            )
            execution_scope = _execution_scope(data)
            execution_parameters['execution_scope'] = execution_scope
            evidence_check = _decision_evidence_check(
                workspace_id=workspace_id,
                sku=sku,
                strategy=strategy,
                decision=decision,
            )
            evidence_override_reason, evidence_error = _evidence_override(request, evidence_check)
            if evidence_error:
                return Response(
                    _evidence_error_payload(evidence_check, evidence_error),
                    status=status.HTTP_409_CONFLICT,
                )
            _record_execution_evidence(
                execution_parameters,
                evidence_check,
                stage='PLAN_CREATION',
                override_reason=evidence_override_reason,
                actor=_actor(request),
            )
            expected_sales = _non_negative_int(data, 'expected_sales_value', 'expected_sales', default=0)
            expected_units = _non_negative_int(data, 'expected_units_sold', 'expected_units', default=0)
            if decision:
                recommended_strategy = _normalise_plan_strategy(decision.action_type)
                projection_status = (decision.action_parameters.get('projection') or {}).get('status') if isinstance(decision.action_parameters, dict) else None
                same_strategy = strategy == recommended_strategy
                planned_rate = execution_parameters.get('discount_rate')
                same_rate = (
                    planned_rate is None and decision.discount_rate is None
                ) or (
                    planned_rate is not None and decision.discount_rate is not None
                    and abs(float(planned_rate) - float(decision.discount_rate)) <= 0.000001
                )
                # Do not let a browser carry a forecast forward after the
                # merchant changes its action. A new scenario must be run and
                # approved before an altered action receives a value.
                expected_recovery = (
                    round(decision.expected_recovery_value)
                    if same_strategy and same_rate and projection_status == 'SCENARIO_ESTIMATE'
                    else 0
                )
            else:
                expected_recovery = _non_negative_int(
                    data, 'expected_recovery_value', 'expected_recovery', default=0,
                )
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_STRATEGY', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        owner = str(data.get('owner') or (assignee.display_name if assignee else '') or '').strip()
        if not owner:
            return Response({'success': False, 'error': {'code': 'OWNER_REQUIRED', 'message': 'Cần chỉ định người phụ trách.'}}, status=status.HTTP_400_BAD_REQUEST)

        # A transient double click must not create two queues for the same
        # approved decision. A cancelled/completed plan may be replaced later.
        if decision_id:
            existing = ActionPlanRecord.objects.filter(
                workspace_id=workspace_id, decision_id=decision_id,
            ).exclude(status__in=FINAL_STATUSES).select_related('assignee_user').first()
            if existing:
                return Response({
                    'success': True, 'created': False, 'idempotent': True,
                    **_serialize_plan(existing),
                }, status=status.HTTP_200_OK)

        campaign_name = str(data.get('campaign_name') or data.get('campaign') or f'Xử lý SKU {sku}').strip()
        # The unique scope-lock row turns the compatibility check into a
        # serialised critical section, including two simultaneous browser
        # requests for different decisions on the same SKU.
        with transaction.atomic():
            ActionPlanCompatibilityService.acquire_scope_lock(workspace_id=workspace_id, sku=sku[:64])
            if decision_id:
                existing = ActionPlanRecord.objects.filter(
                    workspace_id=workspace_id, decision_id=decision_id,
                ).exclude(status__in=FINAL_STATUSES).select_related('assignee_user').first()
                if existing:
                    return Response({
                        'success': True, 'created': False, 'idempotent': True,
                        **_serialize_plan(existing),
                    }, status=status.HTTP_200_OK)
            conflicts = ActionPlanCompatibilityService.find_conflicts(
                workspace_id=workspace_id, sku=sku[:64], strategy=strategy,
                start_date=start_date, due_date=due_date, execution_scope=execution_scope,
            )
            if conflicts:
                return Response({
                    'success': False,
                    'error': {
                        'code': 'ACTION_PLAN_CONFLICT',
                        'message': 'SKU đang có kế hoạch chồng lấn và không tương thích trong cùng phạm vi/thời gian. Hãy hoàn tất, hủy hoặc chọn kho/kênh khác rõ ràng.',
                    },
                    'execution_scope': execution_scope,
                    'conflicting_plans': conflicts,
                }, status=status.HTTP_409_CONFLICT)
            plan = ActionPlanRecord.objects.create(
                workspace_id=workspace_id,
                campaign_name=campaign_name[:255], sku=sku[:64], duration_days=duration_days,
                strategy=strategy[:128], owner=owner[:128], assignee_user=assignee, start_date=start_date,
                due_date=due_date, status='DRAFT', decision_id=decision_id,
                action_parameters=execution_parameters,
                strategy_override_reason_code=override_reason_code,
                strategy_override_reason=override_reason,
                notes=str(data.get('notes') or ''), expected_recovery_value=expected_recovery,
                expected_sales_value=expected_sales, expected_units_sold=expected_units,
            )
            _record_event(plan, 'PLAN_CREATED', _actor(request), new_status='DRAFT', notes=plan.notes, metadata={
                'decision_id': decision_id,
                'due_date': due_date.isoformat(),
                'strategy_id': strategy,
                'execution_scope': execution_scope,
                'strategy_override_reason': override_reason or None,
                'strategy_override_reason_code': override_reason_code or None,
                'data_evidence': (plan.action_parameters or {}).get('data_evidence', {}),
                'execution_parameters': execution_parameters,
            })
            ActionExecutionService.create_checklist(plan)
        return Response({'success': True, 'created': True, **_serialize_plan(plan)}, status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        qs = ActionPlanRecord.objects.filter(
            workspace_id=_workspace_id(request)
        ).select_related('assignee_user', 'observed_outcome')
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
        workspace_id = _workspace_id(request)
        qs = ActionPlanRecord.objects.filter(workspace_id=workspace_id)
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
            'projected_inventory_cost_rotation': int(totals['expected'] or 0),
            'merchant_reported_inventory_cost_rotation': int(totals['actual'] or 0),
            # Legacy aliases: do not label these as realised cash/capital.
            'expected_recovery_value': int(totals['expected'] or 0),
            'actual_recovery_value': int(totals['actual'] or 0),
            'expected_sales_value': int(totals['expected_sales'] or 0),
            'actual_sales_value': int(totals['actual_sales'] or 0),
            'outcome_evidence': ActionOutcomeEvidenceService.report(workspace_id=workspace_id),
        }, status=status.HTTP_200_OK)


class ActionPlanOutcomeReportView(APIView):
    """Expose observed/missing action outcomes without a causal interpretation."""

    def get(self, request, *args, **kwargs):
        return Response(
            ActionOutcomeEvidenceService.report(workspace_id=_workspace_id(request)),
            status=status.HTTP_200_OK,
        )


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

        if new_status == 'IN_PROGRESS' and plan.decision_id:
            decision = DecisionRecord.objects.filter(decision_id=plan.decision_id, workspace_id=plan.workspace_id).first()
            if decision and decision.status == 'ACCEPTED':
                runtime = execution_runtime_status(decision)
                if runtime:
                    return Response({
                        'success': False,
                        'error': {
                            'code': 'MODEL_RUNTIME_NOT_READY',
                            'message': 'Không thể bắt đầu kế hoạch dựa trên mô hình khi model runtime chưa sẵn sàng.',
                        },
                        'model_runtime': runtime,
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if new_status == 'IN_PROGRESS':
            with transaction.atomic():
                ActionPlanCompatibilityService.acquire_scope_lock(
                    workspace_id=plan.workspace_id, sku=plan.sku,
                )
                conflicts = ActionPlanCompatibilityService.find_conflicts(
                    workspace_id=plan.workspace_id,
                    sku=plan.sku,
                    strategy=plan.strategy,
                    start_date=plan.start_date,
                    due_date=plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1))),
                    execution_scope=ActionPlanCompatibilityService.scope_for_plan(plan),
                    exclude_plan_id=str(plan.plan_id),
                )
                if conflicts:
                    return Response({
                        'success': False,
                        'error': {
                            'code': 'ACTION_PLAN_CONFLICT',
                            'message': 'Không thể bắt đầu vì có kế hoạch SKU chồng lấn, không tương thích.',
                        },
                        'execution_scope': ActionPlanCompatibilityService.scope_for_plan(plan),
                        'conflicting_plans': conflicts,
                    }, status=status.HTTP_409_CONFLICT)

        evidence_check = None
        evidence_override_reason = None
        if new_status in {'CONFIRMED', 'IN_PROGRESS'}:
            evidence_check = DecisionEvidenceFreshnessService.evaluate_plan(plan)
            evidence_override_reason, evidence_error = _evidence_override(request, evidence_check)
            if evidence_error:
                return Response(
                    _evidence_error_payload(evidence_check, evidence_error),
                    status=status.HTTP_409_CONFLICT,
                )
            if evidence_check.get('state') != 'NOT_REQUIRED':
                parameters = dict(plan.action_parameters or {})
                _record_execution_evidence(
                    parameters,
                    evidence_check,
                    stage=new_status,
                    override_reason=evidence_override_reason,
                    actor=_actor(request),
                )
                plan.action_parameters = parameters

        old_status, actor = plan.status, _actor(request)
        plan.status = new_status
        if 'notes' in request.data:
            plan.notes = str(request.data['notes'])
        if new_status == 'CONFIRMED':
            plan.confirmed_by, plan.confirmed_at = actor, timezone.now()
        plan.save()
        if evidence_override_reason:
            _record_event(
                plan,
                'DATA_EVIDENCE_OVERRIDE',
                actor,
                notes=evidence_override_reason,
                metadata={
                    'stage': new_status,
                    'evidence_code': evidence_check.get('code') if evidence_check else '',
                    'changed_fields': evidence_check.get('changed_fields', []) if evidence_check else [],
                },
            )
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
        unresolved_tasks = plan.tasks.filter(is_required=True).exclude(
            status__in={ActionPlanTask.STATUS_COMPLETED, ActionPlanTask.STATUS_SKIPPED}
        )
        if unresolved_tasks.exists():
            return Response({
                'success': False,
                'error': {
                    'code': 'CHECKLIST_INCOMPLETE',
                    'message': 'Cần hoàn tất hoặc nêu lý do không thực hiện cho các công việc bắt buộc trước khi ghi nhận kết quả.',
                },
            }, status=status.HTTP_409_CONFLICT)

        data = request.data or {}
        if not any(key in data for key in (
            'merchant_reported_inventory_cost_rotation', 'actual_recovery_value', 'actual_recovery', 'actual_sales_value',
            'actual_sales', 'actual_units_sold', 'actual_units',
        )):
            return Response({'success': False, 'error': {'code': 'OUTCOME_REQUIRED', 'message': 'Cần nhập ít nhất một kết quả thực tế.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            actual_recovery = _non_negative_int(
                data,
                'merchant_reported_inventory_cost_rotation', 'actual_recovery_value', 'actual_recovery',
                default=plan.actual_recovery_value or 0,
            )
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
        try:
            plan.outcome_review_json = _outcome_review(plan, data)
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_OUTCOME_REVIEW', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        plan.outcome_reviewed_at = timezone.now()
        plan.status = 'COMPLETED'
        plan.completed_at = plan.completed_at or timezone.now()
        plan.save()
        if plan.decision_id:
            decision = DecisionRecord.objects.filter(decision_id=plan.decision_id, workspace_id=plan.workspace_id).first()
            if decision and decision.status == 'EXECUTED':
                DecisionStatusService.update_status(decision.decision_id, 'COMPLETED', actor=actor, notes='Action plan outcome recorded.')
        _record_event(plan, 'OUTCOME_RECORDED', actor, old_status, 'COMPLETED', plan.outcome_notes, {
            'merchant_reported_inventory_cost_rotation': actual_recovery,
            'actual_recovery_value': actual_recovery,
            'actual_sales_value': actual_sales,
            'actual_units_sold': actual_units,
            'outcome_review': plan.outcome_review_json,
        })
        payload = _serialize_plan(plan)
        rotation_comparison = payload['inventory_cost_rotation_vs_projection_pct']
        unit_accuracy = payload['units_accuracy_pct'] or 0.0
        payload['outcome'] = {
            'projected_inventory_cost_rotation': plan.expected_recovery_value,
            'merchant_reported_inventory_cost_rotation': plan.actual_recovery_value,
            'inventory_cost_rotation_vs_projection_pct': rotation_comparison,
            # Compatibility aliases.
            'expected_recovery_value': plan.expected_recovery_value,
            'actual_recovery_value': plan.actual_recovery_value,
            'recovery_accuracy_pct': rotation_comparison,
            'expected_units_sold': plan.expected_units_sold,
            'actual_units_sold': plan.actual_units_sold,
            'units_vs_projection_pct': unit_accuracy,
            'units_accuracy_pct': unit_accuracy,
            'expected_sales_value': plan.expected_sales_value,
            'actual_sales_value': plan.actual_sales_value,
            'assessment': 'MERCHANT_REPORTED_ONLY',
            'interpretation': (
                'Số liệu do merchant nhập để đối chiếu vận hành. Không phải đối soát kế toán/ERP và không dùng để khẳng định kế hoạch gây ra kết quả.'
            ),
        }
        # Backward-compatible field for older API consumers.  It is strictly
        # a band over merchant-entered comparisons with the plan projection,
        # not a measure of recommendation accuracy, financial recovery, or
        # causal action impact.  New clients must use the explicitly named
        # provenance fields above instead.
        comparison_values = [
            value for value in (rotation_comparison, payload['outcome']['units_vs_projection_pct'])
            if value is not None
        ]
        if not comparison_values:
            legacy_usefulness = 'NOT_ASSESSED'
        elif sum(comparison_values) / len(comparison_values) >= 75:
            legacy_usefulness = 'HIGH'
        elif sum(comparison_values) / len(comparison_values) >= 50:
            legacy_usefulness = 'MEDIUM'
        else:
            legacy_usefulness = 'LOW'
        payload['outcome']['decision_usefulness'] = legacy_usefulness
        payload['outcome']['decision_usefulness_provenance'] = (
            'LEGACY_MERCHANT_REPORTED_COMPARISON_ONLY'
        )
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


class ActionPlanTaskListView(APIView):
    """Expose merchant-readable execution checklist and evidence."""

    def get(self, request, plan_id, *args, **kwargs):
        plan = _plan_or_404(request, plan_id)
        if not plan:
            return Response({'success': False, 'error': {'code': 'PLAN_NOT_FOUND', 'message': 'Không tìm thấy kế hoạch trong workspace hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)
        return Response({'plan_id': plan.plan_id, 'checklist': ActionExecutionService.task_summary(plan)})


class ActionPlanTaskUpdateView(APIView):
    def patch(self, request, plan_id, task_id, *args, **kwargs):
        permission_error = _write_permission_error(request)
        if permission_error:
            return permission_error
        plan = _plan_or_404(request, plan_id)
        task = plan.tasks.filter(id=task_id).first() if plan else None
        if not task:
            return Response({'success': False, 'error': {'code': 'TASK_NOT_FOUND', 'message': 'Không tìm thấy công việc trong kế hoạch hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)
        try:
            due_date = None
            if 'due_date' in request.data:
                due_date = _parse_date(request.data.get('due_date'), 'Hạn công việc')
                plan_due = plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1)))
                if due_date < plan.start_date or due_date > plan_due:
                    raise ValueError('Hạn công việc phải nằm trong thời gian của kế hoạch.')
            assignee = None
            if 'assignee_user_id' in request.data:
                assignee = _assignee_for_workspace(plan.workspace_id, request.data.get('assignee_user_id'))
            ActionExecutionService.update_task(
                task=task,
                status=request.data.get('status', task.status),
                actor=_actor(request),
                note=str(request.data.get('note') or ''),
                skipped_reason=str(request.data.get('skipped_reason') or ''),
                due_date=due_date,
                assignee_user=assignee,
            )
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_TASK_UPDATE', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        _record_event(plan, 'TASK_UPDATED', _actor(request), notes=task.title, metadata={
            'task_id': task.id, 'status': task.status,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'assignee_user_id': task.assignee_user_id,
        })
        return Response({'success': True, 'checklist': ActionExecutionService.task_summary(plan)})


class ActionPlanTaskEvidenceView(APIView):
    def post(self, request, plan_id, task_id, *args, **kwargs):
        permission_error = _write_permission_error(request)
        if permission_error:
            return permission_error
        plan = _plan_or_404(request, plan_id)
        task = plan.tasks.filter(id=task_id).first() if plan else None
        if not task:
            return Response({'success': False, 'error': {'code': 'TASK_NOT_FOUND', 'message': 'Không tìm thấy công việc trong kế hoạch hiện tại.'}}, status=status.HTTP_404_NOT_FOUND)
        try:
            ActionExecutionService.add_evidence(
                task=task, evidence_type=str(request.data.get('type') or 'LINK'),
                title=str(request.data.get('title') or ''), reference_url=str(request.data.get('reference_url') or ''),
                note=str(request.data.get('note') or ''), actor=_actor(request),
            )
        except ValueError as exc:
            return Response({'success': False, 'error': {'code': 'INVALID_EVIDENCE', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        _record_event(plan, 'TASK_EVIDENCE_ADDED', _actor(request), notes=task.title, metadata={'task_id': task.id})
        return Response({'success': True, 'checklist': ActionExecutionService.task_summary(plan)}, status=status.HTTP_201_CREATED)
