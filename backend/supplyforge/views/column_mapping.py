"""
Automatic Column Mapping V2 — Views (Task 03)
==============================================
REST API endpoints for 3-strategy automatic column mapping, human-in-the-loop overrides,
and audit log retrieval.

POST /api/v2/ingestion/sessions/<id>/map-columns      Trigger 3-strategy column mapping
POST /api/v2/ingestion/sessions/<id>/mapping-override Submit user mapping override
GET  /api/v2/ingestion/sessions/<id>/mapping-audit    Retrieve column_mapping.json audit log
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

from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def trigger_column_mapping(request, session_id):
    """Execute multi-strategy automatic column mapping on session CSV."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    user_overrides = request.data.get('userOverrides') or {}

    headers = session.headers_json or []
    preview_rows = session.preview_rows_json or []

    # If headers missing in DB session, load from file directly
    if not headers and session.storage_path and os.path.exists(session.storage_path):
        try:
            df_sample = pd.read_csv(session.storage_path, nrows=5, encoding_errors='replace')
            headers = list(df_sample.columns)
            preview_rows = df_sample.astype(str).values.tolist()
        except Exception as e:
            logger.exception("Failed to read CSV for headers: %s", e)

    if not headers:
        return Response(
            {'error': 'Không tìm thấy thông tin cột trong phiên upload.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(
            headers=headers,
            sample_rows=preview_rows,
            user_overrides=user_overrides
        )

        # Export reports/column_mapping.json
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        audit_file_path = mapper.export_audit_log(mapping_result, output_dir=reports_dir)

        # Save to session DB
        session.column_mapping_json = mapping_result
        session.status = 'MAPPING'
        session.save(update_fields=['column_mapping_json', 'status', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'status': session.status,
            'mappingResult': mapping_result,
            'auditLogFile': audit_file_path,
        })

    except Exception as e:
        logger.exception("Column mapping failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi column mapping: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['POST'])
def submit_mapping_override(request, session_id):
    """Submit human-in-the-loop user overrides for column mappings."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    source_column = request.data.get('sourceColumn')
    override_canonical_field = request.data.get('canonicalField')  # can be null to unmap/ignore

    if not source_column:
        return Response(
            {'error': 'Vui lòng chỉ định sourceColumn.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Load existing mapping or run fresh
        headers = session.headers_json or []
        preview_rows = session.preview_rows_json or []

        existing_overrides = {}
        if session.column_mapping_json and 'mappings' in session.column_mapping_json:
            for m in session.column_mapping_json['mappings']:
                if m.get('user_override'):
                    existing_overrides[m['source_column']] = m['canonical_field']

        existing_overrides[source_column] = override_canonical_field

        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(
            headers=headers,
            sample_rows=preview_rows,
            user_overrides=existing_overrides
        )

        # Export updated reports/column_mapping.json
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        audit_file_path = mapper.export_audit_log(mapping_result, output_dir=reports_dir)

        session.column_mapping_json = mapping_result
        session.save(update_fields=['column_mapping_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'status': session.status,
            'mappingResult': mapping_result,
            'auditLogFile': audit_file_path,
        })

    except Exception as e:
        logger.exception("Mapping override failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi cập nhật mapping override: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def get_mapping_audit(request, session_id):
    """Retrieve column mapping result and audit log for a session."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if session.column_mapping_json:
        return Response(session.column_mapping_json)

    # Check if reports/column_mapping.json exists on disk
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    audit_file = os.path.join(reports_dir, 'column_mapping.json')
    if os.path.exists(audit_file):
        with open(audit_file, 'r', encoding='utf-8') as f:
            return Response(json.load(f))

    # If no mapping exists yet, run initial mapping
    headers = session.headers_json or []
    preview_rows = session.preview_rows_json or []
    if headers:
        mapper = ColumnMapper(session_id=str(session.id))
        result = mapper.map_columns(headers=headers, sample_rows=preview_rows)
        mapper.export_audit_log(result, output_dir=reports_dir)
        session.column_mapping_json = result
        session.save(update_fields=['column_mapping_json', 'updated_at'])
        return Response(result)

    return Response(
        {'error': 'Phiên ingestion chưa có dữ liệu ánh xạ cột.'},
        status=status.HTTP_404_NOT_FOUND
    )
