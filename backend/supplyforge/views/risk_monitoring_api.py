import logging
import os
import pandas as pd
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.models import IngestionSession, SlowMovingRiskAssessment, RiskMonitoringRun
from src.analytics.risk_monitoring_engine import RiskMonitoringEngine

logger = logging.getLogger(__name__)


# ── M3-08 Risk Monitoring & Validation Views ────────────────────────────

@api_view(['POST'])
def execute_risk_monitoring(request):
    """
    POST /api/v1/risk/monitoring/run
    Execute Risk Monitoring & Validation Engine (M3-08) and persist run snapshot into Django DB.
    """
    session_id = request.data.get('session_id') or request.query_params.get('session_id')
    if not session_id:
        return Response(
            {'error': 'Vui lòng cung cấp session_id hợp lệ.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': f'Không tìm thấy IngestionSession với ID {session_id}'},
            status=status.HTTP_404_NOT_FOUND
        )

    # 1. Gather Assessments from DB or session JSON
    assessments_data = []
    db_assessments = SlowMovingRiskAssessment.objects.filter(session=session)

    if db_assessments.exists():
        for r in db_assessments:
            assessments_data.append({
                'sku': r.sku,
                'canonical_sku_id': r.canonical_sku_id,
                'product_name': r.product_name,
                'category': r.category,
                'assessment': {
                    'risk_class': r.risk_class,
                    'risk_probability': r.risk_probability,
                    'risk_score': r.risk_score
                },
                'primary_signals': r.primary_signals,
                'supporting_signals': r.supporting_signals,
                'diagnostics': r.diagnostics,
                'evidence': r.evidence,
                'metadata': {
                    'decision_cutoff': r.decision_cutoff,
                    'model_version': r.model_version,
                    'calibration_version': r.calibration_version,
                    'diagnostic_rule_version': r.diagnostic_rule_version,
                    'data_version': r.dataset_version
                },
                'assessment_status': r.assessment_status
            })
    elif session.m3_risk_assessments_json:
        assessments_data = session.m3_risk_assessments_json.get('assessments', [])

    if not assessments_data:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu Risk Assessment M3-06 / M3-07 để giám sát. Vui lòng chạy M3-06 / M3-07 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 2. Execute Monitoring Engine
    PROJECT_ROOT = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    try:
        engine = RiskMonitoringEngine(session_id=str(session.id))
        result = engine.evaluate_risk_assessments(
            assessments=assessments_data,
            session_id=str(session.id),
            output_dir=reports_dir,
            data_dir=data_dir
        )

        rep = result.get('report', {})
        alerts = result.get('alerts', [])

        # 3. Persist Monitoring Run Record
        run_obj = RiskMonitoringRun.objects.create(
            session=session,
            status=result.get('status', 'HEALTHY'),
            total_skus_evaluated=result.get('total_skus', len(assessments_data)),
            risk_distribution=rep.get('risk_distribution', {}),
            probability_stats=rep.get('probability_statistics', {}),
            validation_summary=rep.get('validation_summary', {}),
            alerts=alerts
        )

        return Response({
            'run_id': str(run_obj.id),
            'session_id': str(session.id),
            'status': run_obj.status,
            'total_skus_evaluated': run_obj.total_skus_evaluated,
            'report': rep,
            'alerts': alerts
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.exception("Failed to execute M3-08 Risk Monitoring for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Monitoring M3-08: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def list_monitoring_runs(request):
    """
    GET /api/v1/risk/monitoring
    Retrieve List of Risk Monitoring Runs filtered by status or session_id.
    """
    session_id = request.query_params.get('session_id')
    status_filter = request.query_params.get('status')

    qs = RiskMonitoringRun.objects.all()
    if session_id:
        qs = qs.filter(session_id=session_id)
    if status_filter:
        qs = qs.filter(status__iexact=status_filter)

    runs = [
        {
            'run_id': str(r.id),
            'session_id': str(r.session_id),
            'status': r.status,
            'total_skus_evaluated': r.total_skus_evaluated,
            'risk_distribution': r.risk_distribution,
            'probability_stats': r.probability_stats,
            'validation_summary': r.validation_summary,
            'alerts_count': len(r.alerts),
            'run_timestamp': r.run_timestamp.isoformat()
        }
        for r in qs
    ]

    return Response({'total_runs': len(runs), 'runs': runs})


@api_view(['GET'])
def get_monitoring_run_detail(request, run_id):
    """
    GET /api/v1/risk/monitoring/<run_id>
    Retrieve Single Monitoring Run Detail Record.
    """
    try:
        r = RiskMonitoringRun.objects.get(id=run_id)
    except (RiskMonitoringRun.DoesNotExist, ValueError):
        return Response({'error': f'Không tìm thấy Monitoring Run với ID {run_id}'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'run_id': str(r.id),
        'session_id': str(r.session_id),
        'status': r.status,
        'total_skus_evaluated': r.total_skus_evaluated,
        'risk_distribution': r.risk_distribution,
        'probability_stats': r.probability_stats,
        'validation_summary': r.validation_summary,
        'alerts': r.alerts,
        'run_timestamp': r.run_timestamp.isoformat()
    })


@api_view(['GET'])
def get_active_monitoring_alerts(request):
    """
    GET /api/v1/risk/monitoring/alerts
    Retrieve Aggregated Active Alerts across all Monitoring Runs.
    """
    session_id = request.query_params.get('session_id')
    qs = RiskMonitoringRun.objects.all()
    if session_id:
        qs = qs.filter(session_id=session_id)

    all_alerts = []
    for r in qs:
        for a in r.alerts:
            item = dict(a)
            item['run_id'] = str(r.id)
            item['session_id'] = str(r.session_id)
            all_alerts.append(item)

    return Response({
        'total_alerts': len(all_alerts),
        'critical_alerts': sum(1 for a in all_alerts if a.get('severity') == 'CRITICAL'),
        'warning_alerts': sum(1 for a in all_alerts if a.get('severity') == 'WARNING'),
        'alerts': all_alerts
    })
