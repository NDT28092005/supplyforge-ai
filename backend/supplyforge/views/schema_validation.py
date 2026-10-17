"""
Canonical Schema Validation V2 — Views (Task 04)
=================================================
REST API endpoints for executing Canonical Schema Validation and retrieving reports.

POST /api/v2/ingestion/sessions/<id>/validate-schema     Execute schema validation
GET  /api/v2/ingestion/sessions/<id>/schema-validation   Get schema validation report JSON
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

from src.ingestion.schema_validator import SchemaValidator
from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@api_view(['POST'])
def validate_canonical_schema(request, session_id):
    """Execute Canonical Schema Validation on session CSV and column mapping."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not session.storage_path or not StorageBackend.exists(session.storage_path):
        return Response(
            {'error': 'Tệp CSV của phiên này không tồn tại trên hệ thống.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get or generate column mapping
    mapping_result = session.column_mapping_json
    if not mapping_result:
        headers = session.headers_json or []
        preview_rows = session.preview_rows_json or []
        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(headers=headers, sample_rows=preview_rows)
        session.column_mapping_json = mapping_result
        session.save(update_fields=['column_mapping_json', 'updated_at'])

    try:
        # Load CSV sample / full
        with StorageBackend.localize(session.storage_path) as local_path:
            df = pd.read_csv(local_path, nrows=5000, encoding_errors='replace')
            validator = SchemaValidator(session_id=str(session.id))
            report_result = validator.validate_schema(df, mapping_result)

        # Export reports/schema_validation_report.json
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        report_file_path = validator.export_report(report_result, output_dir=reports_dir)

        # Save to IngestionSession DB
        session.schema_validation_status = report_result.get('status', 'VALID')
        session.schema_validation_json = report_result
        session.save(update_fields=['schema_validation_status', 'schema_validation_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'status': report_result['status'],
            'reportFile': report_file_path,
            'report': report_result,
        })

    except Exception as e:
        logger.exception("Schema validation failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi schema validation: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_schema_validation_report(request, session_id):
    """Retrieve existing Canonical Schema Validation report JSON."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if session.schema_validation_json:
        return Response(session.schema_validation_json)

    # Check if reports/schema_validation_report.json exists on disk
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    report_file = os.path.join(reports_dir, 'schema_validation_report.json')
    if os.path.exists(report_file):
        with open(report_file, 'r', encoding='utf-8') as f:
            return Response(json.load(f))

    # If not yet generated, attempt to validate on the fly
    if session.storage_path and StorageBackend.exists(session.storage_path):
        mapping_result = session.column_mapping_json or {}
        with StorageBackend.localize(session.storage_path) as local_path:
            df = pd.read_csv(local_path, nrows=5000, encoding_errors='replace')
            validator = SchemaValidator(session_id=str(session.id))
            report_result = validator.validate_schema(df, mapping_result)
        validator.export_report(report_result, output_dir=reports_dir)

        session.schema_validation_status = report_result.get('status', 'VALID')
        session.schema_validation_json = report_result
        session.save(update_fields=['schema_validation_status', 'schema_validation_json', 'updated_at'])
        return Response(report_result)

    return Response(
        {'error': 'Phiên ingestion chưa thực hiện Schema Validation.'},
        status=status.HTTP_404_NOT_FOUND
    )
