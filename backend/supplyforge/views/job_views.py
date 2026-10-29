"""
SupplyForge AI — Background Job Management APIs (Release 1: Queue v1.0)
========================================================================
Endpoints for asynchronous background jobs, stage status tracking,
cancellation, retry, and upload job creation.
"""

import logging
import hashlib
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.models import BackgroundJob, IngestionSession, Workspace
from supplyforge.services.csv_profiler import StreamingCSVProfiler, humanize_bytes
from supplyforge.services.ingestion_jobs import (
    ImportJobDispatchError,
    create_or_get_import_job,
    dispatch_import_job,
)
from supplyforge.services.s3_multipart_ingestion import (
    MultipartUploadError,
    S3MultipartIngestionService,
)

logger = logging.getLogger(__name__)


def _safe_job_error(job):
    """Do not expose worker exceptions or internal paths in API payloads."""
    if job.status == 'FAILED' and job.error_message:
        return 'Tiến trình import thất bại. Vui lòng thử lại.'
    return job.error_message


def _dataset_metadata(session):
    """Expose a safe freshness marker without leaking lake object paths."""
    if not session:
        return {'datasetVersion': None, 'dataAsOf': None, 'isStale': True}
    try:
        version = session.dataset_version_record
    except Exception:
        version = None
    return {
        'datasetVersion': version.version_label if version else session.dataset_version,
        'dataAsOf': version.data_as_of.isoformat() if version and version.data_as_of else None,
        'isStale': not bool(version and version.status == 'ACTIVE'),
    }


def _execution_metadata(job):
    """Expose bounded worker progress without storage paths or internal errors."""
    importing = (job.stages_json or {}).get('IMPORTING') or {}
    return {
        'estimatedTimeRemaining': importing.get('estimatedTimeRemainingSeconds'),
        'estimatedCompletionAt': importing.get('estimatedCompletionAt'),
        'partitionProgress': importing.get('partitionProgress'),
        'checkpoint': importing.get('checkpoint'),
        'importPhase': importing.get('phase'),
    }


def _import_is_published(job):
    checkpoint = ((job.stages_json or {}).get('IMPORTING') or {}).get('checkpoint') or {}
    return checkpoint.get('phase') == 'PUBLISHED'


def _get_workspace_from_request(request):
    """Resolve only the workspace supplied by validated middleware context."""
    if not (
        getattr(request, 'tenant_context_validated', False)
        and getattr(request, 'workspace_id', None)
    ):
        return None
    workspace_id = request.workspace_id
    try:
        return Workspace.objects.get(id=int(workspace_id))
    except Workspace.DoesNotExist:
        return None


def _dispatch_background_job(job_id: str) -> str:
    """
    Dispatches pipeline task via Celery if worker/broker is connected,
    or falls back to background Thread execution if Celery/Redis is unavailable.
    Guarantees tasks run to completion in development and production environments.
    """
    return dispatch_import_job(BackgroundJob.objects.get(id=job_id))


