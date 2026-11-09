import logging
import os
import base64
import json
from datetime import timedelta
import pandas as pd
from django.conf import settings
from django.db.models import Q, Count, F
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.models import (
    DatasetVersion, IngestionSession, SlowMovingAssessmentRun,
    SlowMovingAlertFeedback, SlowMovingAlertState, SlowMovingDispositionEvent,
    SlowMovingRiskAssessment, SlowMovingSkuContext, SlowMovingAlertPassport,
    SlowMovingAlertAttentionEvent, SlowMovingFeedbackRemediation,
)
from supplyforge.metrics import record_risk_assessment, update_high_risk_sku_gauge
from src.analytics.risk_assessment_assembler import RiskAssessmentAssembler

logger = logging.getLogger(__name__)


def _risk_queryset_for_request(request):
    """Return only the risk records visible to an authenticated workspace."""
    queryset = SlowMovingRiskAssessment.objects.all()
    if getattr(request, 'tenant_context_validated', False) and getattr(request, 'workspace_id', None):
        queryset = queryset.filter(session__workspace_id=request.workspace_id)
    elif getattr(settings, 'IS_DEPLOYED', False):
        # Middleware establishes tenant context for every deployed request.
        # A malformed request must never become a cross-workspace query.
        queryset = queryset.none()
    return queryset


def _source_payload(run):
    if not run:
        return {
            'type': 'CSV',
            'status': 'NO_COMPLETED_RUN',
            'message': 'Chưa có lần phân tích CSV hoàn tất cho bộ dữ liệu đang dùng.',
        }
    payload = {
        'type': run.source_type,
        'status': run.status,
        'run_id': str(run.id),
        'dataset_version': run.dataset_version.version_label if run.dataset_version_id else None,
        'analysis_as_of': run.analysis_as_of.isoformat(),
        'freshness': run.source_freshness,
        'policy_version': run.policy_version,
        'summary': run.summary,
    }
    try:
        from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService

        quality = SlowMovingQualityMonitoringService.report(
            workspace_id=run.workspace_id, source_key=run.source_key,
        )
        payload['quality'] = {
            'state': quality['state'],
            'metrics': {
                key: quality.get('metrics', {}).get(key)
                for key in ('matured_eligible_skus', 'opened_high_risk_alert_count', 'high_risk_precision')
            },
            # Delivery paths must consume this fail-closed contract instead
            # of inferring safety from a score or a risk class.
            'notification': quality.get('notification'),
        }
    except Exception:
        logger.exception('Could not attach slow-moving quality state for run=%s', run.id)
        payload['quality'] = {'state': 'QUALITY_UNAVAILABLE'}
    return payload


def _operational_csv_queryset(request, session_id=None):
    """Resolve one CSV source run; never union historical import results."""
    queryset = _risk_queryset_for_request(request)
    workspace_id = getattr(request, 'workspace_id', None) if getattr(request, 'tenant_context_validated', False) else None
    runs = SlowMovingAssessmentRun.objects.filter(
        source_type=SlowMovingAssessmentRun.SOURCE_CSV,
        status=SlowMovingAssessmentRun.STATUS_COMPLETED,
    ).select_related('dataset_version', 'dataset_version__ingestion_session')
    if workspace_id:
        runs = runs.filter(workspace_id=workspace_id)
    elif getattr(settings, 'IS_DEPLOYED', False):
        return queryset.none(), None

    if session_id:
        run = runs.filter(dataset_version__ingestion_session_id=session_id).order_by('-completed_at').first()
        if run:
            return queryset.filter(assessment_run=run), run
        # Explicit session lookup is a legacy/research route only. It cannot
        # contaminate the default merchant dashboard with previous imports.
        return queryset.filter(session_id=session_id, assessment_run__isnull=True), None

    run = runs.filter(is_current=True).first()
    if run:
        return queryset.filter(assessment_run=run), run
    # Backward-compatible read for workspaces created before DatasetVersion.
    # Once a workspace has adopted versioned CSV ingestion, an absent run is
    # intentionally empty rather than a mixture of historical sessions.
    versions = DatasetVersion.objects.filter(status=DatasetVersion.STATUS_ACTIVE)
    if workspace_id:
        versions = versions.filter(workspace_id=workspace_id)
    if not versions.exists():
        return queryset.filter(assessment_run__isnull=True), None
    return queryset.none(), None


def _compact_risk_evidence(evidence):
    """Keep list responses bounded; the detail endpoint owns full evidence."""
    evidence = evidence if isinstance(evidence, dict) else {}
    allowed = {
        'sales_velocity_90d', 'sales_velocity_30d', 'zero_rate_90d',
        'dsls', 'sold_90d', 'sold_30d', 'stock_quantity', 'unit_cost',
        'capital_exposure_vnd', 'forecast_7d', 'forecast_14d',
        'forecast_30d', 'forecast_trend', 'forecast_model', 'demand_pattern',
        'eligibility_status', 'eligibility_reasons', 'alert_lifecycle_status',
        'alert_consecutive_runs', 'alert_state_id', 'score_semantics', 'source_data_as_of',
        'catalog_context', 'alert_changed_facts', 'alert_event_type',
    }
    return {key: evidence[key] for key in allowed if key in evidence}


def _annotate_risk_metrics(queryset):
    # Operational rows materialise these fields on write. Older research rows
    # retain null values rather than forcing a JSON cast into the queue path.
    return queryset.annotate(
        list_capital_exposure=F('capital_exposure_vnd'),
        list_dsls=F('days_since_last_sale'),
    )


_CURSOR_SORT_FIELDS = {
    'risk_score': 'priority_score',
    'capital_exposure': 'capital_exposure_vnd',
    'dsls': 'days_since_last_sale',
}


