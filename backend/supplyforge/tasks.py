"""
SupplyForge AI — Celery Background Tasks
===========================================
All long-running tasks for file imports and Shopee sync operations.
"""

from __future__ import annotations

import os
import logging
import time
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from supplyforge.models import BackgroundJob, IngestionSession, NotificationRecord
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.services.ingestion import DynamicFileImportService, GeminiColumnMappingService

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 30 * 60  # 30 minutes


@shared_task(name="health_check_task", bind=True)
def health_check_task(self, worker_type: str = "data_worker") -> dict:
    """
    Task 1.3: Celery Health Check Task.
    Verifies worker execution for Data Worker, ML Worker, or Decision Worker.
    """
    timestamp = timezone.now().isoformat()
    logger.info(
        f"[CeleryHealthCheck] Task ID={self.request.id} executed successfully for worker_type={worker_type} at {timestamp}"
    )
    return {
        "status": "ok",
        "worker_type": worker_type,
        "task_id": str(self.request.id),
        "timestamp": timestamp,
    }


def _acquire_redis_lock(lock_key: str, ttl: int = LOCK_TTL_SECONDS) -> bool:
    import redis as redis_lib

    redis_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    r = redis_lib.from_url(redis_url)

    acquired = r.set(lock_key, 'locked', nx=True, ex=ttl)
    return bool(acquired)


def _release_redis_lock(lock_key: str) -> None:
    import redis as redis_lib

    redis_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    r = redis_lib.from_url(redis_url)
    r.delete(lock_key)


# ============================================================
# Single Orchestrator Task for CSV Import Pipeline (Release 1)
# ============================================================

def _update_stage_progress(job: BackgroundJob, stage_name: str, stage_pct: int, stage_status: str, overall_pct: int):
    stages = job.stages_json or {}
    stages[stage_name] = {'status': stage_status, 'progress': stage_pct}
    job.stages_json = stages
    job.current_stage = stage_name
    job.progress_pct = overall_pct
    job.save(update_fields=['stages_json', 'current_stage', 'progress_pct', 'updated_at'])