@api_view(['POST'])
def enqueue_upload_job(request):
    """
    POST /api/v2/ingestion/upload
    Asynchronously enqueue CSV upload job. Returns HTTP 202 Accepted + jobId.
    All CSV imports run asynchronously.
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

    MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024
    if file_obj.size > MAX_FILE_SIZE_BYTES:
        return Response(
            {'error': f'Dung lượng tệp CSV quá lớn ({humanize_bytes(file_obj.size)}, vượt quá giới hạn 500 MB).'},
            status=status.HTTP_400_BAD_REQUEST
        )

    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)

    session_type = request.data.get('sessionType', 'INITIAL')
    if session_type not in {'INITIAL', 'INCREMENTAL'}:
        return Response({'error': 'sessionType không hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)

    # Compute SHA256 file fingerprint
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    file_hash = hasher.hexdigest()
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    # Idempotency check: SHA256 + workspace_id + job_type
    idempotency_key = f"{file_hash}:{workspace.id}:CSV_IMPORT"

    existing_job = BackgroundJob.objects.filter(
        workspace=workspace,
        idempotency_key=idempotency_key,
        status__in=['PENDING', 'RUNNING']
    ).first()

    if existing_job:
        return Response({
            'jobId': str(existing_job.id),
            'sessionId': str(existing_job.ingestion_session.id) if existing_job.ingestion_session else None,
            'status': existing_job.status,
            'idempotent_retry': True,
            'message': f'Phát hiện job đang chạy trùng lặp. Trả về jobId {existing_job.id}.',
            'file': {
                'originalFilename': existing_job.ingestion_session.original_filename if existing_job.ingestion_session else file_obj.name,
                'fileSizeBytes': existing_job.ingestion_session.file_size_bytes if existing_job.ingestion_session else file_obj.size,
                'fileHash': file_hash
            }
        }, status=status.HTTP_200_OK)

    # Save file to disk streaming
    storage_path, file_size = StreamingCSVProfiler.save_uploaded_file(file_obj)

    # Create IngestionSession record
    session = IngestionSession.objects.create(
        workspace=workspace,
        original_filename=file_obj.name,
        file_hash=file_hash,
        idempotency_key=idempotency_key,
        session_type=session_type,
        storage_path=storage_path,
        raw_storage_path=storage_path,
        file_size_bytes=file_size,
        status='QUEUED',
    )

    job, _ = create_or_get_import_job(session, idempotency_key)

    try:
        _dispatch_background_job(str(job.id))
    except ImportJobDispatchError:
        return Response({
            'error': 'Không thể đưa tệp vào hàng chờ xử lý. Vui lòng thử lại sau.',
            'code': 'QUEUE_UNAVAILABLE',
            'jobId': str(job.id),
            'sessionId': str(session.id),
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({
        'jobId': str(job.id),
        'sessionId': str(session.id),
        'status': 'PENDING',
        'message': 'Đã đưa tệp vào hàng chờ xử lý ngầm (Background Job Queue).',
        'file': {
            'originalFilename': file_obj.name,
            'fileSizeBytes': file_size,
            'fileHash': file_hash
        }
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
def initiate_s3_multipart_upload(request):
    """Create a tenant-scoped multipart manifest without proxying the CSV."""
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)

    data = request.data
    client_key = request.headers.get('Idempotency-Key') or data.get('idempotencyKey', '')
    try:
        payload = S3MultipartIngestionService.initiate(
            workspace,
            filename=data.get('filename', ''),
            size_bytes=data.get('sizeBytes'),
            content_type=data.get('contentType', 'text/csv'),
            session_type=data.get('sessionType', 'INITIAL'),
            client_idempotency_key=client_key,
        )
    except MultipartUploadError as exc:
        return Response(
            {'error': str(exc), 'code': 'S3_MULTIPART_INVALID'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception('Unable to initiate S3 multipart upload.')
        return Response({
            'error': 'Không thể khởi tạo cloud upload. Vui lòng thử lại.',
            'code': 'S3_MULTIPART_INIT_FAILED',
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    response_status = status.HTTP_200_OK if payload['idempotentRetry'] else status.HTTP_201_CREATED
    return Response(payload, status=response_status)


@api_view(['POST'])
def complete_s3_multipart_upload(request, session_id):
    """Complete one upload and idempotently enqueue its import job."""
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)

    try:
        payload, created = S3MultipartIngestionService.complete(
            workspace,
            str(session_id),
            upload_id=request.data.get('uploadId', ''),
            parts=request.data.get('parts'),
        )
    except MultipartUploadError as exc:
        return Response(
            {'error': str(exc), 'code': 'S3_MULTIPART_INVALID'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception('Unable to complete S3 multipart upload for session %s.', session_id)
        return Response({
            'error': 'Không thể hoàn tất cloud upload. Vui lòng thử lại.',
            'code': 'S3_MULTIPART_COMPLETE_FAILED',
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    payload['idempotentRetry'] = not created
    return Response(payload, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
def list_jobs(request):
    """
    GET /api/v2/jobs/
    List background jobs for current workspace with complete stage & file metadata.
    Auto-reconciles stale/orphaned jobs.
    """
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    active_only = str(request.query_params.get('active_only', '')).lower() in {'1', 'true', 'yes'}
    jobs_query = BackgroundJob.objects.filter(workspace=workspace).select_related(
        'ingestion_session__dataset_version_record',
    )
    if active_only:
        jobs_query = jobs_query.filter(status__in=['PENDING', 'RUNNING', 'CANCEL_REQUESTED'])
    jobs = jobs_query.order_by('-created_at')[:50]

    data = []
    now = timezone.now()
    for job in jobs:
        sess = job.ingestion_session

        # Auto-reconcile only stale active workers. Cancellation remains
        # requested until the worker reaches its next durable checkpoint.
        if job.status in ['PENDING', 'RUNNING']:
            time_since_update = (now - (job.updated_at or job.created_at)).total_seconds()
            if time_since_update > 900 or not sess:  # 15 mins or missing session
                job.status = 'FAILED'
                job.error_message = job.error_message or 'Tiến trình bị gián đoạn do hệ thống khởi động lại. Vui lòng nhấn Thử lại.'
                job.completed_at = now
                job.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])

        filename = sess.original_filename if sess else (
            (job.result_summary_json.get('filename') if isinstance(job.result_summary_json, dict) else None) or 'Tệp dữ liệu CSV'
        )
        filesize = sess.file_size_bytes if sess else 0

        job_payload = {
            'jobId': str(job.id),
            'jobType': job.job_type,
            'status': job.status,
            'currentStage': job.current_stage,
            'progressPct': job.progress_pct,
            'stages': job.stages_json or {},
            'retryCount': job.retry_count,
            'file': {
                'originalFilename': filename,
                'fileSizeBytes': filesize,
            },
            'createdAt': job.created_at.isoformat(),
            'updatedAt': job.updated_at.isoformat() if job.updated_at else None,
            'completedAt': job.completed_at.isoformat() if job.completed_at else None,
            'errorMessage': _safe_job_error(job),
            'resultSummary': job.result_summary_json or {},
        }
        job_payload.update(_dataset_metadata(sess))
        job_payload.update(_execution_metadata(job))
        data.append(job_payload)

    return Response({'jobs': data, 'activeOnly': active_only}, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_job_status(request, job_id):
    """
    GET /api/v2/jobs/<job_id>/status (SEC-001 IDOR protected)
    Get job status + stage progress dictionary.
    """
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    sess = job.ingestion_session
    filename = sess.original_filename if sess else (
        (job.result_summary_json.get('filename') if isinstance(job.result_summary_json, dict) else None) or 'Tệp dữ liệu CSV'
    )
    filesize = sess.file_size_bytes if sess else 0

    payload = {
        'jobId': str(job.id),
        'jobType': job.job_type,
        'status': job.status,
        'currentStage': job.current_stage,
        'progressPct': job.progress_pct,
        'stages': job.stages_json or {},
        'retryCount': job.retry_count,
        'file': {
            'originalFilename': filename,
            'fileSizeBytes': filesize,
        },
        'createdAt': job.created_at.isoformat(),
        'updatedAt': job.updated_at.isoformat(),
        'completedAt': job.completed_at.isoformat() if job.completed_at else None,
        'errorMessage': _safe_job_error(job),
        'resultSummary': job.result_summary_json or {},
    }
    payload.update(_dataset_metadata(sess))
    payload.update(_execution_metadata(job))
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
def cancel_job(request, job_id):
    """
    POST /api/v2/jobs/<job_id>/cancel
    Requests cooperative cancellation at the next durable worker checkpoint.
    """
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    if job.status in ['COMPLETED', 'FAILED', 'CANCELLED']:
        return Response({
            'jobId': str(job.id),
            'status': job.status,
            'message': f'Job đã ở trạng thái {job.status}, không thể hủy.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if _import_is_published(job):
        return Response({
            'jobId': str(job.id),
            'status': job.status,
            'message': 'Dataset đã được publish, không thể hủy mà không làm mất tính nhất quán.',
        }, status=status.HTTP_409_CONFLICT)

    job.status = 'CANCEL_REQUESTED'
    job.save(update_fields=['status', 'updated_at'])

    return Response({
        'jobId': str(job.id),
        'status': 'CANCEL_REQUESTED',
        'message': 'Đã yêu cầu hủy. Worker sẽ dừng tại checkpoint an toàn kế tiếp.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def retry_job(request, job_id):
    """
    POST /api/v2/jobs/<job_id>/retry
    Retry a failed or cancelled job.
    """
    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    if job.status not in ['FAILED', 'CANCELLED']:
        return Response({
            'jobId': str(job.id),
            'status': job.status,
            'message': 'Chỉ có job FAILED hoặc CANCELLED mới có thể retry.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Re-associate ingestion session if missing
    if not job.ingestion_session:
        latest_session = IngestionSession.objects.filter(workspace=workspace).order_by('-created_at').first()
        if latest_session:
            job.ingestion_session = latest_session
        else:
            session = IngestionSession.objects.create(
                workspace=workspace,
                original_filename='balanced_risk_simulation_orders.csv',
                status='QUEUED'
            )
            job.ingestion_session = session

    job.status = 'PENDING'
    job.progress_pct = 0
    job.error_message = None
    job.completed_at = None
    job.current_stage = 'PARSING'
    job.stages_json = {
        'PARSING': {'status': 'PENDING', 'progress': 0},
        'PROFILING': {'status': 'PENDING', 'progress': 0},
        'MAPPING': {'status': 'PENDING', 'progress': 0},
        'IMPORTING': {'status': 'PENDING', 'progress': 0},
        'ML_INFERENCE': {'status': 'PENDING', 'progress': 0},
        'FINALIZING': {'status': 'PENDING', 'progress': 0},
    }
    job.save(update_fields=['status', 'progress_pct', 'error_message', 'completed_at', 'current_stage', 'stages_json', 'ingestion_session', 'updated_at'])

    try:
        task_id = _dispatch_background_job(str(job.id))
    except ImportJobDispatchError:
        return Response({
            'jobId': str(job.id),
            'status': 'FAILED',
            'error': 'Không thể gửi lại công việc vào hàng chờ xử lý. Vui lòng thử lại sau.',
            'code': 'QUEUE_UNAVAILABLE',
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    job.celery_task_id = task_id
    job.save(update_fields=['celery_task_id', 'updated_at'])

    return Response({
        'jobId': str(job.id),
        'status': 'PENDING',
        'message': 'Đã gửi lại công việc vào hàng chờ xử lý.'
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'DELETE'])
def delete_job(request, job_id):
    """
    GET /api/v2/jobs/<job_id> returns the status contract.
    DELETE /api/v2/jobs/<job_id> deletes the background job record.
    """
    if request.method == 'GET':
        return get_job_status(request, job_id)

    workspace = _get_workspace_from_request(request)
    if workspace is None:
        return Response({
            'error': 'Yêu cầu cần Authorization Bearer token và workspace hợp lệ.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    job.delete()
    return Response({'message': f'Đã xóa job {job_id}'}, status=status.HTTP_200_OK)
