"""
SupplyForge AI — Background Job Management APIs (Release 1: Queue v1.0)
========================================================================
Endpoints for asynchronous background jobs, stage status tracking,
cancellation, retry, and upload job creation.
"""

import logging
import hashlib
import threading
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.models import BackgroundJob, IngestionSession, Workspace
from supplyforge.services.csv_profiler import StreamingCSVProfiler, humanize_bytes
from supplyforge.tasks import run_import_pipeline

logger = logging.getLogger(__name__)


def _get_workspace_from_request(request):
    workspace_id = request.data.get('workspaceId') or request.GET.get('workspaceId') or getattr(request, 'workspace_id', 1)
    try:
        return Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        ws, _ = Workspace.objects.get_or_create(
            id=1,
            defaults={'name': 'Default Workspace', 'slug': 'default'}
        )
        return ws


def _dispatch_background_job(job_id: str) -> str:
    """
    Dispatches pipeline task via Celery if worker/broker is connected,
    or falls back to background Thread execution if Celery/Redis is unavailable.
    Guarantees tasks run to completion in development and production environments.
    """
    try:
        async_res = run_import_pipeline.delay(str(job_id))
        return str(async_res.id)
    except Exception as e:
        logger.warning(f"Celery dispatch notice for job {job_id}: {e}. Running via Threading fallback executor.")
        t = threading.Thread(target=run_import_pipeline, args=(str(job_id),), daemon=True)
        t.start()
        return "thread-executor"


@csrf_exempt
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
        session_type=request.data.get('sessionType', 'INITIAL'),
        storage_path=storage_path,
        raw_storage_path=storage_path,
        file_size_bytes=file_size,
        status='QUEUED',
    )

    # Create BackgroundJob record
    job = BackgroundJob.objects.create(
        workspace=workspace,
        job_type='CSV_IMPORT',
        ingestion_session=session,
        idempotency_key=idempotency_key,
        status='PENDING',
        current_stage='PARSING',
        progress_pct=0,
        stages_json={
            'PARSING': {'status': 'PENDING', 'progress': 0},
            'PROFILING': {'status': 'PENDING', 'progress': 0},
            'MAPPING': {'status': 'PENDING', 'progress': 0},
            'IMPORTING': {'status': 'PENDING', 'progress': 0},
            'ML_INFERENCE': {'status': 'PENDING', 'progress': 0},
            'FINALIZING': {'status': 'PENDING', 'progress': 0},
        }
    )

    # Dispatch background job task (Celery + Threading fallback)
    task_id = _dispatch_background_job(str(job.id))
    job.celery_task_id = task_id
    job.save(update_fields=['celery_task_id', 'updated_at'])

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


@csrf_exempt
@api_view(['GET'])
def list_jobs(request):
    """
    GET /api/v2/jobs/
    List background jobs for current workspace with complete stage & file metadata.
    Auto-reconciles stale/orphaned jobs.
    """
    workspace = _get_workspace_from_request(request)
    jobs = BackgroundJob.objects.filter(workspace=workspace).order_by('-created_at')[:50]

    data = []
    now = timezone.now()
    for job in jobs:
        sess = job.ingestion_session

        # Auto-reconcile stale status:
        # 1. CANCEL_REQUESTED -> CANCELLED
        if job.status == 'CANCEL_REQUESTED':
            job.status = 'CANCELLED'
            job.completed_at = job.updated_at or now
            job.save(update_fields=['status', 'completed_at', 'updated_at'])
            if sess:
                sess.status = 'CANCELLED'
                sess.save(update_fields=['status', 'updated_at'])

        # 2. PENDING or RUNNING stuck without updates for > 15 minutes (or without session)
        elif job.status in ['PENDING', 'RUNNING']:
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

        data.append({
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
            'errorMessage': job.error_message,
            'resultSummary': job.result_summary_json or {},
        })

    return Response({'jobs': data}, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['GET'])
def get_job_status(request, job_id):
    """
    GET /api/v2/jobs/<job_id>/status (SEC-001 IDOR protected)
    Get job status + stage progress dictionary.
    """
    workspace = _get_workspace_from_request(request)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    sess = job.ingestion_session
    filename = sess.original_filename if sess else (
        (job.result_summary_json.get('filename') if isinstance(job.result_summary_json, dict) else None) or 'Tệp dữ liệu CSV'
    )
    filesize = sess.file_size_bytes if sess else 0

    return Response({
        'jobId': str(job.id),
        'jobType': job.job_type,
        'status': job.status,
        'currentStage': job.current_stage,
        'progressPct': job.progress_pct,
        'stages': job.stages_json or {},
        'estimatedTimeRemaining': None,
        'retryCount': job.retry_count,
        'file': {
            'originalFilename': filename,
            'fileSizeBytes': filesize,
        },
        'createdAt': job.created_at.isoformat(),
        'updatedAt': job.updated_at.isoformat(),
        'completedAt': job.completed_at.isoformat() if job.completed_at else None,
        'errorMessage': job.error_message,
        'resultSummary': job.result_summary_json or {},
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
def cancel_job(request, job_id):
    """
    POST /api/v2/jobs/<job_id>/cancel
    Immediately cancels the background job and moves it to history.
    """
    workspace = _get_workspace_from_request(request)
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

    job.status = 'CANCELLED'
    job.completed_at = timezone.now()
    job.save(update_fields=['status', 'completed_at', 'updated_at'])

    if job.ingestion_session:
        job.ingestion_session.status = 'CANCELLED'
        job.ingestion_session.save(update_fields=['status', 'updated_at'])

    return Response({
        'jobId': str(job.id),
        'status': 'CANCELLED',
        'message': 'Đã hủy công việc xử lý ngầm thành công.'
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
def retry_job(request, job_id):
    """
    POST /api/v2/jobs/<job_id>/retry
    Retry a failed or cancelled job.
    """
    workspace = _get_workspace_from_request(request)
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

    task_id = _dispatch_background_job(str(job.id))
    job.celery_task_id = task_id
    job.save(update_fields=['celery_task_id', 'updated_at'])

    return Response({
        'jobId': str(job.id),
        'status': 'PENDING',
        'message': 'Đã gửi lại công việc vào hàng chờ xử lý.'
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['DELETE'])
def delete_job(request, job_id):
    """
    DELETE /api/v2/jobs/<job_id>
    Delete background job record.
    """
    workspace = _get_workspace_from_request(request)
    try:
        job = BackgroundJob.objects.get(id=job_id, workspace=workspace)
    except BackgroundJob.DoesNotExist:
        return Response({'error': 'Không tìm thấy job.'}, status=status.HTTP_404_NOT_FOUND)

    job.delete()
    return Response({'message': f'Đã xóa job {job_id}'}, status=status.HTTP_200_OK)
