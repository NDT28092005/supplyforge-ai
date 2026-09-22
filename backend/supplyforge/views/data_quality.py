"""
Data Quality Validation V2 — Views (DAT-05)
============================================
REST API endpoints for executing Data Quality Validation, fetching reports,
and serving paginated SKU quality profiles.

POST /api/v2/ingestion/sessions/<id>/quality-validation    Execute quality validation
GET  /api/v2/ingestion/sessions/<id>/quality-report        Get data quality report JSON
GET  /api/v2/ingestion/sessions/<id>/sku-quality-profiles  Get paginated SKU quality profiles
"""

import json
import logging
import os
import sys

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import pandas as pd

from supplyforge.models import IngestionSession

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.data_quality_validator import DataQualityValidator
from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def trigger_data_quality_validation(request, session_id):
    """Execute 13-dimension deterministic Data Quality Validation on session dataset."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not session.storage_path or not os.path.exists(session.storage_path):
        return Response(
            {'error': 'Tệp CSV của phiên này không tồn tại trên hệ thống.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Load column mapping result if present
    mapping_result = session.column_mapping_json
    if not mapping_result:
        headers = session.headers_json or []
        preview_rows = session.preview_rows_json or []
        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(headers=headers, sample_rows=preview_rows)
        session.column_mapping_json = mapping_result
        session.save(update_fields=['column_mapping_json', 'updated_at'])

    try:
        # Load CSV dataset (up to 50k rows for quality profiling)
        df = pd.read_csv(session.storage_path, nrows=50000, encoding_errors='replace')

        validator = DataQualityValidator(session_id=str(session.id))
        report_result = validator.validate_quality(df, mapping_result)

        # Export reports/data_quality_report.json, data_quality_summary.json, sku_quality_profile.csv/parquet
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        generated_files = validator.export_reports(report_result, output_dir=reports_dir)

        # Save to IngestionSession DB
        session.quality_score = report_result.get('datasetQualityScore', 0.0)
        session.quality_status = report_result.get('qualityStatus', 'GOOD')
        session.data_quality_json = report_result
        session.status = 'PROFILED'
        session.save(update_fields=['quality_score', 'quality_status', 'data_quality_json', 'status', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'status': session.quality_status,
            'qualityScore': session.quality_score,
            'reportsGenerated': generated_files,
            'report': report_result,
        })

    except Exception as e:
        logger.exception("Data quality validation failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Data Quality Validation: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def get_data_quality_report(request, session_id):
    """Retrieve Data Quality Validation report JSON."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if session.data_quality_json:
        return Response(session.data_quality_json)

    # Check if reports/data_quality_report.json exists on disk
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    report_file = os.path.join(reports_dir, 'data_quality_report.json')
    if os.path.exists(report_file):
        with open(report_file, 'r', encoding='utf-8') as f:
            return Response(json.load(f))

    return Response(
        {'error': 'Phiên ingestion chưa thực hiện Data Quality Validation.'},
        status=status.HTTP_404_NOT_FOUND
    )


@csrf_exempt
@api_view(['GET'])
def get_sku_quality_profiles(request, session_id):
    """Retrieve paginated SKU-level Data Quality Profiles."""
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('pageSize', 10))
    search = request.query_params.get('search', '').strip().lower()
    status_filter = request.query_params.get('status', '').strip().upper()

    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    csv_file = os.path.join(reports_dir, 'sku_quality_profile.csv')

    if not os.path.exists(csv_file):
        return Response({'total': 0, 'page': page, 'pageSize': page_size, 'items': []})

    try:
        df = pd.read_csv(csv_file).fillna('')
        if search:
            df = df[df['sku'].astype(str).str.lower().str.contains(search)]
        if status_filter:
            df = df[df['quality_status'].astype(str).str.upper() == status_filter]

        total = len(df)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        items = df.iloc[start_idx:end_idx].to_dict(orient='records')

        return Response({
            'total': total,
            'page': page,
            'pageSize': page_size,
            'totalPages': (total + page_size - 1) // page_size if page_size > 0 else 1,
            'items': items,
        })
    except Exception as e:
        logger.exception("Failed to read sku_quality_profile.csv: %s", e)
        return Response(
            {'error': f'Lỗi đọc dữ liệu SKU quality profiles: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
