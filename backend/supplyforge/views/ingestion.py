"""
Data Ingestion V2 — Views
===========================
REST API endpoints for the new streaming CSV upload & profiling pipeline.

POST /api/v2/ingestion/upload          Upload CSV + stream-profile
GET  /api/v2/ingestion/sessions/<id>   Get session detail
GET  /api/v2/ingestion/sessions        List all sessions for workspace
"""

import logging
import os
import json

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.models import IngestionSession, Workspace
from supplyforge.services.csv_profiler import StreamingCSVProfiler, humanize_bytes
from supplyforge.services.ingestion import DynamicFileImportService

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def ingestion_upload(request):
    """Upload a CSV file → save to disk → streaming profile → return results.

    Accepts:
        - file: CSV file (multipart/form-data)
        - workspaceId: workspace ID (default: 1)
        - sessionType: 'INITIAL' or 'INCREMENTAL' (default: 'INITIAL')
    """
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {'error': 'Vui lòng chọn file CSV để upload.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not file_obj.name.lower().endswith('.csv'):
        return Response(
            {'error': 'Hệ thống chỉ hỗ trợ file CSV. Vui lòng upload file có phần mở rộng .csv'},
            status=status.HTTP_400_BAD_REQUEST
        )

    workspace_id = request.data.get('workspaceId', 1)
    session_type = request.data.get('sessionType', 'INITIAL')

    # Validate workspace exists (create default if needed for MVP)
    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        workspace, _ = Workspace.objects.get_or_create(
            id=1,
            defaults={'name': 'Default Workspace', 'slug': 'default'}
        )

    # ── 1. Create ingestion session ───────────────────────────────────
    session = IngestionSession.objects.create(
        workspace=workspace,
        original_filename=file_obj.name,
        session_type=session_type,
        status='UPLOADING',
    )

    try:
        # ── 2. Save file to disk (streaming, chunked) ────────────────
        storage_path, file_size = StreamingCSVProfiler.save_uploaded_file(file_obj)
        session.storage_path = storage_path
        session.file_size_bytes = file_size
        session.status = 'PROFILING'
        session.save(update_fields=['storage_path', 'file_size_bytes', 'status', 'updated_at'])

        # ── 3. Streaming profile ──────────────────────────────────────
        profile = StreamingCSVProfiler.profile_csv(storage_path)

        # ── 4. Persist profiling results ──────────────────────────────
        session.total_rows = profile.total_rows
        session.total_columns = profile.total_columns
        session.headers_json = profile.headers
        session.column_types_json = profile.column_types
        session.date_column_detected = profile.date_column_detected
        session.sku_column_detected = profile.sku_column_detected
        session.unique_sku_count = profile.unique_sku_count
        session.missing_values_json = profile.missing_values
        session.preview_rows_json = profile.preview_rows

        if profile.date_range_start:
            from datetime import datetime as dt
            session.date_range_start = dt.strptime(profile.date_range_start, '%Y-%m-%d').date()
        if profile.date_range_end:
            from datetime import datetime as dt
            session.date_range_end = dt.strptime(profile.date_range_end, '%Y-%m-%d').date()

        session.status = 'PROFILED'
        session.save()

        # ── 5. Build response ─────────────────────────────────────────
        return Response({
            'sessionId': str(session.id),
            'status': session.status,
            'file': {
                'originalFilename': session.original_filename,
                'fileSizeBytes': file_size,
                'fileSizeHuman': humanize_bytes(file_size),
            },
            'profile': profile.to_dict(),
        })

    except Exception as e:
        logger.exception('Ingestion profiling failed for session %s', session.id)
        session.status = 'FAILED'
        session.error_message = str(e)
        session.save(update_fields=['status', 'error_message', 'updated_at'])
        return Response(
            {'error': f'Profiling thất bại: {str(e)}', 'sessionId': str(session.id)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def ingestion_session_detail(request, session_id):
    """Get profiling results for a specific ingestion session."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response(_serialize_session(session))


@csrf_exempt
@api_view(['GET'])
def ingestion_session_list(request):
    """List all ingestion sessions, optionally filtered by workspace."""
    workspace_id = request.GET.get('workspaceId', 1)
    sessions = IngestionSession.objects.filter(workspace_id=workspace_id)[:50]
    return Response([_serialize_session(s) for s in sessions])


def _serialize_session(session: IngestionSession) -> dict:
    """Serialize an IngestionSession to JSON-friendly dict."""
    date_range = {}
    if session.date_range_start or session.date_range_end:
        start_str = session.date_range_start.isoformat() if session.date_range_start else None
        end_str = session.date_range_end.isoformat() if session.date_range_end else None
        span = None
        if session.date_range_start and session.date_range_end:
            span = (session.date_range_end - session.date_range_start).days
        date_range = {'start': start_str, 'end': end_str, 'spanDays': span}

    return {
        'sessionId': str(session.id),
        'status': session.status,
        'sessionType': session.session_type,
        'file': {
            'originalFilename': session.original_filename,
            'fileSizeBytes': session.file_size_bytes,
            'fileSizeHuman': humanize_bytes(session.file_size_bytes),
        },
        'profile': {
            'totalRows': session.total_rows,
            'totalColumns': session.total_columns,
            'headers': session.headers_json,
            'columnTypes': session.column_types_json,
            'dateRange': date_range,
            'dateColumnDetected': session.date_column_detected,
            'uniqueSkuCount': session.unique_sku_count,
            'skuColumnDetected': session.sku_column_detected,
            'missingValues': session.missing_values_json,
            'previewRows': session.preview_rows_json,
        },
        'createdAt': session.created_at.isoformat() if session.created_at else None,
        'updatedAt': session.updated_at.isoformat() if session.updated_at else None,
        'errorMessage': session.error_message,
    }


# ── Legacy v1 Adapter Functions ───────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
def analyze_file(request):
    """v1 Legacy Adapter -> Delegates to Streaming Ingestion Upload."""
    return ingestion_upload(request)


@csrf_exempt
@api_view(['POST'])
def process_file(request):
    """
    POST /api/v1/import/process
    Process uploaded CSV or session file with mapping rule and import into Products & Orders.
    """
    file_obj = request.FILES.get('file')
    mapping_rule_raw = request.data.get('mappingRule')
    session_id = request.data.get('sessionId') or request.GET.get('sessionId')
    user_id = request.data.get('userId') or request.GET.get('userId', 'user_default_001')

    if not file_obj and session_id:
        try:
            session = IngestionSession.objects.get(id=session_id)
            if session.storage_path and os.path.exists(session.storage_path):
                file_obj = open(session.storage_path, 'rb')
        except Exception:
            pass

    if not file_obj:
        return Response({'error': 'Vui lòng cung cấp tệp CSV hoặc sessionId hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)

    mapping_rule = {}
    if mapping_rule_raw:
        if isinstance(mapping_rule_raw, str):
            try:
                mapping_rule = json.loads(mapping_rule_raw)
            except Exception:
                pass
        elif isinstance(mapping_rule_raw, dict):
            mapping_rule = mapping_rule_raw

    res = DynamicFileImportService.process_batch_import(file_obj, mapping_rule, user_id)

    return Response({
        'status': 'success',
        'message': 'Đã nạp thành công dữ liệu sản phẩm và đơn hàng vào hệ thống.',
        'result': res
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['DELETE', 'POST'])
def clear_data(request):
    """v1 Legacy Adapter Clear Data."""
    user_id = request.data.get('userId') or request.GET.get('userId', 'user_default_001')
    DynamicFileImportService.clear_data(user_id)
    return Response({"message": "Đã xóa toàn bộ dữ liệu sản phẩm và đơn hàng cũ thành công."})
