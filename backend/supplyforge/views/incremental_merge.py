"""
Incremental Merge V2 — Views (DAT-07)
======================================
REST API endpoints for Incremental Upload & Dataset Merge, version history,
and mutation audit log retrieval.

POST /api/v2/ingestion/sessions/<id>/incremental-merge Execute Incremental Merge
GET  /api/v2/ingestion/sessions/<id>/merge-report       Get Merge Report & Upload Metadata
GET  /api/v2/ingestion/sessions/<id>/dataset-versions  Get Dataset Versions & Audit Log
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

from src.ingestion.incremental_merger import IncrementalMerger
from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def trigger_incremental_merge(request, session_id):
    """Execute DAT-07 Incremental Merge pipeline on session CSV."""
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

    mapping_result = session.column_mapping_json
    if not mapping_result:
        headers = session.headers_json or []
        preview_rows = session.preview_rows_json or []
        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(headers=headers, sample_rows=preview_rows)
        session.column_mapping_json = mapping_result

    try:
        new_df = pd.read_csv(session.storage_path, nrows=50000, encoding_errors='replace')

        # Check if existing canonical dataset exists on disk
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        existing_csv_path = os.path.join(reports_dir, 'incremental_dataset.csv')
        existing_df = None
        if os.path.exists(existing_csv_path):
            try:
                existing_df = pd.read_csv(existing_csv_path, encoding_errors='replace')
            except Exception:
                existing_df = None

        merger = IncrementalMerger(session_id=str(session.id))
        merge_report = merger.merge_incremental_upload(new_df, existing_df=existing_df, mapping_result=mapping_result)

        generated_files = merger.export_artifacts(merge_report, output_dir=reports_dir)

        session.dataset_version = merge_report.get('versionInfo', {}).get('currentVersion', 'v1.0')
        session.incremental_merge_json = merge_report
        session.save(update_fields=['dataset_version', 'incremental_merge_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'datasetVersion': session.dataset_version,
            'summary': merge_report.get('summary', {}),
            'uploadMetadata': merge_report.get('uploadMetadata', {}),
            'recalculationTrigger': merge_report.get('recalculationTrigger', {}),
            'reportsGenerated': generated_files,
            'mergeReport': merge_report,
        })

    except Exception as e:
        logger.exception("Incremental merge failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Incremental Merge: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def get_merge_report(request, session_id):
    """Retrieve merge report and upload metadata."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    report_file = os.path.join(reports_dir, 'merge_report.json')

    if os.path.exists(report_file):
        with open(report_file, 'r', encoding='utf-8') as f:
            report = json.load(f)
        return Response({'report': report})

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.incremental_merge_json:
            return Response({'report': session.incremental_merge_json})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'report': None})


@csrf_exempt
@api_view(['GET'])
def get_dataset_versions(request, session_id):
    """Retrieve dataset versions and historical mutation audit log."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    version_file = os.path.join(reports_dir, 'dataset_version.json')
    audit_file = os.path.join(reports_dir, 'dataset_audit_log.json')

    version_info = {}
    audit_log = []

    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            version_info = json.load(f)

    if os.path.exists(audit_file):
        with open(audit_file, 'r', encoding='utf-8') as f:
            audit_log = json.load(f)

    return Response({
        'versionInfo': version_info,
        'auditLog': audit_log,
    })
