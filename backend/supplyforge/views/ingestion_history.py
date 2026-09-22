"""
Ingestion History V2 — Views (DAT-09)
======================================
REST API endpoints for recording and retrieving ingestion history sessions,
processing stats, version lineage, error logs, and audit trails.

POST /api/v2/ingestion/sessions/<id>/record-history  Record/Update Ingestion Event
GET  /api/v2/ingestion/sessions/<id>/history         Get Session Ingestion Details
GET  /api/v2/ingestion/history-list                  Get All Ingestion History Sessions
"""

import json
import logging
import os
import sys

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.models import IngestionSession

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.ingestion_history_tracker import IngestionHistoryTracker

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def record_ingestion_history_event(request, session_id):
    """Record or update an ingestion session event in history."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    stage = request.data.get('stage', 'COMPLETED')
    hist_status = request.data.get('status', 'COMPLETED')
    filename = request.data.get('filename', session.original_filename or 'shopee_upload.csv')
    stats = request.data.get('stats')
    time_info = request.data.get('timeInfo')
    version_info = request.data.get('versionInfo')
    error_info = request.data.get('errorInfo')
    audit_action = request.data.get('auditAction')

    try:
        tracker = IngestionHistoryTracker(session_id=str(session.id))
        result = tracker.record_ingestion_event(
            session_id=str(session.id),
            stage=stage,
            status=hist_status,
            filename=filename,
            ingestion_id=session.ingestion_id,
            stats=stats,
            time_info=time_info,
            version_info=version_info,
            error_info=error_info,
            audit_action=audit_action,
            output_dir=os.path.join(PROJECT_ROOT, 'reports')
        )

        session.ingestion_id = result['ingestionId']
        session.ingestion_history_json = result['sessionRecord']
        session.save(update_fields=['ingestion_id', 'ingestion_history_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'ingestionId': session.ingestion_id,
            'currentStage': stage,
            'status': hist_status,
            'historyRecord': result['sessionRecord'],
            'reportsGenerated': result['reportsGenerated'],
        })

    except Exception as e:
        logger.exception("Failed to record ingestion history for session %s", session_id)
        return Response(
            {'error': f'Lỗi ghi nhận Ingestion History: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def get_ingestion_history_detail(request, session_id):
    """Retrieve detailed history for a specific ingestion session."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    history_file = os.path.join(reports_dir, 'ingestion_history.json')

    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history_list = json.load(f)
            for item in history_list:
                if item.get('sessionId') == str(session_id) or item.get('ingestionId') == str(session_id):
                    return Response({'historyDetail': item})
        except Exception as e:
            logger.exception("Error reading ingestion_history.json")

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.ingestion_history_json:
            return Response({'historyDetail': session.ingestion_history_json})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'historyDetail': None})


@csrf_exempt
@api_view(['GET'])
def get_all_ingestion_history_list(request):
    """Retrieve master list of all ingestion sessions across datasets."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    history_file = os.path.join(reports_dir, 'ingestion_history.json')

    history_list = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history_list = json.load(f)
        except Exception:
            pass

    # Also include Django DB sessions if not present in file
    sessions = IngestionSession.objects.all().order_by('-created_at')[:50]
    existing_session_ids = {h.get('sessionId') for h in history_list}

    for s in sessions:
        if str(s.id) not in existing_session_ids:
            created_str = s.created_at.strftime('%Y%m%d') if s.created_at else '20260816'
            created_iso = s.created_at.isoformat() if s.created_at else ''
            history_list.append({
                'ingestionId': s.ingestion_id or f"ING-{created_str}-00001",
                'sessionId': str(s.id),
                'datasetId': 'Shopee_Default_Dataset',
                'filename': s.original_filename or 'shopee_sales.csv',
                'uploadedAt': created_iso,
                'uploadedBy': 'merchant_default',
                'currentStage': 'COMPLETED' if s.status == 'PROFILED' else s.status,
                'status': 'COMPLETED',
                'datasetVersion': s.dataset_version or 'v1.0',
                'timeline': [{'stage': 'COMPLETED', 'status': 'COMPLETED', 'timestamp': created_iso}],
                'statistics': {
                    'totalRecords': getattr(s, 'record_count', 0) or 0,
                    'validRecords': getattr(s, 'record_count', 0) or 0,
                },
                'timeRange': {},
            })

    return Response({
        'totalIngestions': len(history_list),
        'ingestionHistory': history_list,
    })
