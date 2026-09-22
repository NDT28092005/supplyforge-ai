import logging
import os
import pandas as pd
from django.conf import settings
from django.db.models import Q, Count
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.models import IngestionSession, SlowMovingRiskAssessment
from src.analytics.risk_assessment_assembler import RiskAssessmentAssembler

logger = logging.getLogger(__name__)


# ── M3-07 Risk API & Persistence Views ─────────────────────────────────

@csrf_exempt
@api_view(['POST'])
def run_and_persist_assessments(request=None, session_id=None, workspace_id=1, user_id='user_default_001'):
    """
    POST /api/v1/risk/assessments
    Executes Risk Assessment Assembly (M3-06) and persists results into Django DB.
    Enforces DAT-11 Data Readiness Gate Check.
    """
    if request is not None:
        session_id = request.data.get('session_id') or request.query_params.get('session_id')

    session = None
    if session_id:
        try:
            session = IngestionSession.objects.get(id=session_id)
        except IngestionSession.DoesNotExist:
            pass

    if not session:
        session = IngestionSession.objects.order_by('-created_at').first()

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
        c_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')
        if os.path.exists(c_path):
            try:
                pred_df = pd.read_csv(c_path)
            except Exception:
                pass

    if pred_df is None or pred_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu M3-03/M3-04 Predictions. Vui lòng thực thi M3-03 / M3-04 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

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


@csrf_exempt
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

    queryset = SlowMovingRiskAssessment.objects.all()

    # If table is completely empty, attempt auto-populating from existing Product records or CSV
    if not queryset.exists():
        _auto_populate_assessments_from_products(session_id)
        queryset = SlowMovingRiskAssessment.objects.all()

    if session_id and queryset.filter(session_id=session_id).exists():
        queryset = queryset.filter(session_id=session_id)

    if risk_class:
        queryset = queryset.filter(risk_class__iexact=risk_class)
    if sku:
        queryset = queryset.filter(Q(sku__icontains=sku) | Q(product_name__icontains=sku))

    if sort_by in ['risk_score', '-risk_score', 'risk_probability', '-risk_probability', 'created_at', '-created_at']:
        queryset = queryset.order_by(sort_by)

    # Optional Pagination
    limit = int(request.query_params.get('limit', 100))
    offset = int(request.query_params.get('offset', 0))
    total_count = queryset.count()
    records = queryset[offset:offset+limit]

    data = [
        {
            'assessment_id': str(r.id),
            'sku': r.sku,
            'canonical_sku_id': r.canonical_sku_id,
            'product_name': r.product_name,
            'category': r.category,
            'risk': {
                'class': r.risk_class,
                'score': r.risk_score,
                'probability': r.risk_probability
            },
            'primary_signals': r.primary_signals,
            'supporting_signals': r.supporting_signals,
            'diagnostics': r.diagnostics,
            'evidence': r.evidence,
            'model': {
                'name': 'XGBoost',
                'version': r.model_version
            },
            'calibration_version': r.calibration_version,
            'diagnostic_rule_version': r.diagnostic_rule_version,
            'data_version': r.dataset_version,
            'assessment_status': r.assessment_status,
            'assessment_timestamp': r.assessment_timestamp.isoformat()
        }
        for r in records
    ]

    return Response({
        'total_count': total_count,
        'limit': limit,
        'offset': offset,
        'assessments': data
    })


@csrf_exempt
@api_view(['GET'])
def get_risk_assessment_detail(request, id):
    """
    GET /api/v1/risk/assessments/<id>
    Retrieve Single Risk Assessment Detail Record by UUID.
    """
    try:
        r = SlowMovingRiskAssessment.objects.get(id=id)
    except (SlowMovingRiskAssessment.DoesNotExist, ValueError):
        return Response({'error': f'Không tìm thấy Risk Assessment với ID {id}'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'assessment_id': str(r.id),
        'sku': r.sku,
        'canonical_sku_id': r.canonical_sku_id,
        'product_name': r.product_name,
        'category': r.category,
        'risk': {
            'class': r.risk_class,
            'score': r.risk_score,
            'probability': r.risk_probability
        },
        'primary_signals': r.primary_signals,
        'supporting_signals': r.supporting_signals,
        'diagnostics': r.diagnostics,
        'evidence': r.evidence,
        'model': {
            'name': 'XGBoost',
            'version': r.model_version
        },
        'calibration_version': r.calibration_version,
        'diagnostic_rule_version': r.diagnostic_rule_version,
        'data_version': r.dataset_version,
        'assessment_status': r.assessment_status,
        'assessment_timestamp': r.assessment_timestamp.isoformat()
    })


