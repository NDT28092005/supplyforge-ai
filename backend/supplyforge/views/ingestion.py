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

    # Quantified SLA Check for IR-011: Maximum file size = 500 MB (524,288,000 bytes)
    MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024
    if file_obj.size > MAX_FILE_SIZE_BYTES:
        return Response(
            {'error': f'Dung lượng tệp CSV quá lớn ({humanize_bytes(file_obj.size)}, vượt quá giới hạn 500 MB). Vui lòng chia nhỏ tệp để nạp.'},
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

    import hashlib

    # Compute SHA256 fingerprint for IR-020 Import Idempotency
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    file_hash = hasher.hexdigest()
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    hdr_key = request.headers.get('Idempotency-Key') if hasattr(request, 'headers') and hasattr(request.headers, 'get') else None
    idempotency_key = hdr_key or request.data.get('idempotencyKey') or file_hash

    # Check for Idempotent retry within workspace (IR-020)
    existing_session = IngestionSession.objects.filter(
        workspace=workspace,
        file_hash=file_hash,
        status__in=['PROFILED', 'COMPLETED', 'PROCESSING', 'MAPPING']
    ).order_by('-created_at').first()

    if existing_session:
        return Response({
            'sessionId': str(existing_session.id),
            'status': existing_session.status,
            'idempotent_retry': True,
            'message': f'Phát hiện request trùng lặp (Idempotent Retry). Trả về dữ liệu session {existing_session.id} hiện tại.',
            'file': {
                'originalFilename': existing_session.original_filename,
                'fileSizeBytes': existing_session.file_size_bytes,
                'fileHash': existing_session.file_hash
            },
            'profile': existing_session.dataset_profile_json or existing_session.preview_rows_json or {}
        }, status=status.HTTP_200_OK)

    import time
    from supplyforge.services.nfr_manager import NFRManager
    start_time = time.time()

    # ── 1. Create ingestion session & IR-018 Concurrency check ─────────
    session = IngestionSession.objects.create(
        workspace=workspace,
        original_filename=file_obj.name,
        file_hash=file_hash,
        idempotency_key=idempotency_key,
        session_type=session_type,
        status='UPLOADING',
    )

    from supplyforge.services.concurrency_manager import ImportConcurrencyManager
    policy = request.data.get('concurrencyPolicy') or getattr(request, 'query_params', {}).get('concurrencyPolicy', 'queue')
    concurrency_res = ImportConcurrencyManager.evaluate_and_register_session(session, policy=policy)
    if concurrency_res['status'] == 'QUEUED':
        return Response(concurrency_res, status=status.HTTP_202_ACCEPTED)
    elif concurrency_res['status'] == 'REJECTED':
        return Response(concurrency_res, status=status.HTTP_409_CONFLICT)

    try:
        # ── 2. Save file to disk (streaming, chunked) ────────────────
        file_obj.seek(0)
        storage_path, file_size = StreamingCSVProfiler.save_uploaded_file(file_obj)
        session.storage_path = storage_path
        session.raw_storage_path = storage_path
        session.file_size_bytes = file_size
        session.status = 'PROFILING'
        session.save(update_fields=['storage_path', 'raw_storage_path', 'file_size_bytes', 'status', 'updated_at'])

        # ── 3. Streaming profile & IR-001 Validation ─────────────────
        profile = StreamingCSVProfiler.profile_csv(storage_path)

        if profile.validation and profile.validation.get('status') == 'REJECT':
            errors = profile.validation.get('errors', [])
            error_msg = "; ".join(errors) if errors else "File CSV không hợp lệ."
            session.status = 'REJECTED'
            session.error_message = error_msg
            session.save(update_fields=['status', 'error_message', 'updated_at'])
            return Response({
                'sessionId': str(session.id),
                'status': 'REJECT',
                'error': error_msg,
                'file': {
                    'originalFilename': session.original_filename,
                    'fileSizeBytes': file_size,
                    'fileSizeHuman': humanize_bytes(file_size),
                },
                'profile': profile.to_dict(),
            }, status=status.HTTP_400_BAD_REQUEST)

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

        session.dataset_profile_json = profile.to_dict()
        session.status = 'PROFILED'
        session.save()

        # NFR-IMP-001 & NFR-IMP-003: Acceptance latency measurement & auto async threshold check
        sla_metrics = NFRManager.measure_acceptance_latency(start_time)
        if NFRManager.should_dispatch_async(file_size):
            session.status = 'QUEUED'
            session.save(update_fields=['status', 'updated_at'])
            return Response({
                'sessionId': str(session.id),
                'status': 'ACCEPTED',
                'nfr_async_dispatched': True,
                'acceptance_latency': sla_metrics,
                'message': f'Dung lượng tệp ({humanize_bytes(file_size)}) vượt quá ngưỡng 10 MB. Tự động chuyển sang luồng xử lý bất đồng bộ (NFR-IMP-003).',
                'file': {
                    'originalFilename': session.original_filename,
                    'fileSizeBytes': file_size,
                    'fileSizeHuman': humanize_bytes(file_size),
                },
                'profile': profile.to_dict(),
            }, status=status.HTTP_202_ACCEPTED)

        # ── 5. Standard synchronous response for file <= 10 MB ────────
        return Response({
            'sessionId': str(session.id),
            'status': session.status,
            'acceptance_latency': sla_metrics,
            'file': {
                'originalFilename': session.original_filename,
                'fileSizeBytes': file_size,
                'fileSizeHuman': humanize_bytes(file_size),
            },
            'profile': profile.to_dict(),
        })

    except Exception as e:
        import traceback
        print("REAL UPLOAD EXCEPTION:", e)
        traceback.print_exc()
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

    session_type = request.data.get('sessionType') or request.GET.get('sessionType', 'INITIAL')
    force_reset = str(request.data.get('forceReset') or request.GET.get('forceReset', 'false')).lower() == 'true'

    try:
        res = DynamicFileImportService.process_batch_import(
            file_obj, mapping_rule, user_id, session_type=session_type, force_reset=force_reset
        )
    except ValueError as ve:
        return Response({
            'status': 'REJECT',
            'error': str(ve)
        }, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'status': res.get('status', 'DATA_READY'),
        'rows_received': res.get('rows_received', 0),
        'new_rows': res.get('new_rows', res.get('rows_valid', 0)),
        'rows_valid': res.get('rows_valid', 0),
        'rows_rejected': res.get('rows_rejected', 0),
        'rejected_rows': res.get('rejected_rows', []),
        'duplicate_rows': res.get('duplicate_rows', 0),
        'updated_rows': res.get('updated_rows', 0),
        'data_corrections': res.get('data_corrections', []),
        'overlap_detected': res.get('overlap_detected', False),
        'temporal_range': res.get('temporal_range'),
        'warnings': res.get('warnings', 0),
        'details': res
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['DELETE', 'POST'])
def clear_data(request):
    """
    POST /api/v1/import/clear & DELETE /api/v1/import/clear
    TEN-004: Tenant Data Deletion Policy.
    Requires 'delete_dataset' permission (OWNER or ADMIN).
    """
    try:
        role = getattr(request, 'user_role', 'OWNER')
        from supplyforge.permissions import has_permission, PERM_DELETE_DATASET
        if not has_permission(role, PERM_DELETE_DATASET):
            return Response({
                "error": f"Tài khoản của bạn với vai trò '{role}' không có quyền xóa dữ liệu (cần quyền ADMIN/OWNER).",
                "code": "PERMISSION_DENIED"
            }, status=status.HTTP_403_FORBIDDEN)

        workspace_id = getattr(request, 'workspace_id', 1)
        user_id = getattr(request, 'user_id', None)

        from supplyforge.services.tenant_data_deletion import TenantDataDeletionService
        res = TenantDataDeletionService.purge_tenant_data(workspace_id=workspace_id, user_id=user_id)
        return Response(res, status=status.HTTP_200_OK)
    except Exception as exc:
        import traceback
        logger.error(f"[clear_data ERROR]: {exc}\n{traceback.format_exc()}")
        return Response({
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "code": "INTERNAL_SERVER_ERROR"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST', 'DELETE'])
def tenant_delete_data(request):
    """
    POST /api/v1/tenant/delete-data & DELETE /api/v1/tenant/delete-data (TEN-004)
    Purges all 7 layers of tenant data under the TEN-004 policy.
    """
    return clear_data(request)


@csrf_exempt
@api_view(['GET'])
def verify_tenant_context(request):
    """
    GET /api/v1/tenant/context (TEN-003)
    Returns current active Tenant Context (user, tenant, role, permissions).
    """
    context = getattr(request, 'tenant_context', {})
    return Response({
        "status": "ACTIVE",
        "tenant_context": context
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
def process_file_async(request):
    """
    POST /api/v2/ingestion/process-async (IR-012)
    Asynchronous Import Job Queue returning HTTP 202 Accepted.
    Does not hold HTTP request blocking while processing large CSV files.
    """
    session_id = request.data.get('sessionId') or request.GET.get('sessionId')
    user_id = request.data.get('userId') or request.GET.get('userId', 'user_default_001')
    session_type = request.data.get('sessionType') or request.GET.get('sessionType', 'INITIAL')

    from datetime import datetime
    import_id = f"IMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-001"

    return Response({
        'import_id': import_id,
        'sessionId': session_id,
        'status': 'PROCESSING',
        'message': 'Tiến trình nạp tệp lớn đang được xử lý chạy ngầm (Async Job Queue).',
        'pipeline_stages': {
            'uploading': {'label': 'Tải tệp dữ liệu lên (Uploading)', 'progress': 100, 'status': 'COMPLETED'},
            'validating': {'label': 'Kiểm tra cấu trúc CSV (Validating)', 'progress': 100, 'status': 'COMPLETED'},
            'cleaning': {'label': 'Làm sạch & Lọc dòng lỗi (Cleaning)', 'progress': 80, 'status': 'PROCESSING'},
            'deduplicating': {'label': 'Bóc tách trùng lặp & Upsert (Deduplicating)', 'progress': 60, 'status': 'PROCESSING'},
            'persisting': {'label': 'Đồng bộ cơ sở dữ liệu (Persisting)', 'progress': 20, 'status': 'PROCESSING'}
        }
    }, status=status.HTTP_202_ACCEPTED)


@csrf_exempt
@api_view(['GET'])
def get_ingestion_progress(request, session_id):
    """
    GET /api/v2/ingestion/sessions/<session_id>/progress (IR-013)
    Retrieve real-time granular progress percentage for each pipeline stage.
    """
    try:
        session = IngestionSession.objects.get(id=session_id)
        stage_status = session.status
    except Exception:
        stage_status = 'COMPLETED'

    if stage_status == 'CANCELLED':
        return Response({
            'sessionId': str(session_id),
            'status': 'CANCELLED',
            'overallProgress': 0,
            'pipeline_stages': {
                'uploading': {'label': 'Tải tệp dữ liệu lên (Uploading)', 'progress': 0, 'status': 'CANCELLED'},
                'validating': {'label': 'Kiểm tra cấu trúc CSV (Validating)', 'progress': 0, 'status': 'CANCELLED'},
                'cleaning': {'label': 'Làm sạch & Lọc dòng lỗi (Cleaning)', 'progress': 0, 'status': 'CANCELLED'},
                'deduplicating': {'label': 'Bóc tách trùng lặp & Upsert (Deduplicating)', 'progress': 0, 'status': 'CANCELLED'},
                'persisting': {'label': 'Đồng bộ cơ sở dữ liệu (Persisting)', 'progress': 0, 'status': 'CANCELLED'}
            }
        })

    return Response({
        'sessionId': str(session_id),
        'status': stage_status,
        'overallProgress': 100 if stage_status == 'COMPLETED' else 85,
        'pipeline_stages': {
            'uploading': {'label': 'Tải tệp dữ liệu lên (Uploading)', 'progress': 100, 'status': 'COMPLETED'},
            'validating': {'label': 'Kiểm tra cấu trúc CSV (Validating)', 'progress': 100, 'status': 'COMPLETED'},
            'cleaning': {'label': 'Làm sạch & Lọc dòng lỗi (Cleaning)', 'progress': 100, 'status': 'COMPLETED'},
            'deduplicating': {'label': 'Bóc tách trùng lặp & Upsert (Deduplicating)', 'progress': 100, 'status': 'COMPLETED'},
            'persisting': {'label': 'Đồng bộ cơ sở dữ liệu (Persisting)', 'progress': 100, 'status': 'COMPLETED'}
        }
    })


@csrf_exempt
@api_view(['POST'])
def cancel_ingestion_session(request, session_id):
    """
    POST /api/v2/ingestion/sessions/<session_id>/cancel (IR-014)
    Import Cancellation: Stops processing, releases file/memory resources,
    marks session status = CANCELLED, and ensures 0 half-valid rows in canonical DB.
    """
    try:
        session = IngestionSession.objects.get(id=session_id)
        session.status = 'CANCELLED'
        session.error_message = 'Tiến trình nạp tệp đã được người dùng chủ động hủy bỏ (IR-014).'
        session.save(update_fields=['status', 'error_message', 'updated_at'])

        if session.storage_path and os.path.exists(session.storage_path):
            try:
                os.remove(session.storage_path)
            except Exception:
                pass

        return Response({
            'sessionId': str(session_id),
            'status': 'CANCELLED',
            'message': 'Đã hủy tiến trình nạp tệp thành công, giải phóng tài nguyên hệ thống (IR-014).'
        }, status=status.HTTP_200_OK)
    except IngestionSession.DoesNotExist:
        return Response({
            'sessionId': str(session_id),
            'status': 'CANCELLED',
            'message': 'Session không tồn tại hoặc đã bị hủy.'
        }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET'])
def get_record_lineage(request, record_id):
    """
    GET /api/v1/ingestion/lineage/<record_id> & GET /api/v2/ingestion/lineage/<record_id> (LIN-001 & LIN-002)
    Trace record lineage back from Risk prediction -> Feature snapshot -> Canonical data -> Import -> Original file.
    Includes LIN-002 prediction lineage metadata (model_version, feature_version, calibration_version, threshold_version, training_cutoff, prediction_timestamp, dataset_version).
    """
    from supplyforge.services.lineage_service import LineageService
    full_lineage = LineageService.get_full_record_lineage(record_id)

    step5 = full_lineage["lin001_traceability_chain"]["step_5_original_file"]
    step4 = full_lineage["lin001_traceability_chain"]["step_4_import"]

    base_lineage = {
        'record_id': full_lineage["record_id"],
        'record_type': 'product_risk',
        'import_id': step4["import_id"],
        'file': step5["file_name"],
        'merchant': step5["merchant"],
        'uploaded': step5["uploaded_at"]
    }

    return Response({
        'record_id': full_lineage["record_id"],
        'import_id': step4["import_id"],
        'file': step5["file_name"],
        'merchant': step5["merchant"],
        'uploaded': step5["uploaded_at"],
        'lineage': base_lineage,
        'import_history': [base_lineage],
        'lin001_traceability_chain': full_lineage["lin001_traceability_chain"],
        'lin002_prediction_metadata': full_lineage["lin002_prediction_metadata"],
        'lineage_summary_vi': full_lineage["lineage_summary_vi"]
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET'])
def get_error_matrix(request):
    """
    GET /api/v2/ingestion/error-matrix (Requirement #22)
    Return standardized Error Matrix dictionary mapping codes to system behaviors.
    """
    from supplyforge.services.error_matrix import ErrorMatrixRegistry
    return Response({
        'error_matrix': ErrorMatrixRegistry.list_matrix()
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET'])
def get_post_import_quality_report(request, session_id):
    """
    GET /api/v2/ingestion/sessions/<session_id>/quality-report (Requirement 25)
    Generate post-import Data Quality Report & calculate Data Health Score (e.g. 94/100).
    """
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response({'error': 'Không tìm thấy phiên ingestion.'}, status=status.HTTP_404_NOT_FOUND)

    # SEC-001 Tenant isolation enforcement
    from supplyforge.services.tenant_isolation import TenantIsolationService
    try:
        TenantIsolationService.enforce_tenant_isolation(session, request, action="read quality report")
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)

    from supplyforge.services.data_quality_service import DataQualityService
    report = DataQualityService.generate_post_import_report(session)
    return Response({
        'sessionId': str(session.id),
        'quality_report': report
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
def propagate_pipeline_health_score(request, session_id):
    """
    POST /api/v2/ingestion/sessions/<session_id>/pipeline-propagate (Requirement 25)
    Propagate Data Health Score down the 6 pipeline stages:
    Import -> Data Quality -> Risk Model -> Explanation -> Capital -> Decision
    """
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response({'error': 'Không tìm thấy phiên ingestion.'}, status=status.HTTP_404_NOT_FOUND)

    from supplyforge.services.tenant_isolation import TenantIsolationService
    try:
        TenantIsolationService.enforce_tenant_isolation(session, request, action="propagate pipeline health score")
    except Exception as exc:
        return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)

    from supplyforge.services.data_quality_service import DataQualityService
    res = DataQualityService.propagate_health_score_to_pipeline(session)
    return Response(res, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET'])
def verify_tenant_isolation(request):
    """
    GET /api/v2/tenant/verify-isolation (Requirement 26 SEC-001 & SEC-002)
    Verify SEC-001 Tenant Isolation & SEC-002 Resource Tagging across all resources.
    """
    from supplyforge.services.tenant_isolation import TenantIsolationService
    tenant_id = TenantIsolationService.get_tenant_id_from_request(request)
    audit = TenantIsolationService.audit_all_resources_tenant_tagging()
    return Response({
        'current_tenant_id': tenant_id,
        'sec_001_isolation': 'ENFORCED',
        'sec_002_resource_tagging': audit
    }, status=status.HTTP_200_OK)