def _stage_parse(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    if not session or not session.storage_path or not os.path.exists(session.storage_path):
        raise FileNotFoundError(f"Tệp CSV không tồn tại tại đường dẫn {session.storage_path if session else 'N/A'}")

    _update_stage_progress(job, 'PARSING', 50, 'PROCESSING', 10)
    
    headers, sample_rows = [], []
    with open(session.storage_path, 'r', encoding='utf-8', errors='ignore') as f:
        headers, sample_rows = DynamicFileImportService.peek_sample_data(f)

    if not headers:
        raise ValueError("Tệp CSV rỗng hoặc không đúng định dạng.")

    context['headers'] = headers
    context['sample_rows'] = sample_rows
    _update_stage_progress(job, 'PARSING', 100, 'COMPLETED', 15)
    return context


def _stage_profile(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    _update_stage_progress(job, 'PROFILING', 30, 'PROCESSING', 25)

    profile = StreamingCSVProfiler.profile_csv(session.storage_path)

    if profile.validation and profile.validation.get('status') == 'REJECT':
        errors = profile.validation.get('errors', [])
        raise ValueError(f"CSV Validation Rejected: {'; '.join(errors)}")

    session.total_rows = profile.total_rows
    session.total_columns = profile.total_columns
    session.headers_json = profile.headers
    session.column_types_json = profile.column_types
    session.preview_rows_json = profile.preview_rows
    session.missing_values_json = profile.missing_values
    session.dataset_profile_json = {
        'totalRows': profile.total_rows,
        'totalColumns': profile.total_columns,
        'headers': profile.headers,
        'columnTypes': profile.column_types,
        'previewRows': profile.preview_rows,
        'missingValues': profile.missing_values,
        'uniqueSkus': getattr(profile, 'unique_skus', getattr(profile, 'unique_sku_count', 0)),
        'dateRange': getattr(profile, 'date_range', {}),
    }
    session.status = 'PROFILED'
    session.save(update_fields=[
        'total_rows', 'total_columns', 'headers_json', 'column_types_json',
        'preview_rows_json', 'missing_values_json', 'dataset_profile_json',
        'status', 'updated_at'
    ])

    context['profile'] = session.dataset_profile_json
    _update_stage_progress(job, 'PROFILING', 100, 'COMPLETED', 35)
    return context


def _stage_mapping(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    _update_stage_progress(job, 'MAPPING', 40, 'PROCESSING', 45)

    headers = context.get('headers', [])
    sample_rows = context.get('sample_rows', [])

    mapping = GeminiColumnMappingService.infer_column_mapping(headers, sample_rows)
    session.column_mapping_json = mapping
    session.status = 'MAPPING'
    session.save(update_fields=['column_mapping_json', 'status', 'updated_at'])

    context['mapping_rule'] = mapping
    _update_stage_progress(job, 'MAPPING', 100, 'COMPLETED', 50)
    return context


def _stage_import(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    mapping_rule = context.get('mapping_rule', {})
    _update_stage_progress(job, 'IMPORTING', 20, 'PROCESSING', 60)

    session.status = 'PROCESSING'
    session.save(update_fields=['status', 'updated_at'])

    with open(session.storage_path, 'rb') as f:
        import_res = DynamicFileImportService.process_batch_import(
            file_obj=f,
            mapping_rule=mapping_rule,
            user_id=1,
            session_type=session.session_type,
            session_id=str(session.id)
        )

    context['import_result'] = import_res
    _update_stage_progress(job, 'IMPORTING', 100, 'COMPLETED', 80)
    return context


def _stage_ml_inference(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    _update_stage_progress(job, 'ML_INFERENCE', 30, 'PROCESSING', 85)

    from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products
    try:
        if session:
            _auto_populate_assessments_from_products(str(session.id))
        context['ml_result'] = {'status': 'SUCCESS'}
    except Exception as e:
        logger.warning(f"Batch ML Inference notice for job {job.id}: {e}")
        context['ml_result'] = {'status': 'SKIPPED_OR_BASELINE'}

    _update_stage_progress(job, 'ML_INFERENCE', 100, 'COMPLETED', 95)
    return context


def _stage_finalize(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    _update_stage_progress(job, 'FINALIZING', 50, 'PROCESSING', 98)

    session.status = 'COMPLETED'
    session.readiness_status = 'COMPLETED'
    session.save(update_fields=['status', 'readiness_status', 'updated_at'])

    # Warmup Redis Cache so UI reads in <0.1s immediately
    try:
        from supplyforge.services.cache_warming_service import CacheWarmingService
        CacheWarmingService.warm_workspace_cache(job.workspace_id)
    except Exception as e:
        logger.warning(f"Cache warming notice in _stage_finalize: {e}")

    import_res = context.get('import_result', {})
    rows_valid = import_res.get('rows_valid', 0) if isinstance(import_res, dict) else 0

    NotificationRecord.objects.create(
        workspace_id=job.workspace_id,
        notification_type=NotificationRecord.TRIGGER_NEW_CRITICAL_SKU,
        title=f"Đã nhập dữ liệu thành công ({session.original_filename})",
        message=f"Đã nhập thành công {rows_valid} dòng sản phẩm từ {session.original_filename}.",
        severity=NotificationRecord.SEVERITY_INFO,
    )

    job.result_summary_json = {
        'rowsProcessed': session.total_rows or rows_valid,
        'rowsValid': rows_valid,
        'session_id': str(session.id),
        'filename': session.original_filename
    }
    _update_stage_progress(job, 'FINALIZING', 100, 'COMPLETED', 100)
    return context


@shared_task(bind=True, queue='data_worker', max_retries=2, default_retry_delay=30)
def run_import_pipeline(self, job_id: str):
    """
    Single Orchestrator Task: runs 6 stages sequentially with cooperative cancellation.
    Idempotent & safe to retry.
    """
    try:
        job = BackgroundJob.objects.get(id=job_id)
    except BackgroundJob.DoesNotExist:
        logger.error(f"run_import_pipeline: Job {job_id} not found.")
        return {'error': 'Job not found'}

    if job.status in ['CANCEL_REQUESTED', 'CANCELLED']:
        job.status = 'CANCELLED'
        job.save(update_fields=['status', 'updated_at'])
        if job.ingestion_session:
            job.ingestion_session.status = 'CANCELLED'
            job.ingestion_session.save(update_fields=['status', 'updated_at'])
        return {'cancelled': True}

    job.status = 'RUNNING'
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id
    job.save(update_fields=['status', 'started_at', 'celery_task_id', 'updated_at'])

    context = {'job_id': job_id}
    stages = [
        ('PARSING',       _stage_parse),
        ('PROFILING',     _stage_profile),
        ('MAPPING',       _stage_mapping),
        ('IMPORTING',     _stage_import),
        ('ML_INFERENCE',  _stage_ml_inference),
        ('FINALIZING',    _stage_finalize),
    ]

    for stage_name, stage_fn in stages:
        # Check cancellation before each stage
        job.refresh_from_db(fields=['status'])
        if job.status in ['CANCEL_REQUESTED', 'CANCELLED']:
            job.status = 'CANCELLED'
            job.save(update_fields=['status', 'updated_at'])
            if job.ingestion_session:
                job.ingestion_session.status = 'CANCELLED'
                job.ingestion_session.save(update_fields=['status', 'updated_at'])
            return {'cancelled': True, 'last_stage': stage_name}

        try:
            context = stage_fn(job, context)
        except Exception as exc:
            logger.exception(f"Error in stage {stage_name} for job {job_id}: {exc}")
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.save(update_fields=['retry_count', 'updated_at'])
                raise self.retry(exc=exc, countdown=30 * job.retry_count)
            else:
                job.status = 'FAILED'
                job.error_message = f"Lỗi tại giai đoạn [{stage_name}]: {str(exc)}"
                job.completed_at = timezone.now()
                job.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
                if job.ingestion_session:
                    job.ingestion_session.status = 'FAILED'
                    job.ingestion_session.error_message = str(exc)
                    job.ingestion_session.save(update_fields=['status', 'error_message', 'updated_at'])
                return {'failed': True, 'stage': stage_name, 'error': str(exc)}

    # All stages complete
    job.status = 'COMPLETED'
    job.progress_pct = 100
    job.completed_at = timezone.now()
    job.save(update_fields=['status', 'progress_pct', 'completed_at', 'updated_at'])

    return context


@shared_task(bind=True)
def process_file_import_async(self, file_path, mapping_rule, user_id):
    """
    Legacy helper task for asynchronous imports.
    """
    self.update_state(state='PROCESSING', meta={'progress': 10, 'message': 'Starting file parse...'})
    
    try:
        time.sleep(1)
        self.update_state(state='PROCESSING', meta={'progress': 40, 'message': 'Executing AI fuzzy matching & column normalization...'})
        
        with open(file_path, 'rb') as f:
            result = DynamicFileImportService.process_batch_import(f, mapping_rule, user_id)
            
        self.update_state(state='PROCESSING', meta={'progress': 90, 'message': 'Saving products to database...'})
        time.sleep(0.5)
        
        return {
            'status': 'SUCCESS',
            'progress': 100,
            'message': 'Import completed successfully.',
            'result': result
        }
    except Exception as e:
        self.update_state(state='FAILURE', meta={'progress': 100, 'message': str(e)})
        raise e


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def sync_shopee_products_task(self, connection_id: int) -> dict | None:
    """
    Celery task: delta-sync products & variations for a given ShopeeConnection.
    """
    lock_key = f'shopee_sync_products_lock:{connection_id}'

    if not _acquire_redis_lock(lock_key):
        logger.info(
            '[CeleryTask] sync_shopee_products_task SKIPPED for connection_id=%d — lock held.',
            connection_id,
        )
        return None

    try:
        from supplyforge.models import SyncLog
        from supplyforge.services.shopee_sync import ShopeeSyncService

        last_sync = (
            SyncLog.objects
            .filter(
                connection_id=connection_id,
                sync_type='PRODUCT',
                event_type='SYNC_COMPLETED',
            )
            .order_by('-finished_at')
            .values_list('finished_at', flat=True)
            .first()
        )

        if last_sync:
            time_from = int(last_sync.timestamp())
        else:
            time_from = int(time.time()) - (30 * 24 * 3600)

        time_to = int(time.time())

        logger.info(
            '[CeleryTask] sync_shopee_products_task START connection_id=%d window=[%d → %d]',
            connection_id, time_from, time_to,
        )

        stats = ShopeeSyncService.sync_products(connection_id, time_from, time_to)

        logger.info(
            '[CeleryTask] sync_shopee_products_task DONE connection_id=%d stats=%s',
            connection_id, stats,
        )
        return stats

    except Exception as exc:
        logger.exception(
            '[CeleryTask] sync_shopee_products_task FAILED connection_id=%d',
            connection_id,
        )
        raise self.retry(exc=exc)

    finally:
        _release_redis_lock(lock_key)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def sync_shopee_orders_task(self, connection_id: int) -> dict | None:
    """
    Celery task: delta-sync orders for a given ShopeeConnection.
    """
    lock_key = f'shopee_sync_orders_lock:{connection_id}'

    if not _acquire_redis_lock(lock_key):
        logger.info(
            '[CeleryTask] sync_shopee_orders_task SKIPPED for connection_id=%d — lock held.',
            connection_id,
        )
        return None

    try:
        from supplyforge.models import SyncLog
        from supplyforge.services.shopee_sync import ShopeeSyncService

        last_sync = (
            SyncLog.objects
            .filter(
                connection_id=connection_id,
                sync_type='ORDER',
                event_type='SYNC_COMPLETED',
            )
            .order_by('-finished_at')
            .values_list('finished_at', flat=True)
            .first()
        )

        if last_sync:
            time_from = int(last_sync.timestamp())
        else:
            time_from = int(time.time()) - (15 * 24 * 3600)

        time_to = int(time.time())

        logger.info(
            '[CeleryTask] sync_shopee_orders_task START connection_id=%d window=[%d → %d]',
            connection_id, time_from, time_to,
        )

        stats = ShopeeSyncService.sync_orders(connection_id, time_from, time_to)

        logger.info(
            '[CeleryTask] sync_shopee_orders_task DONE connection_id=%d stats=%s',
            connection_id, stats,
        )
        return stats

    except Exception as exc:
        logger.exception(
            '[CeleryTask] sync_shopee_orders_task FAILED connection_id=%d',
            connection_id,
        )
        raise self.retry(exc=exc)

    finally:
        _release_redis_lock(lock_key)