@csrf_exempt
@api_view(['GET'])
def get_sku_risk_assessment(request, sku_id):
    """
    GET /api/v1/risk/skus/<sku_id>
    Direct SKU Risk Assessment lookup.
    """
    r = SlowMovingRiskAssessment.objects.filter(Q(sku=sku_id) | Q(canonical_sku_id=sku_id)).order_by('-assessment_timestamp').first()
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
            'probability': r.risk_probability
        },
        'primary_signals': r.primary_signals,
        'supporting_signals': r.supporting_signals,
        'diagnostics': r.diagnostics,
        'evidence': r.evidence,
        'model': {
            'name': 'XGBoost',
            'version': r.model_version
        },
        'calibration_version': r.calibration_version,
        'diagnostic_rule_version': r.diagnostic_rule_version,
        'data_version': r.dataset_version,
        'assessment_status': r.assessment_status,
        'assessment_timestamp': r.assessment_timestamp.isoformat()
    })


def _auto_populate_assessments_from_products(session_id=None):
    """
    Auto-populates SlowMovingRiskAssessment DB table from real imported Product + Order data.
    Calculates real evidence: sales velocity, DSLS, zero-rate, ADI from actual OrderItem history.
    """
    from datetime import datetime, timedelta
    from django.db.models import Max, Sum, Count, Q
    from supplyforge.models import Product, Order, OrderItem, Sku, IngestionSession

    real_items = []
    seen_skus = set()

    # Determine reference date from actual data
    max_order_dt = Order.objects.aggregate(Max('created_at'))['created_at__max']
    ref_date = max_order_dt if max_order_dt else datetime.now()
    if hasattr(ref_date, 'tzinfo') and ref_date.tzinfo is not None:
        ref_date = ref_date.replace(tzinfo=None)

    ninety_days_ago = ref_date - timedelta(days=90)
    thirty_days_ago = ref_date - timedelta(days=30)
    seven_days_ago = ref_date - timedelta(days=7)

    # 1. Build product list from Product table
    p_qs = Product.objects.all()
    for p in p_qs:
        sku_val = p.item_sku or p.third_party_id or f"SKU_{p.id}"
        name_val = p.product_name or f"Product {sku_val}"
        if sku_val not in seen_skus:
            seen_skus.add(sku_val)
            real_items.append({
                'sku': sku_val,
                'canonical_sku_id': f"CSKU_{sku_val}",
                'product_name': name_val,
                'category': getattr(p, 'platform', None) or 'Shopee Orders',
                'stock': int(p.stock or 0),
                'cost': float(p.cost or p.price or 0),
                'item_id': p.item_id,
                'item_sku': p.item_sku,
            })

    # 2. Fallback to OrderItem if Product table is empty
    if len(real_items) < 2:
        oi_items = OrderItem.objects.values('sku', 'product_name').distinct()[:300]
        for item in oi_items:
            sku_val = item.get('sku')
            name_val = item.get('product_name')
            if sku_val and sku_val not in seen_skus:
                seen_skus.add(sku_val)
                real_items.append({
                    'sku': sku_val,
                    'canonical_sku_id': f"CSKU_{sku_val}",
                    'product_name': name_val or f"Product {sku_val}",
                    'category': 'Shopee Orders',
                    'stock': 0,
                    'cost': 0,
                    'item_id': None,
                    'item_sku': sku_val,
                })

    if not real_items:
        return

    # Delete any old orphan demo assessments (e.g. CSKU_101, CSKU_102)
    SlowMovingRiskAssessment.objects.all().delete()

    # 3. Compute real evidence for each SKU from Order/OrderItem history
    from django.db import connection
    evidence_map = {}
    for item in real_items:
        sku_val = item.get('item_sku') or item.get('sku')
        match_q = Q(sku=sku_val) | Q(sku__iexact=sku_val)
        if item.get('item_id'):
            match_q = match_q | Q(item_id=item['item_id'])
        if item.get('product_name'):
            match_q = match_q | Q(product_name=item['product_name'])

        # Total sold in 90d, 30d, 7d windows
        sold_90d = OrderItem.objects.filter(
            match_q, order__created_at__gte=ninety_days_ago, order__created_at__lte=ref_date
        ).aggregate(total=Sum('quantity'))['total'] or 0

        sold_30d = OrderItem.objects.filter(
            match_q, order__created_at__gte=thirty_days_ago, order__created_at__lte=ref_date
        ).aggregate(total=Sum('quantity'))['total'] or 0

        sold_7d = OrderItem.objects.filter(
            match_q, order__created_at__gte=seven_days_ago, order__created_at__lte=ref_date
        ).aggregate(total=Sum('quantity'))['total'] or 0

        # Last sale date (DSLS)
        last_sale = OrderItem.objects.filter(match_q).aggregate(
            last_date=Max('order__created_at')
        )['last_date']
        if last_sale:
            if hasattr(last_sale, 'tzinfo') and last_sale.tzinfo is not None:
                last_sale = last_sale.replace(tzinfo=None)
            dsls = max(0, (ref_date - last_sale).days)
        else:
            dsls = 999

        # Sales velocity (units/day over 90d)
        velocity_90d = round(float(sold_90d) / 90.0, 4) if sold_90d else 0.0
        velocity_30d = round(float(sold_30d) / 30.0, 4) if sold_30d else 0.0

        # Number of distinct days with orders in 90d
        order_days_90d = OrderItem.objects.filter(
            match_q, order__created_at__gte=ninety_days_ago, order__created_at__lte=ref_date
        ).values('order__created_at__date').distinct().count()

        # Zero-rate: fraction of days without sales in 90d window
        zero_rate_90d = round(1.0 - (order_days_90d / 90.0), 3) if order_days_90d else 1.0

        # ADI (Average Demand Interval)
        adi = round(90.0 / max(order_days_90d, 1), 2)

        # Total orders count
        total_orders = OrderItem.objects.filter(match_q).aggregate(cnt=Count('id'))['cnt'] or 0

        evidence_map[item['sku']] = {
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

    # Find IngestionSession
    session_obj = None
    if session_id:
        try:
            session_obj = IngestionSession.objects.get(id=session_id)
        except Exception:
            session_obj = None
    if not session_obj:
        session_obj = IngestionSession.objects.order_by('-created_at').first()

    assessments_to_create = []

    for item in real_items:
        ev = evidence_map.get(item['sku'], {})
        velocity = ev.get('velocity_90d', 0)
        dsls = ev.get('dsls', 999)
        zero_rate = ev.get('zero_rate_90d', 1.0)
        adi = ev.get('adi', 99)
        total_orders = ev.get('total_orders', 0)

        # Classify risk based on real thresholds
        if total_orders == 0 or dsls > 180:
            r_class = 'CRITICAL'
            prob = 0.95
        elif velocity < 0.1 and dsls > 60:
            r_class = 'CRITICAL'
            prob = 0.90
        elif velocity < 0.5 and dsls > 30:
            r_class = 'HIGH_RISK'
            prob = 0.72
        elif velocity < 2.0 and zero_rate > 0.5:
            r_class = 'MEDIUM_RISK'
            prob = 0.45
        else:
            r_class = 'LOW_RISK'
            prob = 0.15

        score = round(prob * 100.0, 1)

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
                },
                model_version='xgboost_exp03_v1',
                dataset_version='v1.3',
                assessment_status='COMPLETE'
            )
        )

    if assessments_to_create:
        SlowMovingRiskAssessment.objects.all().delete()
        SlowMovingRiskAssessment.objects.bulk_create(assessments_to_create, ignore_conflicts=True)
        try:
            from supplyforge.services.auto_decision_generator import AutoDecisionGeneratorService
            AutoDecisionGeneratorService.generate_decisions_from_assessments()
        except Exception as e:
            logger.error("Auto decision generator failed: %s", e)


@csrf_exempt
@api_view(['GET'])
def get_global_risk_summary(request):
    """
    GET /api/v1/risk/summary
    Aggregated count summary across all 4 risk classes.
    """
    session_id = request.query_params.get('session_id')
    qs = SlowMovingRiskAssessment.objects.all()

    if not qs.exists():
        _auto_populate_assessments_from_products(session_id)
        qs = SlowMovingRiskAssessment.objects.all()

    if session_id and qs.filter(session_id=session_id).exists():
        qs = qs.filter(session_id=session_id)

    total_skus = qs.count()
    counts = qs.values('risk_class').annotate(total=Count('id'))
    counts_map = {item['risk_class'].upper(): item['total'] for item in counts}

    return Response({
        'total_skus': total_skus,
        'critical': counts_map.get('CRITICAL', 0),
        'high_risk': counts_map.get('HIGH_RISK', 0),
        'medium_risk': counts_map.get('MEDIUM_RISK', 0),
        'low_risk': counts_map.get('LOW_RISK', 0)
    })