def _encode_risk_cursor(*, sort_by: str, descending: bool, record) -> str:
    field = _CURSOR_SORT_FIELDS[sort_by]
    payload = {
        'sort_by': sort_by,
        'descending': descending,
        'metric': str(getattr(record, field)),
        'sku': record.sku,
        'id': str(record.id),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii').rstrip('=')


def _decode_risk_cursor(value: str, *, sort_by: str, descending: bool) -> dict:
    try:
        padded = f"{value}{'=' * (-len(value) % 4)}"
        payload = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('cursor không hợp lệ.') from exc
    if payload.get('sort_by') != sort_by or bool(payload.get('descending')) != descending:
        raise ValueError('cursor không đúng với cách sắp xếp đang dùng.')
    if not payload.get('sku') or not payload.get('id') or payload.get('metric') in (None, ''):
        raise ValueError('cursor thiếu vị trí bản ghi.')
    return payload


def _after_risk_cursor(queryset, *, sort_by: str, descending: bool, cursor: dict):
    field = _CURSOR_SORT_FIELDS[sort_by]
    metric_lookup = f'{field}__lt' if descending else f'{field}__gt'
    return queryset.filter(
        Q(**{metric_lookup: cursor['metric']})
        | Q(**{field: cursor['metric'], 'sku__gt': cursor['sku']})
        | Q(**{field: cursor['metric'], 'sku': cursor['sku'], 'id__gt': cursor['id']})
    )


def _model_payload(record):
    if record.risk_probability is None:
        return {'name': 'Quy tắc ưu tiên vận hành', 'version': record.model_version}
    return {
        'name': 'LightGBM' if 'lightgbm' in (record.model_version or '').lower() else 'Risk classifier',
        'version': record.model_version,
    }


# ── M3-07 Risk API & Persistence Views ─────────────────────────────────

@api_view(['POST'])
def run_and_persist_assessments(request=None, session_id=None, workspace_id=1, user_id='user_default_001'):
    """
    POST /api/v1/risk/assessments
    Executes Risk Assessment Assembly (M3-06) and persists results into Django DB.
    Enforces DAT-11 Data Readiness Gate Check.
    """
    if request is not None:
        session_id = request.data.get('session_id') or request.query_params.get('session_id')
        if getattr(settings, 'IS_DEPLOYED', False) and not (
            getattr(request, 'tenant_context_validated', False) and getattr(request, 'workspace_id', None)
        ):
            return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)

    session = None
    scoped_workspace_id = (
        getattr(request, 'workspace_id', None)
        if request is not None and getattr(request, 'tenant_context_validated', False)
        else None
    )
    if session_id:
        try:
            session_query = IngestionSession.objects
            if scoped_workspace_id:
                session_query = session_query.filter(workspace_id=scoped_workspace_id)
            session = session_query.get(id=session_id)
        except IngestionSession.DoesNotExist:
            pass

    if not session:
        session_query = IngestionSession.objects
        if scoped_workspace_id:
            session_query = session_query.filter(workspace_id=scoped_workspace_id)
        session = session_query.order_by('-created_at').first()

    if not session:
        _auto_populate_assessments_from_products(session_id)
        if request is not None:
            return Response({'status': 'SUCCESS', 'message': 'Auto-populated risk assessments from products.'})
        return {'status': 'SUCCESS'}

    # 1. DAT-11 Readiness Gate Check
    if session.status == 'NOT_READY':
        return Response(
            {
                'error': 'Session chưa qua DAT-11 Data Readiness Gate. Quá trình lưu trữ Risk Assessment bị chặn.',
                'readiness_status': 'NOT_READY',
                'session_id': str(session.id)
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # 2. Run Assembly Engine
    pred_df = None
    diag_df = None
    if session.m3_probability_calibration_json:
        recs = session.m3_probability_calibration_json.get('calibratedPredictions')
        if recs:
            pred_df = pd.DataFrame(recs)
    elif session.m3_risk_classifications_json:
        recs = session.m3_risk_classifications_json.get('classifications')
        if recs:
            pred_df = pd.DataFrame(recs)

    if session.m3_risk_diagnostics_json:
        drecs = session.m3_risk_diagnostics_json.get('profiles')
        if drecs:
            diag_df = pd.DataFrame(drecs)

    # Fallback to local files if session JSON is missing
    PROJECT_ROOT = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    if pred_df is None or pred_df.empty:
        _auto_populate_assessments_from_products(session_id)
        if request is not None:
            return Response({'status': 'SUCCESS', 'message': 'Auto-populated risk assessments from products.'})
        return {'status': 'SUCCESS'}


    try:
        assembler = RiskAssessmentAssembler(session_id=str(session.id))
        result = assembler.assemble_risk_assessments(
            predictions_df=pred_df,
            diagnostics_df=diag_df,
            session_id=str(session.id),
            output_dir=reports_dir,
            data_dir=data_dir
        )

        assessments_list = result.get('assessments', [])
        persisted_records = []

        # 3. Persist into Django Model
        for item in assessments_list:
            sku_val = item['sku']
            r_class = item['assessment']['risk_class']
            r_prob = float(item['assessment']['risk_probability'])
            r_score = float(item['assessment']['risk_score'])

            # Validation Rules
            if r_class not in ['CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK']:
                continue
            if not (0.0 <= r_prob <= 1.0):
                continue

            obj, created = SlowMovingRiskAssessment.objects.update_or_create(
                session=session,
                sku=sku_val,
                defaults={
                    'canonical_sku_id': item.get('canonical_sku_id', sku_val),
                    'product_name': item.get('product_name', f'Product {sku_val}'),
                    'category': item.get('category', 'Mother & Baby'),
                    'risk_class': r_class,
                    'risk_probability': r_prob,
                    'risk_score': r_score,
                    'primary_signals': item.get('primary_signals', []),
                    'supporting_signals': item.get('supporting_signals', []),
                    'diagnostics': item.get('diagnostics', []),
                    'evidence': item.get('evidence', {}),
                    'decision_cutoff': item.get('metadata', {}).get('decision_cutoff', 't0'),
                    'model_version': item.get('metadata', {}).get('model_version', 'xgboost_exp03_v1'),
                    'calibration_version': item.get('metadata', {}).get('calibration_version', 'calibration_v1.0'),
                    'diagnostic_rule_version': item.get('metadata', {}).get('diagnostic_rule_version', 'rules_v1.0'),
                    'dataset_version': item.get('metadata', {}).get('data_version', 'v1.0'),
                    'assessment_status': item.get('assessment_status', 'COMPLETE')
                }
            )
            persisted_records.append({
                'assessment_id': str(obj.id),
                'sku': obj.sku,
                'risk_class': obj.risk_class,
                'risk_score': obj.risk_score
            })

        session.m3_risk_assessments_json = result
        session.save(update_fields=['m3_risk_assessments_json', 'updated_at'])

        return Response({
            'session_id': str(session.id),
            'status': 'SUCCESS',
            'persisted_count': len(persisted_records),
            'summary': result.get('summary', {}),
            'records': persisted_records
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Failed to persist Risk Assessment for session %s", session_id)
        return Response(
            {'error': f'Lỗi lưu trữ Risk Assessment M3-07: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def list_risk_assessments(request):
    """
    GET /api/v1/risk/assessments
    Query & Filter Persisted Risk Assessments by risk_class, sku, sort by risk_score.
    Includes smart fallback to all assessments or auto-population if DB table is empty.
    """
    session_id = request.query_params.get('session_id')
    risk_class = request.query_params.get('risk_class')
    sku = request.query_params.get('sku')
    sort_by = request.query_params.get('sort_by', '-risk_score')

    queryset, source_run = _operational_csv_queryset(request, session_id)

    # Incomplete data is visible on demand, never silently scored as a safe
    # SKU in the merchant queue.
    include_ineligible = str(request.query_params.get('include_ineligible') or '').lower() in {'1', 'true', 'yes'}
    if not include_ineligible and source_run:
        queryset = queryset.filter(assessment_status='COMPLETE')

    if risk_class:
        queryset = queryset.filter(risk_class__iexact=risk_class)
    if sku:
        queryset = queryset.filter(Q(sku__icontains=sku) | Q(product_name__icontains=sku))

    category = request.query_params.get('category')
    if category:
        queryset = queryset.filter(category__icontains=category)

    capital_band = request.query_params.get('capital_band')
    aging_band = request.query_params.get('aging_band')
    if capital_band == 'LOW':
        queryset = queryset.filter(capital_exposure_vnd__lt=10_000_000)
    elif capital_band == 'MID':
        queryset = queryset.filter(capital_exposure_vnd__gte=10_000_000, capital_exposure_vnd__lte=50_000_000)
    elif capital_band == 'HIGH':
        queryset = queryset.filter(capital_exposure_vnd__gt=50_000_000)
    if aging_band == 'FRESH':
        queryset = queryset.filter(days_since_last_sale__lte=30)
    elif aging_band == 'AGING':
        queryset = queryset.filter(days_since_last_sale__gt=30, days_since_last_sale__lte=60)
    elif aging_band == 'AT_RISK':
        queryset = queryset.filter(days_since_last_sale__gt=60, days_since_last_sale__lte=90)
    elif aging_band == 'CRITICAL':
        queryset = queryset.filter(days_since_last_sale__gt=90)

    raw_sort = sort_by.lstrip('-')
    descending = sort_by.startswith('-')
    if raw_sort == 'risk_score':
        queryset = queryset.order_by('-priority_score' if descending else 'priority_score', 'sku', 'id')
    elif raw_sort == 'capital_exposure':
        queryset = queryset.order_by('-capital_exposure_vnd' if descending else 'capital_exposure_vnd', 'sku', 'id')
    elif raw_sort == 'dsls':
        queryset = queryset.order_by('-days_since_last_sale' if descending else 'days_since_last_sale', 'sku', 'id')
    elif sort_by in ['risk_probability', '-risk_probability', 'created_at', '-created_at']:
        queryset = queryset.order_by(sort_by, 'sku', 'id')
    else:
        raw_sort, descending = 'risk_score', True
        queryset = queryset.order_by('-priority_score', 'sku', 'id')

    try:
        limit = min(100, max(1, int(request.query_params.get('limit', 50))))
        offset = max(0, int(request.query_params.get('offset', 0)))
    except (TypeError, ValueError):
        return Response({'error': 'limit và offset phải là số nguyên hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    cursor_mode = str(request.query_params.get('pagination') or '').lower() == 'cursor' or bool(request.query_params.get('cursor'))
    if cursor_mode and raw_sort in _CURSOR_SORT_FIELDS:
        try:
            cursor_value = request.query_params.get('cursor')
            if cursor_value:
                queryset = _after_risk_cursor(
                    queryset.filter(**{f'{_CURSOR_SORT_FIELDS[raw_sort]}__isnull': False}),
                    sort_by=raw_sort, descending=descending,
                    cursor=_decode_risk_cursor(cursor_value, sort_by=raw_sort, descending=descending),
                )
            else:
                queryset = queryset.filter(**{f'{_CURSOR_SORT_FIELDS[raw_sort]}__isnull': False})
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    total_count = queryset.count() if not cursor_mode else None
    records = list(queryset.only(
        'id', 'sku', 'canonical_sku_id', 'product_name', 'category',
        'risk_class', 'risk_score', 'risk_probability', 'primary_signals',
        'supporting_signals', 'evidence', 'model_version',
        'assessment_timestamp', 'priority_score', 'sellable_stock_quantity',
        'capital_exposure_vnd', 'days_since_last_sale', 'eligibility_status',
    )[0:limit + 1] if cursor_mode else queryset.only(
        'id', 'sku', 'canonical_sku_id', 'product_name', 'category',
        'risk_class', 'risk_score', 'risk_probability', 'primary_signals',
        'supporting_signals', 'evidence', 'model_version',
        'assessment_timestamp', 'priority_score', 'sellable_stock_quantity',
        'capital_exposure_vnd', 'days_since_last_sale', 'eligibility_status',
    )[offset:offset+limit])
    has_next = cursor_mode and len(records) > limit
    if has_next:
        records = records[:limit]
    alert_ids = [
        str((record.evidence or {}).get('alert_state_id'))
        for record in records if (record.evidence or {}).get('alert_state_id')
    ]
    alert_statuses = {
        str(alert.id): alert.status
        for alert in SlowMovingAlertState.objects.filter(id__in=alert_ids).only('id', 'status')
    }

    data = []
    for record in records:
        evidence = _compact_risk_evidence(record.evidence)
        alert_id = evidence.get('alert_state_id')
        if alert_id and str(alert_id) in alert_statuses:
            evidence['alert_lifecycle_status'] = alert_statuses[str(alert_id)]
        data.append({
            'assessment_id': str(record.id),
            'sku': record.sku,
            'canonical_sku_id': record.canonical_sku_id,
            'product_name': record.product_name,
            'category': record.category,
            'risk': {
                'class': record.risk_class,
                'score': record.risk_score,
                'priority_score': (
                    record.priority_score
                    if record.priority_score is not None else record.risk_score
                ),
                'probability': record.risk_probability,
                'has_calibrated_probability': record.risk_probability is not None,
            },
            'primary_signals': record.primary_signals,
            'supporting_signals': record.supporting_signals,
            'evidence': evidence,
            'capital_exposure_vnd': float(record.capital_exposure_vnd) if record.capital_exposure_vnd is not None else evidence.get('capital_exposure_vnd'),
            'stock_quantity': float(record.sellable_stock_quantity) if record.sellable_stock_quantity is not None else evidence.get('stock_quantity', 0),
            'unit_cost': evidence.get('unit_cost', 0),
            'model': _model_payload(record),
            'assessment_timestamp': record.assessment_timestamp.isoformat()
        })

    return Response({
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'assessments': data,
        'source': _source_payload(source_run),
        'pagination': {
            'mode': 'cursor' if cursor_mode else 'offset',
            'has_next': bool(has_next),
            'next_cursor': _encode_risk_cursor(
                sort_by=raw_sort, descending=descending, record=records[-1],
            ) if has_next and records and raw_sort in _CURSOR_SORT_FIELDS else None,
        },
    })


@api_view(['GET'])
def get_risk_assessment_detail(request, id):
    """
    GET /api/v1/risk/assessments/<id>
    Retrieve Single Risk Assessment Detail Record by UUID.
    """
    try:
        r = _risk_queryset_for_request(request).get(id=id)
    except (SlowMovingRiskAssessment.DoesNotExist, ValueError):
        return Response({'error': f'Không tìm thấy Risk Assessment với ID {id}'}, status=status.HTTP_404_NOT_FOUND)

    alert_id = (r.evidence or {}).get('alert_state_id')
    passport = None
    if alert_id:
        passport = SlowMovingAlertPassport.objects.filter(
            workspace_id=r.session.workspace_id,
            alert_state_id=alert_id,
        ).order_by('-created_at').first()
    return Response({
        'assessment_id': str(r.id),
        'sku': r.sku,
        'canonical_sku_id': r.canonical_sku_id,
        'product_name': r.product_name,
        'category': r.category,
        'risk': {
            'class': r.risk_class,
            'score': r.risk_score,
            'priority_score': r.risk_score,
            'probability': r.risk_probability,
            'has_calibrated_probability': r.risk_probability is not None,
        },
        'primary_signals': r.primary_signals,
        'supporting_signals': r.supporting_signals,
        'diagnostics': r.diagnostics,
        'evidence': r.evidence,
        'model': _model_payload(r),
        'calibration_version': r.calibration_version,
        'diagnostic_rule_version': r.diagnostic_rule_version,
        'data_version': r.dataset_version,
        'assessment_status': r.assessment_status,
        'assessment_timestamp': r.assessment_timestamp.isoformat(),
        'source': _source_payload(r.assessment_run) if r.assessment_run_id else None,
        'alert_passport': _serialize_alert_passport(passport),
    })


@api_view(['GET'])
def get_sku_risk_assessment(request, sku_id):
    """
    GET /api/v1/risk/skus/<sku_id>
    Direct SKU Risk Assessment lookup.
    """
    session_id = request.query_params.get('session_id')
    queryset, source_run = _operational_csv_queryset(request, session_id)
    if source_run:
        queryset = queryset.filter(assessment_status='COMPLETE')
    r = queryset.filter(
        Q(sku=sku_id) | Q(canonical_sku_id=sku_id)
    ).order_by('-assessment_timestamp').first()
    if not r:
        return Response({'error': f'Không tìm thấy Risk Assessment cho SKU {sku_id}'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'assessment_id': str(r.id),
        'sku': r.sku,
        'canonical_sku_id': r.canonical_sku_id,
        'product_name': r.product_name,
        'category': r.category,
        'risk': {
            'class': r.risk_class,
            'score': r.risk_score,
            'priority_score': r.risk_score,
            'probability': r.risk_probability,
            'has_calibrated_probability': r.risk_probability is not None,
        },
        'primary_signals': r.primary_signals,
        'supporting_signals': r.supporting_signals,
        'diagnostics': r.diagnostics,
        'evidence': r.evidence,
        'model': _model_payload(r),
        'calibration_version': r.calibration_version,
        'diagnostic_rule_version': r.diagnostic_rule_version,
        'data_version': r.dataset_version,
        'assessment_status': r.assessment_status,
        'assessment_timestamp': r.assessment_timestamp.isoformat(),
        'source': _source_payload(source_run),
    })


def _legacy_auto_populate_assessments_from_products(session_id=None):
    """
    Auto-populates SlowMovingRiskAssessment DB table from real imported Product + Order data.
    Calculates real evidence: sales velocity, DSLS, zero-rate, ADI from actual OrderItem history.
    """
    from datetime import datetime, timedelta
    from django.db.models import Max, Sum, Count, Q
    from django.utils import timezone
    from supplyforge.models import InventoryRecord, Product, Order, OrderItem, Sku, IngestionSession
    from supplyforge.services.inventory_readiness import InventoryReadinessGate

    session = (
        IngestionSession.objects.select_related('workspace')
        .filter(id=session_id)
        .first()
        if session_id else None
    )
    if not session:
        logger.warning('Skipping risk auto-population without an explicit ingestion session.')
        return
    real_items = []
    seen_skus = set()

    # Determine the assessment point from the latest observed demand *or*
    # explicit inventory snapshot. A later stock snapshot is valid evidence
    # for the same operational decision and must not be hidden merely because
    # no order was placed on that exact date.
    max_order_dt = Order.objects.filter(workspace_id=session.workspace_id).aggregate(Max('created_at'))['created_at__max']
    max_inventory_date = InventoryRecord.objects.filter(
        sku__workspace_id=session.workspace_id,
    ).aggregate(Max('record_date'))['record_date__max']
    reference_points = [point for point in (max_order_dt, max_inventory_date) if point is not None]
    if reference_points:
        normalized_points = []
        for point in reference_points:
            if isinstance(point, datetime):
                normalized_points.append(
                    timezone.make_aware(point) if timezone.is_naive(point) else point
                )
            else:
                normalized_points.append(
                    timezone.make_aware(datetime.combine(point, datetime.max.time()))
                )
        ref_date = max(normalized_points)
    else:
        ref_date = timezone.now()

    ninety_days_ago = ref_date - timedelta(days=90)
    thirty_days_ago = ref_date - timedelta(days=30)
    seven_days_ago = ref_date - timedelta(days=7)

    # 1. Build product list from OrderItem
    seen_skus = set()
    real_items = []

    p_qs = Product.objects.filter(workspace_id=session.workspace_id)
    for p in p_qs:
        sku_val = p.item_sku or p.third_party_id or f"SKU_{p.id}"
        name_val = p.product_name or f"Product {sku_val}"
        if sku_val not in seen_skus:
            seen_skus.add(sku_val)
            real_items.append({
                'sku': sku_val,
                'canonical_sku_id': f"CSKU_{sku_val}",
                'product_name': name_val,
                'category': getattr(p, 'platform', None) or 'Sales Orders',
                'stock': int(p.stock or 0),
                'cost': float(p.cost or p.price or 0),
                'item_id': p.item_id,
                'item_sku': p.item_sku,
            })

    if not real_items:
        oi_items = OrderItem.objects.filter(
            order__workspace_id=session.workspace_id,
        ).values('sku', 'product_name').distinct()[:1000]
        for item in oi_items:
            sku_val = item.get('sku')
            name_val = item.get('product_name')
            if sku_val and sku_val not in seen_skus:
                seen_skus.add(sku_val)
                real_items.append({
                    'sku': sku_val,
                    'canonical_sku_id': f"CSKU_{sku_val}",
                    'product_name': name_val or f"Product {sku_val}",
                    'category': 'Tồn kho',
                    'stock': 0,
                    'cost': 0,
                    'item_id': None,
                    'item_sku': sku_val,
                })

    if not real_items:
        SlowMovingRiskAssessment.objects.filter(session=session).delete()
        return

    # Delete old assessments for this session
    SlowMovingRiskAssessment.objects.filter(session=session).delete()

    # 3. Compute real evidence in bulk queries across all SKUs & product names
    evidence_map = {}
    
    oi_stats_90d_sku = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=ninety_days_ago, order__created_at__lte=ref_date
    ).values('sku').annotate(
        sold_90d=Sum('quantity'),
        last_sale=Max('order__created_at'),
        order_days_cnt=Count('order__created_at__date', distinct=True)
    )
    stats_90d_sku = {r['sku'].upper().strip(): r for r in oi_stats_90d_sku if r.get('sku')}

    oi_stats_90d_name = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=ninety_days_ago, order__created_at__lte=ref_date
    ).values('product_name').annotate(
        sold_90d=Sum('quantity'),
        last_sale=Max('order__created_at'),
        order_days_cnt=Count('order__created_at__date', distinct=True)
    )
    stats_90d_name = {r['product_name'].strip(): r for r in oi_stats_90d_name if r.get('product_name')}

    oi_stats_30d_sku = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=thirty_days_ago, order__created_at__lte=ref_date
    ).values('sku').annotate(sold_30d=Sum('quantity'))
    stats_30d_sku = {r['sku'].upper().strip(): r['sold_30d'] for r in oi_stats_30d_sku if r.get('sku')}

    oi_stats_30d_name = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=thirty_days_ago, order__created_at__lte=ref_date
    ).values('product_name').annotate(sold_30d=Sum('quantity'))
    stats_30d_name = {r['product_name'].strip(): r['sold_30d'] for r in oi_stats_30d_name if r.get('product_name')}

    oi_stats_7d_sku = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=seven_days_ago, order__created_at__lte=ref_date
    ).values('sku').annotate(sold_7d=Sum('quantity'))
    stats_7d_sku = {r['sku'].upper().strip(): r['sold_7d'] for r in oi_stats_7d_sku if r.get('sku')}

    oi_stats_7d_name = OrderItem.objects.filter(
        order__workspace_id=session.workspace_id,
        order__created_at__gte=seven_days_ago, order__created_at__lte=ref_date
    ).values('product_name').annotate(sold_7d=Sum('quantity'))
    stats_7d_name = {r['product_name'].strip(): r['sold_7d'] for r in oi_stats_7d_name if r.get('product_name')}

    total_orders_sku = {
        r['sku'].upper().strip(): r['cnt']
        for r in OrderItem.objects.filter(order__workspace_id=session.workspace_id).values('sku').annotate(cnt=Count('id'))
        if r.get('sku')
    }
    total_orders_name = {
        r['product_name'].strip(): r['cnt']
        for r in OrderItem.objects.filter(order__workspace_id=session.workspace_id).values('product_name').annotate(cnt=Count('id'))
        if r.get('product_name')
    }

    for item in real_items:
        s_val = (item.get('item_sku') or item.get('sku') or '').upper().strip()
        p_name = (item.get('product_name') or '').strip()

        st90 = stats_90d_sku.get(s_val) or stats_90d_name.get(p_name) or {}
        sold_90d = st90.get('sold_90d') or 0
        sold_30d = stats_30d_sku.get(s_val) or stats_30d_name.get(p_name) or 0
        sold_7d = stats_7d_sku.get(s_val) or stats_7d_name.get(p_name) or 0
        last_sale = st90.get('last_sale')
        order_days_90d = st90.get('order_days_cnt') or 0
        total_orders = total_orders_sku.get(s_val) or total_orders_name.get(p_name) or 0

        if last_sale:
            dsls = max(0, (ref_date - last_sale).days)
        else:
            dsls = 999

        velocity_90d = round(float(sold_90d) / 90.0, 4) if sold_90d else 0.0
        velocity_30d = round(float(sold_30d) / 30.0, 4) if sold_30d else 0.0
        zero_rate_90d = round(1.0 - (order_days_90d / 90.0), 3) if order_days_90d else 1.0
        adi = round(90.0 / max(order_days_90d, 1), 2)

        evidence_map[s_val] = {
            'sold_90d': int(sold_90d),
            'sold_30d': int(sold_30d),
            'sold_7d': int(sold_7d),
            'velocity_90d': velocity_90d,
            'velocity_30d': velocity_30d,
            'dsls': dsls,
            'zero_rate_90d': zero_rate_90d,
            'adi': adi,
            'order_days_90d': order_days_90d,
            'total_orders': total_orders,
        }

    session_obj = session

    assessments_to_create = []

    for item in real_items:
        ev = evidence_map.get(item['sku'], {})
        velocity = ev.get('velocity_90d', 0)
        dsls = ev.get('dsls', 999)
        zero_rate = ev.get('zero_rate_90d', 1.0)
        adi = ev.get('adi', 99)
        total_orders = ev.get('total_orders', 0)

        # Attempt to run HybridModelPipeline (XGBoost primary model + Isotonic calibration)
        sku_val = item['sku']
        risk_probability = None
        risk_class = None
        lgb_forecast_7d = 0.0
        lgb_forecast_14d = 0.0
        lgb_forecast_30d = 0.0
        assessment_model_version = 'rule_based_demand_v1'
        assessment_calibration_version = 'none'

        try:
            from supplyforge.services.ml_model import HybridModelPipeline
            pred = HybridModelPipeline.predict_risk(sku_val, workspace_id=session_obj.workspace_id)
            if pred and 'risk_probability' in pred:
                risk_probability = float(pred['risk_probability'])
                risk_class = pred.get('risk_level')
                prediction_meta = pred.get('prediction') or {}
                assessment_model_version = str(prediction_meta.get('model_version') or assessment_model_version)
                if prediction_meta.get('calibrated'):
                    assessment_calibration_version = str(prediction_meta.get('calibration_method') or 'calibrated')
                ft = pred.get('features', {})
                lgb_forecast_7d = float(ft.get('forecast_7d', 0.0))
                lgb_forecast_14d = float(ft.get('forecast_14d', 0.0))
                lgb_forecast_30d = float(ft.get('forecast_30d', 0.0))
        except Exception as e:
            logger.debug("HybridModelPipeline evaluation notice for SKU %s: %s", sku_val, e)

        if risk_probability is None or risk_class is None:
            # Deterministic rule-based fallback when no governed model is
            # available. Identical evidence must produce identical scores.
            import math
            dsls_norm = min(365.0, float(dsls)) / 30.0
            vel_norm = min(10.0, float(velocity))
            zr_norm = float(zero_rate)
            adi_norm = min(30.0, float(adi)) / 2.0
            
            # Continuous log-odds computation
            log_odds = -1.2 + (dsls_norm * 0.45) - (vel_norm * 0.85) + (zr_norm * 0.95) + (adi_norm * 0.35)
            
            prob_raw = 1.0 / (1.0 + math.exp(-log_odds))
            prob = round(max(0.03, min(0.97, prob_raw)), 4)
            
            if prob >= 0.80:
                r_class = 'CRITICAL'
            elif prob >= 0.60:
                r_class = 'HIGH_RISK'
            elif prob >= 0.35:
                r_class = 'MEDIUM_RISK'
            else:
                r_class = 'LOW_RISK'
        else:
            prob = round(risk_probability, 4)
            r_class = risk_class

        score = round(prob * 100.0, 1)

        # LightGBM Demand Forecaster model lookup if not populated yet
        if lgb_forecast_7d == 0.0:
            lgb_forecast_7d = round(velocity * 7.0, 2)
            lgb_forecast_14d = round(velocity * 14.0, 2)
            lgb_forecast_30d = round(velocity * 30.0, 2)

        # Determine diagnostic signals
        primary_signals = []
        supporting_signals = []
        if velocity < 0.5:
            primary_signals.append('LOW_SALES_VELOCITY')
        if dsls > 90:
            primary_signals.append('POSSIBLE_OBSOLESCENCE')
        if adi > 1.32 and zero_rate > 0.5:
            primary_signals.append('LUMPY_DEMAND')
        if not primary_signals:
            primary_signals.append('LOW_SALES_VELOCITY')
        if velocity < 0.5 and total_orders > 5:
            supporting_signals.append('PROMO_ASSOCIATED_LOW_VELOCITY')

        inventory_readiness = InventoryReadinessGate.evaluate(
            workspace_id=session_obj.workspace_id,
            canonical_sku=item['sku'],
            as_of=ref_date.date(),
        )
        observed_stock = inventory_readiness.available_quantity if inventory_readiness.ready else None
        observed_cost = inventory_readiness.unit_cost if inventory_readiness.ready else None
        observed_price = inventory_readiness.unit_selling_price if inventory_readiness.ready else None

        assessments_to_create.append(
            SlowMovingRiskAssessment(
                session=session_obj,
                sku=item['sku'],
                canonical_sku_id=item['canonical_sku_id'],
                product_name=item['product_name'],
                category=item['category'],
                risk_class=r_class,
                risk_probability=prob,
                risk_score=score,
                primary_signals=primary_signals,
                supporting_signals=supporting_signals,
                diagnostics=list(set(primary_signals + supporting_signals)),
                evidence={
                    'sales_velocity_90d': velocity,
                    'sales_velocity_30d': ev.get('velocity_30d', 0),
                    'zero_rate_90d': zero_rate,
                    'dsls': dsls,
                    'adi': adi,
                    'cv2': 0.58,
                    'sold_90d': ev.get('sold_90d', 0),
                    'sold_30d': ev.get('sold_30d', 0),
                    'total_orders': total_orders,
                    'stock_quantity': observed_stock,
                    'unit_cost': observed_cost,
                    'unit_price': observed_price,
                    'capital_exposure_vnd': inventory_readiness.capital_exposure,
                    'inventory_readiness': {
                        'status': inventory_readiness.status,
                        'reasons': list(inventory_readiness.reasons),
                        'record_date': inventory_readiness.record_date.isoformat() if inventory_readiness.record_date else None,
                        'lifecycle_status': inventory_readiness.lifecycle_status,
                        'warehouse_count': inventory_readiness.warehouse_count,
                    },
                    'forecast_7d': lgb_forecast_7d,
                    'forecast_14d': lgb_forecast_14d,
                    'forecast_30d': lgb_forecast_30d,
                    'forecast_trend': 'DECREASING' if velocity < 0.2 else 'STABLE',
                    'forecast_model': 'historical_velocity_projection',
                },
                model_version=assessment_model_version,
                calibration_version=assessment_calibration_version,
                dataset_version='v1.3',
                assessment_status='COMPLETE'
            )
        )

    if assessments_to_create:
        SlowMovingRiskAssessment.objects.filter(session=session_obj).delete()
        SlowMovingRiskAssessment.objects.bulk_create(assessments_to_create, ignore_conflicts=True)
        try:
            from supplyforge.services.auto_decision_generator import AutoDecisionGeneratorService
            AutoDecisionGeneratorService.generate_decisions_from_assessments(
                workspace_id=session_obj.workspace_id,
            )
        except Exception as e:
            logger.error("Auto decision generator failed: %s", e)


def _auto_populate_assessments_from_products(session_id=None):
    """Compatibility entry point for CSV imports outside the worker pipeline.

    Published DatasetVersion records use the operational run service.  The
    legacy branch is intentionally retained for research fixtures that have no
    lake version; it cannot be selected by the default merchant dashboard.
    """
    session = IngestionSession.objects.filter(id=session_id).first() if session_id else None
    if not session:
        logger.warning('Skipping risk auto-population without an explicit ingestion session.')
        return None
    version = DatasetVersion.objects.filter(ingestion_session=session).first()
    if version and version.status == DatasetVersion.STATUS_ACTIVE:
        from supplyforge.services.slow_moving_run_service import SlowMovingRunService

        return SlowMovingRunService.run_csv_for_dataset(version)
    return _legacy_auto_populate_assessments_from_products(session_id)


@api_view(['GET'])
def get_global_risk_summary(request):
    """
    GET /api/v1/risk/summary
    Aggregated count summary across all 4 risk classes.
    """
    session_id = request.query_params.get('session_id')
    qs, source_run = _operational_csv_queryset(request, session_id)
    if source_run:
        qs = qs.filter(assessment_status='COMPLETE')

    total_skus = qs.count()
    counts = qs.values('risk_class').annotate(total=Count('id'))
    counts_map = {item['risk_class'].upper(): item['total'] for item in counts}

    update_high_risk_sku_gauge(
        critical_count=counts_map.get('CRITICAL', 0),
        high_count=counts_map.get('HIGH_RISK', 0),
        medium_count=counts_map.get('MEDIUM_RISK', 0),
        low_count=counts_map.get('LOW_RISK', 0)
    )

    return Response({
        'total_skus': total_skus,
        'critical': counts_map.get('CRITICAL', 0),
        'high_risk': counts_map.get('HIGH_RISK', 0),
        'medium_risk': counts_map.get('MEDIUM_RISK', 0),
        'low_risk': counts_map.get('LOW_RISK', 0),
        'source': _source_payload(source_run),
    })


def _alert_queryset_for_request(request):
    queryset = SlowMovingAlertState.objects.select_related('last_assessment_run')
    if getattr(request, 'tenant_context_validated', False) and getattr(request, 'workspace_id', None):
        return queryset.filter(workspace_id=request.workspace_id)
    return queryset.none() if getattr(settings, 'IS_DEPLOYED', False) else queryset


def _serialize_alert_state(alert):
    labels = {
        SlowMovingAlertState.STATUS_CANDIDATE: 'Chờ xác nhận',
        SlowMovingAlertState.STATUS_OPEN: 'Cần xem',
        SlowMovingAlertState.STATUS_ACKNOWLEDGED: 'Đã tiếp nhận',
        SlowMovingAlertState.STATUS_SNOOZED: 'Tạm ẩn',
        SlowMovingAlertState.STATUS_RESOLVED: 'Đã xử lý',
        SlowMovingAlertState.STATUS_DATA_BLOCKED: 'Cần bổ sung dữ liệu',
    }
    return {
        'id': str(alert.id),
        'canonical_sku': alert.canonical_sku,
        'status': alert.status,
        'consecutive_eligible_runs': alert.consecutive_eligible_runs,
        'first_detected_at': alert.first_detected_at.isoformat(),
        'last_detected_at': alert.last_detected_at.isoformat(),
        'acknowledged_at': alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        'snoozed_until': alert.snoozed_until.isoformat() if alert.snoozed_until else None,
        'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
        'resolution_note': alert.resolution_note,
        'owner_label': alert.owner_label,
        'next_review_at': alert.next_review_at.isoformat() if alert.next_review_at else None,
        'status_label': labels.get(alert.status, 'Cần kiểm tra'),
        'last_run_id': str(alert.last_assessment_run_id) if alert.last_assessment_run_id else None,
    }


def _serialize_alert_passport(passport):
    if not passport:
        return None
    return {
        'id': str(passport.id),
        'event_type': passport.event_type,
        'title': passport.title,
        'summary': passport.summary,
        'safe_next_step': passport.safe_next_step,
        'recheck_condition': passport.recheck_condition,
        'source_scope_fingerprint': passport.source_scope_fingerprint,
        'previous_facts': passport.previous_facts_json,
        'current_facts': passport.current_facts_json,
        # Labels are already merchant language. Deliberately hide raw codes.
        'changes': [
            {
                key: change.get(key)
                for key in ('label', 'before', 'after', 'material')
                if key in change
            }
            for change in (passport.changed_facts_json or [])
        ],
        'created_at': passport.created_at.isoformat(),
    }


@api_view(['GET'])
def list_slow_moving_alerts(request):
    """List lifecycle states, not raw heuristic rows, for an action queue."""
    try:
        source_key = _source_key_for_request(request.query_params.get('source'))
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    statuses = [value.strip().upper() for value in str(request.query_params.get('status') or '').split(',') if value.strip()]
    queryset = _alert_queryset_for_request(request).filter(source_key=source_key)
    if statuses:
        queryset = queryset.filter(status__in=statuses)
    else:
        queryset = queryset.exclude(status=SlowMovingAlertState.STATUS_RESOLVED)
    alerts = list(queryset.order_by('-last_detected_at')[:200])
    passports = {}
    for passport in SlowMovingAlertPassport.objects.filter(
        alert_state_id__in=[alert.id for alert in alerts],
    ).order_by('alert_state_id', '-created_at'):
        passports.setdefault(str(passport.alert_state_id), passport)
    return Response({
        'alerts': [
            {
                **_serialize_alert_state(alert),
                'latest_passport': _serialize_alert_passport(passports.get(str(alert.id))),
            }
            for alert in alerts
        ],
    })


@api_view(['GET'])
def get_slow_moving_quality(request):
    """Return outcome-based quality gates for the selected operational scope."""
    requested_source = str(request.query_params.get('source') or 'CSV')
    if requested_source.upper() == SlowMovingAssessmentRun.SOURCE_CSV:
        source_key = SlowMovingAssessmentRun.SOURCE_CSV
    elif requested_source.upper().startswith('ODOO:'):
        source_key = f"ODOO:{requested_source.split(':', 1)[1].lower()}"
    else:
        return Response({'error': 'source phải là CSV hoặc ODOO:<connection-id>.'}, status=status.HTTP_400_BAD_REQUEST)
    workspace_id = getattr(request, 'workspace_id', None) if getattr(request, 'tenant_context_validated', False) else None
    if workspace_id is None and getattr(settings, 'IS_DEPLOYED', False):
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    if workspace_id is None:
        run = SlowMovingAssessmentRun.objects.filter(
            source_key=source_key,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
        ).order_by('-completed_at').first()
        if not run:
            return Response({
                'state': 'INSUFFICIENT_EVIDENCE',
                'reason': 'NO_CURRENT_OPERATIONAL_RUN',
                'source_key': source_key,
            })
        workspace_id = run.workspace_id
    from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService

    return Response(SlowMovingQualityMonitoringService.report(
        workspace_id=int(workspace_id), source_key=source_key,
    ))


def _source_key_for_request(value: str | None) -> str:
    requested = str(value or 'CSV').strip()
    if requested.upper() == SlowMovingAssessmentRun.SOURCE_CSV:
        return SlowMovingAssessmentRun.SOURCE_CSV
    if requested.upper().startswith('ODOO:'):
        return f"ODOO:{requested.split(':', 1)[1].lower()}"
    raise ValueError('source phải là CSV hoặc ODOO:<connection-id>.')


def _request_workspace_id(request):
    workspace_id = getattr(request, 'workspace_id', None) if getattr(request, 'tenant_context_validated', False) else None
    if workspace_id is None and not getattr(settings, 'IS_DEPLOYED', False):
        run = SlowMovingAssessmentRun.objects.filter(
            status=SlowMovingAssessmentRun.STATUS_COMPLETED, is_current=True,
        ).order_by('-completed_at').first()
        workspace_id = run.workspace_id if run else None
    return int(workspace_id) if workspace_id is not None else None


@api_view(['GET'])
def get_slow_moving_alert_health(request):
    """Operational health, intentionally separate from score/outcome claims."""
    try:
        source_key = _source_key_for_request(request.query_params.get('source'))
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    workspace_id = _request_workspace_id(request)
    if workspace_id is None:
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    from supplyforge.services.slow_moving_alert_operations import SlowMovingAlertHealthService

    return Response(SlowMovingAlertHealthService.report(
        workspace_id=workspace_id, source_key=source_key,
    ))


@api_view(['GET'])
def get_slow_moving_alert_passport(request, id):
    try:
        alert = _alert_queryset_for_request(request).get(id=id)
    except (SlowMovingAlertState.DoesNotExist, ValueError):
        return Response({'error': 'Không tìm thấy cảnh báo bán chậm.'}, status=status.HTTP_404_NOT_FOUND)
    passport = alert.passports.order_by('-created_at').first()
    if not passport:
        return Response({
            'passport': None,
            'message': 'Cảnh báo này chưa có phiếu giải thích từ lần đánh giá trước đó.',
        })
    return Response({'passport': _serialize_alert_passport(passport)})


@api_view(['GET', 'POST'])
def slow_moving_catalog_contexts(request):
    """List or append a scoped merchant catalog declaration.

    Context is never inferred from a feedback note; a merchant explicitly
    confirms it here (or through a future verified Odoo mapping flow).
    """
    workspace_id = _request_workspace_id(request)
    if workspace_id is None:
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    if request.method == 'GET':
        canonical_sku = str(request.query_params.get('canonical_sku') or '').strip().upper()
        query = SlowMovingSkuContext.objects.filter(workspace_id=workspace_id)
        if canonical_sku:
            query = query.filter(canonical_sku=canonical_sku)
        rows = query.order_by('-effective_from', '-created_at')[:200]
        availability_labels = dict(SlowMovingSkuContext.AVAILABILITY_CHOICES)
        role_labels = dict(SlowMovingSkuContext.ROLE_CHOICES)
        now = timezone.now()
        return Response({'contexts': [{
            'id': str(row.id), 'canonical_sku': row.canonical_sku,
            'source': row.source_key or 'Mọi nguồn', 'warehouse_code': row.warehouse_code or 'Mọi kho',
            'channel': row.channel or 'Mọi kênh',
            # Keep codes for API clients but always supply the merchant copy
            # a UI should render.
            'availability': row.availability,
            'availability_label': availability_labels.get(row.availability, 'Cần xác nhận'),
            'catalog_role': row.catalog_role,
            'catalog_role_label': role_labels.get(row.catalog_role, 'Cần xác nhận'),
            'related_canonical_sku': row.related_canonical_sku or None,
            'conversion_quantity': str(row.conversion_quantity) if row.conversion_quantity is not None else None,
            'effective_from': row.effective_from.isoformat(),
            'effective_to': row.effective_to.isoformat() if row.effective_to else None,
            'status_label': (
                'Cần xác nhận lại' if row.effective_to and row.effective_to < now else 'Đang có hiệu lực'
            ),
            'evidence_reference': row.evidence_reference or None,
            'declared_by': row.declared_by or None,
        } for row in rows]})

    canonical_sku = str(request.data.get('canonical_sku') or '').strip().upper()
    try:
        source_key = _source_key_for_request(request.data.get('source'))
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    availability = str(request.data.get('availability') or '').upper().strip()
    catalog_role = str(request.data.get('catalog_role') or SlowMovingSkuContext.ROLE_STANDALONE).upper().strip()
    if not canonical_sku:
        return Response({'error': 'Cần chọn mã sản phẩm.'}, status=status.HTTP_400_BAD_REQUEST)
    if availability not in {value for value, _ in SlowMovingSkuContext.AVAILABILITY_CHOICES}:
        return Response({'error': 'Tình trạng hàng không hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    if catalog_role not in {value for value, _ in SlowMovingSkuContext.ROLE_CHOICES}:
        return Response({'error': 'Loại sản phẩm không hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    evidence_reference = str(request.data.get('evidence_reference') or '').strip()[:512]
    if not evidence_reference:
        return Response({'error': 'Cần thêm lý do hoặc liên kết bằng chứng trước khi xác nhận tình trạng hàng này.'}, status=status.HTTP_400_BAD_REQUEST)
    effective_from = parse_datetime(str(request.data.get('effective_from') or ''))
    if effective_from is None:
        current_run = SlowMovingAssessmentRun.objects.filter(
            workspace_id=workspace_id, source_key=source_key,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED, is_current=True,
        ).order_by('-completed_at').first()
        # A declaration should affect the next assessment even when the source
        # data is historical. The declaration's created_at still records when
        # the merchant made this choice.
        effective_from = current_run.analysis_as_of if current_run else timezone.now()
    effective_to = parse_datetime(str(request.data.get('effective_to') or '')) if request.data.get('effective_to') else None
    if timezone.is_naive(effective_from):
        effective_from = timezone.make_aware(effective_from, timezone.get_current_timezone())
    if effective_to and timezone.is_naive(effective_to):
        effective_to = timezone.make_aware(effective_to, timezone.get_current_timezone())
    if effective_to and effective_to <= effective_from:
        return Response({'error': 'Thời điểm kết thúc phải sau thời điểm bắt đầu.'}, status=status.HTTP_400_BAD_REQUEST)
    if effective_to is None:
        return Response({'error': 'Cần chọn ngày hết hiệu lực để hệ thống yêu cầu xác nhận lại đúng lúc.'}, status=status.HTTP_400_BAD_REQUEST)
    conversion = request.data.get('conversion_quantity')
    if conversion in ('', None):
        conversion = None
    else:
        try:
            conversion = float(conversion)
        except (TypeError, ValueError):
            return Response({'error': 'Quy tắc quy đổi phải là số hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    related_canonical_sku = str(request.data.get('related_canonical_sku') or '').strip().upper()[:255]
    requires_relation = catalog_role in {
        SlowMovingSkuContext.ROLE_BUNDLE,
        SlowMovingSkuContext.ROLE_COMPONENT,
        SlowMovingSkuContext.ROLE_REPLACEMENT,
    }
    if requires_relation and (not related_canonical_sku or conversion is None or conversion <= 0):
        return Response({
            'error': 'Cần chọn SKU liên quan và quy tắc quy đổi lớn hơn 0 trước khi xác nhận quan hệ sản phẩm.',
        }, status=status.HTTP_400_BAD_REQUEST)
    context = SlowMovingSkuContext.objects.create(
        workspace_id=workspace_id,
        canonical_sku=canonical_sku,
        source_key=source_key,
        warehouse_code=str(request.data.get('warehouse_code') or '').strip()[:128],
        channel=str(request.data.get('channel') or '').strip()[:128],
        availability=availability,
        catalog_role=catalog_role,
        related_canonical_sku=related_canonical_sku,
        conversion_quantity=conversion,
        effective_from=effective_from,
        effective_to=effective_to,
        evidence_reference=evidence_reference,
        provenance_json={'source': 'merchant-api'},
        declared_by=str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))[:128],
    )
    return Response({
        'context_id': str(context.id),
        'message': 'Đã lưu tình trạng hàng trong thời hạn đã chọn. Lần phân tích kế tiếp sẽ dùng thông tin này.',
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def list_slow_moving_remediations(request):
    workspace_id = _request_workspace_id(request)
    if workspace_id is None:
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    status_filter = str(request.query_params.get('status') or '').upper().strip()
    query = SlowMovingFeedbackRemediation.objects.filter(workspace_id=workspace_id).select_related('alert_state')
    requested_source = str(request.query_params.get('source') or '').strip()
    if requested_source:
        try:
            source_key = _source_key_for_request(requested_source)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        query = query.filter(alert_state__source_key=source_key)
    if status_filter:
        query = query.filter(status=status_filter)
    rows = query.order_by('due_at', '-created_at')[:200]
    type_labels = dict(SlowMovingFeedbackRemediation.TYPE_CHOICES)
    status_labels = dict(SlowMovingFeedbackRemediation.STATUS_CHOICES)
    return Response({'remediations': [{
        'id': str(row.id), 'sku': row.alert_state.canonical_sku, 'title': row.title,
        'detail': row.detail, 'type': row.remediation_type, 'status': row.status,
        'type_label': type_labels.get(row.remediation_type, 'Cần xử lý'),
        'status_label': status_labels.get(row.status, 'Cần xử lý'),
        'owner_label': row.owner_label or None,
        'due_at': row.due_at.isoformat() if row.due_at else None,
        'evidence_reference': row.evidence_reference or None,
        'outcome_note': row.outcome_note or None,
    } for row in rows]})


@api_view(['POST'])
def update_slow_moving_remediation(request, id):
    workspace_id = _request_workspace_id(request)
    query = SlowMovingFeedbackRemediation.objects
    if workspace_id is not None:
        query = query.filter(workspace_id=workspace_id)
    elif getattr(settings, 'IS_DEPLOYED', False):
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        remediation = query.get(id=id)
    except (SlowMovingFeedbackRemediation.DoesNotExist, ValueError):
        return Response({'error': 'Không tìm thấy việc cần xử lý.'}, status=status.HTTP_404_NOT_FOUND)
    action = str(request.data.get('action') or '').upper().strip()
    owner_label = str(request.data.get('owner_label') or '').strip()[:128]
    if action == 'ASSIGN':
        if not owner_label:
            return Response({'error': 'Cần giao người phụ trách.'}, status=status.HTTP_400_BAD_REQUEST)
        remediation.owner_label = owner_label
        remediation.save(update_fields=['owner_label', 'updated_at'])
    elif action == 'START':
        remediation.status = SlowMovingFeedbackRemediation.STATUS_IN_PROGRESS
        if owner_label:
            remediation.owner_label = owner_label
        remediation.save(update_fields=['status', 'owner_label', 'updated_at'])
    elif action in {'COMPLETE', 'CANCEL'}:
        from supplyforge.services.slow_moving_alert_operations import SlowMovingFeedbackRemediationService
        try:
            remediation = SlowMovingFeedbackRemediationService.complete(
                remediation,
                actor=str(getattr(request, 'user_email', '') or getattr(request, 'user_id', '')),
                outcome_note=str(request.data.get('outcome_note') or ''),
                evidence_reference=str(request.data.get('evidence_reference') or ''),
                cancelled=action == 'CANCEL',
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    else:
        return Response({'error': 'action phải là ASSIGN, START, COMPLETE hoặc CANCEL.'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'remediation': {'id': str(remediation.id), 'status': remediation.status, 'owner_label': remediation.owner_label or None}})


@api_view(['POST'])
def record_slow_moving_disposition(request):
    """Record a lineaged confounder without rewriting a historical outcome."""
    source_key = str(request.data.get('source') or 'CSV')
    workspace_id = getattr(request, 'workspace_id', None) if getattr(request, 'tenant_context_validated', False) else None
    runs = SlowMovingAssessmentRun.objects.filter(
        source_key=source_key,
        status=SlowMovingAssessmentRun.STATUS_COMPLETED,
        is_current=True,
    )
    if workspace_id is not None:
        runs = runs.filter(workspace_id=workspace_id)
    elif getattr(settings, 'IS_DEPLOYED', False):
        return Response({'error': 'Yêu cầu cần workspace đã xác thực.'}, status=status.HTTP_401_UNAUTHORIZED)
    run = runs.order_by('-completed_at').first()
    if not run:
        return Response({'error': 'Không có lần đánh giá hiện hành cho nguồn đã chọn.'}, status=status.HTTP_409_CONFLICT)
    occurred_at = parse_datetime(str(request.data.get('occurred_at') or ''))
    if occurred_at is None:
        return Response({'error': 'occurred_at phải là thời điểm ISO-8601 hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    from supplyforge.services.slow_moving_dispositions import (
        SlowMovingDispositionError, SlowMovingDispositionService,
    )

    try:
        event = SlowMovingDispositionService.record(
            run=run,
            canonical_sku=request.data.get('canonical_sku'),
            event_type=request.data.get('event_type'),
            occurred_at=occurred_at,
            evidence_reference=request.data.get('evidence_reference'),
            provenance={
                'source': 'merchant-api',
                'submitted_by': str(getattr(getattr(request, 'user', None), 'id', '') or ''),
            },
        )
    except SlowMovingDispositionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({
        'id': str(event.id), 'canonical_sku': event.canonical_sku,
        'event_type': event.event_type, 'occurred_at': event.occurred_at.isoformat(),
        'scope': 'Sự kiện được ghi nhận để loại outcome bị nhiễu khỏi đánh giá dự báo; không dùng để khẳng định hiệu quả nhân quả.',
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def update_slow_moving_alert_state(request, id):
    """Apply an explicit merchant lifecycle transition with an audit payload."""
    try:
        alert = _alert_queryset_for_request(request).get(id=id)
    except (SlowMovingAlertState.DoesNotExist, ValueError):
        return Response({'error': 'Không tìm thấy cảnh báo bán chậm.'}, status=status.HTTP_404_NOT_FOUND)
    action = str(request.data.get('action') or '').upper()
    note = str(request.data.get('note') or '').strip()[:500]
    requested_reason = str(request.data.get('feedback_reason') or '').upper().strip()
    owner_label = str(request.data.get('owner_label') or '').strip()[:128]
    now = timezone.now()
    from supplyforge.services.slow_moving_alert_trust import SlowMovingAlertTrustService

    attention_event = None
    if action == 'ACKNOWLEDGE':
        alert.status = SlowMovingAlertState.STATUS_ACKNOWLEDGED
        alert.acknowledged_at = now
    elif action == 'SNOOZE':
        try:
            days = max(1, min(60, int(request.data.get('days', 7))))
        except (TypeError, ValueError):
            return Response({'error': 'Số ngày tạm ẩn phải là số nguyên từ 1 đến 60.'}, status=status.HTTP_400_BAD_REQUEST)
        alert.status = SlowMovingAlertState.STATUS_SNOOZED
        alert.snoozed_until = now + timedelta(days=days)
        alert.next_review_at = alert.snoozed_until
    elif action == 'RESOLVE':
        if not note:
            return Response({'error': 'Cần nêu lý do trước khi đóng cảnh báo.'}, status=status.HTTP_400_BAD_REQUEST)
        alert.status = SlowMovingAlertState.STATUS_RESOLVED
        alert.resolved_at = now
        alert.resolution_note = note
        alert.consecutive_eligible_runs = 0
        alert.next_review_at = None
    elif action == 'REOPEN':
        # Explicit merchant reopening is allowed, but is audit-visible and
        # does not pretend a model discovered a new fact.
        alert.status = SlowMovingAlertState.STATUS_OPEN
        alert.resolved_at = None
        alert.resolution_note = ''
        alert.next_review_at = SlowMovingAlertTrustService.next_review(now=now)
        attention_event = SlowMovingAlertAttentionEvent.TYPE_REOPENED
    elif action == 'ASSIGN':
        if not owner_label:
            return Response({'error': 'Cần giao người phụ trách trước khi lưu.'}, status=status.HTTP_400_BAD_REQUEST)
        alert.owner_label = owner_label
        alert.next_review_at = alert.next_review_at or SlowMovingAlertTrustService.next_review(now=now)
        alert.save(update_fields=['owner_label', 'next_review_at', 'updated_at'])
        return Response({'alert': _serialize_alert_state(alert)})
    else:
        return Response({'error': 'action phải là ACKNOWLEDGE, SNOOZE, RESOLVE, REOPEN hoặc ASSIGN.'}, status=status.HTTP_400_BAD_REQUEST)
    default_reasons = {
        'ACKNOWLEDGE': SlowMovingAlertFeedback.REASON_ACCEPTED,
        'SNOOZE': SlowMovingAlertFeedback.REASON_SNOOZED,
        'RESOLVE': SlowMovingAlertFeedback.REASON_RESOLVED,
        'REOPEN': SlowMovingAlertFeedback.REASON_ACCEPTED,
    }
    valid_reasons = {value for value, _ in SlowMovingAlertFeedback.REASON_CHOICES}
    feedback_reason = requested_reason or default_reasons[action]
    if feedback_reason not in valid_reasons:
        return Response({'error': 'Lý do phản hồi không hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    submitted_by = str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))[:128]
    feedback = SlowMovingAlertFeedback.objects.create(
        workspace_id=alert.workspace_id,
        alert_state=alert,
        action=action,
        reason=feedback_reason,
        note=note,
        evidence_reference=str(request.data.get('evidence_reference') or '').strip()[:512],
        submitted_by=submitted_by,
    )
    # Retain only a compatibility summary for older clients. Quality and audit
    # consume the append-only event above, never this mutable JSON value.
    alert.feedback = {
        **(alert.feedback or {}),
        'last_action': action,
        'last_action_at': now.isoformat(),
        'last_action_by': submitted_by,
    }
    if not alert.next_review_at and alert.status != SlowMovingAlertState.STATUS_RESOLVED:
        alert.next_review_at = SlowMovingAlertTrustService.next_review(now=now)
    alert.save()
    event_type = attention_event or {
        'ACKNOWLEDGE': SlowMovingAlertAttentionEvent.TYPE_ACKNOWLEDGED,
        'SNOOZE': SlowMovingAlertAttentionEvent.TYPE_SNOOZED,
        'RESOLVE': SlowMovingAlertAttentionEvent.TYPE_RESOLVED,
    }[action]
    SlowMovingAlertAttentionEvent.objects.create(
        workspace_id=alert.workspace_id,
        alert_state=alert,
        assessment_run=alert.last_assessment_run,
        event_type=event_type,
        reason_codes=[feedback_reason],
        note=note,
        actor=submitted_by,
        policy_version=(alert.last_assessment_run.policy_version if alert.last_assessment_run_id else ''),
    )
    from supplyforge.services.slow_moving_alert_operations import SlowMovingFeedbackRemediationService
    SlowMovingFeedbackRemediationService.create_from_feedback(feedback, owner_label=alert.owner_label)
    return Response({'alert': _serialize_alert_state(alert)})
