"""
Data Freshness V2 — Views (DAT-08)
===================================
REST API endpoints for Data Freshness Tracking, decision safety guard,
and SKU-level freshness report retrieval.

POST /api/v2/ingestion/sessions/<id>/freshness-tracking Execute Freshness Evaluation
GET  /api/v2/ingestion/sessions/<id>/freshness-status   Get Freshness Status & Alerts
GET  /api/v2/ingestion/sessions/<id>/sku-freshness      Get SKU Freshness Profiles
"""

import json
import logging
import os
import sys

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import pandas as pd

from supplyforge.models import IngestionSession
from supplyforge.services.storage_backend import StorageBackend

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.data_freshness_tracker import DataFreshnessTracker
from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@api_view(['POST'])
def trigger_freshness_tracking(request, session_id):
    """Execute DAT-08 Data Freshness Evaluation on session dataset."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Prefer merged/normalized dataset if available, fallback to session storage_path
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    inc_csv_path = os.path.join(reports_dir, 'incremental_dataset.csv')
    norm_csv_path = os.path.join(reports_dir, 'normalized_dataset.csv')

    data_filepath = session.storage_path
    if os.path.exists(inc_csv_path):
        data_filepath = inc_csv_path
    elif os.path.exists(norm_csv_path):
        data_filepath = norm_csv_path

    if not data_filepath or not StorageBackend.exists(data_filepath):
        return Response(
            {'error': 'Không tìm thấy tệp dữ liệu của phiên này trên hệ thống.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    mapping_result = session.column_mapping_json
    custom_thresholds = request.data.get('customThresholds')

    try:
        with StorageBackend.localize(data_filepath) as local_path:
            df = pd.read_csv(local_path, nrows=50000, encoding_errors='replace')

        tracker = DataFreshnessTracker(session_id=str(session.id))
        status_result = tracker.evaluate_freshness(
            df=df,
            mapping_result=mapping_result,
            custom_thresholds=custom_thresholds,
            last_upload_at=session.created_at.isoformat() if session.created_at else None
        )

        generated_files = tracker.export_artifacts(status_result, output_dir=reports_dir)

        session.freshness_status = status_result.get('freshnessStatus', 'FRESH')
        session.freshness_days = status_result.get('freshnessDays', 0)
        session.freshness_json = status_result
        session.save(update_fields=['freshness_status', 'freshness_days', 'freshness_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'freshnessStatus': session.freshness_status,
            'freshnessDays': session.freshness_days,
            'decisionGuard': status_result.get('decisionGuard', {}),
            'alerts': status_result.get('alerts', []),
            'reportsGenerated': generated_files,
            'statusResult': status_result,
        })

    except Exception as e:
        logger.exception("Freshness tracking failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Freshness Tracking: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_freshness_status(request, session_id):
    """Retrieve data freshness status, decision safety guard, and alerts."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    status_file = os.path.join(reports_dir, 'data_freshness_status.json')

    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            status_result = json.load(f)
        return Response({'statusResult': status_result})

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.freshness_json:
            return Response({'statusResult': session.freshness_json})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'statusResult': None})


@api_view(['GET'])
def get_sku_freshness_report(request, session_id):
    """Retrieve paginated SKU-level freshness report."""
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('pageSize', 5))

    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sku_csv_path = os.path.join(reports_dir, 'sku_freshness_report.csv')

    if os.path.exists(sku_csv_path):
        try:
            sku_df = pd.read_csv(sku_csv_path, encoding_errors='replace')
            total = len(sku_df)
            total_pages = max(1, (total + page_size - 1) // page_size)

            start = (page - 1) * page_size
            end = start + page_size
            page_df = sku_df.iloc[start:end].fillna("")

            return Response({
                'total': total,
                'page': page,
                'pageSize': page_size,
                'totalPages': total_pages,
                'items': page_df.to_dict(orient='records')
            })
        except Exception as e:
            logger.exception("Failed to read sku_freshness_report.csv")

    return Response({
        'total': 0,
        'page': page,
        'pageSize': page_size,
        'totalPages': 1,
        'items': []
    })
