"""
SupplyForge AI — Celery Background Tasks
===========================================
All long-running tasks for file imports and Shopee sync operations.
"""

from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from supplyforge.models import BackgroundJob, IngestionSession, NotificationRecord
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.services.ingestion import DynamicFileImportService, GeminiColumnMappingService
from supplyforge.services.storage_backend import StorageBackend
import supplyforge.celery_telemetry

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 30 * 60  # 30 minutes
MAX_REPORTED_PARTITIONS = 200


class ImportCancelled(RuntimeError):
    """Signals a cooperative cancellation at a durable ingestion checkpoint."""


@shared_task(name="health_check_task", bind=True)
def health_check_task(self, worker_type: str = "data_worker") -> dict:
    """
    Task 1.3: Celery Health Check Task.
    Verifies worker execution for Data Worker, ML Worker, or Decision Worker.
    """
    t_start = time.monotonic()
    timestamp = timezone.now().isoformat()
    logger.info(
        f"[CeleryHealthCheck] Task ID={self.request.id} executed successfully for worker_type={worker_type} at {timestamp}"
    )
    from supplyforge.metrics import record_task
    record_task(
        worker_type=worker_type,
        queue=f"{worker_type}_queue" if not worker_type.endswith("_queue") else worker_type,
        task_type="health_check_task",
        status="success",
        duration=time.monotonic() - t_start
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
    stage = dict(stages.get(stage_name, {}))
    stage.update({'status': stage_status, 'progress': stage_pct})
    stages[stage_name] = stage
    job.stages_json = stages
    job.current_stage = stage_name
    job.progress_pct = overall_pct
    job.save(update_fields=['stages_json', 'current_stage', 'progress_pct', 'updated_at'])


def _partition_progress(partition_counts: dict | None) -> dict:
    """Keep job metadata bounded when source data spans many dates."""
    partition_counts = partition_counts or {}
    items = sorted(partition_counts.items())
    visible = dict(items[:MAX_REPORTED_PARTITIONS])
    return {
        'completed': visible,
        'completedCount': len(items),
        'truncated': len(items) > len(visible),
    }


def _import_progress_reporter(job: BackgroundJob, total_rows: int):
    """Persist safe import progress and stop only at chunk/partition boundaries."""
    started = time.monotonic()

    def report(payload: dict) -> None:
        current = BackgroundJob.objects.get(id=job.id)
        if current.status in {'CANCEL_REQUESTED', 'CANCELLED'}:
            raise ImportCancelled('User requested cancellation at a durable checkpoint.')

        processed = max(0, int(payload.get('rowsProcessed') or 0))
        elapsed = time.monotonic() - started
        rate = processed / elapsed if processed and elapsed else 0
        remaining = max(0, total_rows - processed) if total_rows else None
        eta_seconds = int(remaining / rate) if remaining is not None and rate else None
        phase = payload.get('phase', 'IMPORTING')
        completion_ratio = min(1.0, processed / total_rows) if total_rows else 0.0
        if phase == 'SILVER':
            stage_pct = 20 + int(35 * completion_ratio)
            overall_pct = 60 + int(8 * completion_ratio)
        else:
            stage_pct = 55 + int(40 * completion_ratio)
            overall_pct = 68 + int(10 * completion_ratio)

        stages = current.stages_json or {}
        stage = dict(stages.get('IMPORTING', {}))
        timestamp = timezone.now()
        stage.update({
            'status': 'PROCESSING',
            'progress': min(stage_pct, 95),
            'phase': phase,
            'rowsProcessed': processed,
            'totalRows': total_rows or None,
            'rowsRemaining': remaining,
            'filesWritten': int(payload.get('filesWritten') or 0),
            'batchNumber': int(payload.get('batchNumber') or 0),
            'partitionProgress': _partition_progress(payload.get('partitionCounts')),
            'elapsedSeconds': round(elapsed, 1),
            'estimatedTimeRemainingSeconds': eta_seconds,
            'estimatedCompletionAt': (
                (timestamp + timedelta(seconds=eta_seconds)).isoformat()
                if eta_seconds is not None else None
            ),
            'checkpoint': {
                'phase': phase,
                'rowsCompleted': processed,
                'at': timestamp.isoformat(),
            },
        })
        stages['IMPORTING'] = stage
        current.stages_json = stages
        current.current_stage = 'IMPORTING'
        current.progress_pct = min(overall_pct, 79)
        current.save(update_fields=['stages_json', 'current_stage', 'progress_pct', 'updated_at'])

    return report


def _mark_import_published(job: BackgroundJob) -> None:
    """Dataset replacement is irreversible after promotion, so cancel becomes too late."""
    current = BackgroundJob.objects.get(id=job.id)
    stages = current.stages_json or {}
    stage = dict(stages.get('IMPORTING', {}))
    checkpoint = dict(stage.get('checkpoint', {}))
    checkpoint.update({'phase': 'PUBLISHED', 'at': timezone.now().isoformat()})
    stage['checkpoint'] = checkpoint
    if current.status == 'CANCEL_REQUESTED':
        current.status = 'RUNNING'
        stage['cancellation'] = {'status': 'TOO_LATE', 'message': 'Dataset đã được publish.'}
    stages['IMPORTING'] = stage
    current.stages_json = stages
    current.save(update_fields=['status', 'stages_json', 'updated_at'])


def _import_is_published(job: BackgroundJob) -> bool:
    stages = job.stages_json or {}
    checkpoint = (stages.get('IMPORTING') or {}).get('checkpoint') or {}
    return checkpoint.get('phase') == 'PUBLISHED'


def _mark_job_cancelled(job: BackgroundJob, reason: str) -> dict:
    """Cancel a job and preserve lake artifacts for a later idempotent retry."""
    job.refresh_from_db()
    job.status = 'CANCELLED'
    job.completed_at = timezone.now()
    stages = job.stages_json or {}
    stage = dict(stages.get(job.current_stage or 'IMPORTING', {}))
    stage.update({'status': 'CANCELLED', 'cancellationReason': reason})
    stages[job.current_stage or 'IMPORTING'] = stage
    job.stages_json = stages
    job.save(update_fields=['status', 'completed_at', 'stages_json', 'updated_at'])
    if job.ingestion_session:
        job.ingestion_session.status = 'CANCELLED'
        job.ingestion_session.save(update_fields=['status', 'updated_at'])
        try:
            from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService

            LakehouseIngestionService.mark_cancelled(job.ingestion_session, reason)
        except Exception:
            logger.exception('Could not mark lake dataset version as cancelled for job %s.', job.id)
    return {'cancelled': True, 'last_stage': job.current_stage}


def _stage_parse(job: BackgroundJob, context: dict) -> dict:
    session = job.ingestion_session
    if not session or not session.storage_path:
        raise FileNotFoundError(f"Tệp CSV không tồn tại tại đường dẫn {session.storage_path if session else 'N/A'}")

    _update_stage_progress(job, 'PARSING', 50, 'PROCESSING', 10)
    
    headers, sample_rows = [], []
    with StorageBackend.localize(session.storage_path) as local_path:
        if not local_path or not os.path.exists(local_path):
            raise FileNotFoundError('Tệp CSV không tồn tại.')
        with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
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
    if session.raw_storage_path:
        extension = os.path.splitext(session.original_filename)[1].lower() or '.csv'
        session.lake_storage_path = StorageBackend.publish_raw_to_lake(
            session.raw_storage_path,
            f'bronze/workspace-{session.workspace_id}/sessions/{session.id}/source{extension}',
        )
    session.status = 'PROFILED'
    session.save(update_fields=[
        'total_rows', 'total_columns', 'headers_json', 'column_types_json',
        'preview_rows_json', 'missing_values_json', 'dataset_profile_json',
        'lake_storage_path', 'status', 'updated_at'
    ])

    from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService

    dataset_version = LakehouseIngestionService.prepare_version(session)

    context['profile'] = session.dataset_profile_json
    context['dataset_version_id'] = str(dataset_version.id)
    context['dataset_version'] = dataset_version.version_label
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

    from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService

    dataset_version = LakehouseIngestionService.prepare_version(session)
    progress_report = _import_progress_reporter(job, session.total_rows or 0)
    with StorageBackend.localize(session.storage_path) as local_path:
        # Silver is generated before mutating the operational projection. A
        # failed lake transform leaves the previously active dataset untouched.
        silver_manifest = LakehouseIngestionService.materialize_silver(
            dataset_version,
            local_path,
            mapping_rule,
            progress_callback=progress_report,
        )
        import_res = LakehouseIngestionService.completed_import_result(dataset_version)
        if import_res is None:
            silver_progress = {
                'filesWritten': silver_manifest.get('filesWritten', 0),
                'partitionCounts': silver_manifest.get('partitionCounts', {}),
            }
            progress_report({
                'phase': 'OPERATIONAL_IMPORT',
                'rowsProcessed': 0,
                **silver_progress,
            })
            import_res = DynamicFileImportService.process_file_in_chunks(
                file_path=local_path,
                mapping_rule=mapping_rule,
                user_id=job.workspace.owner_id or job.workspace_id,
                session_type=session.session_type,
                session_id=str(session.id),
                workspace_id=job.workspace_id,
                force_reset=session.session_type == 'INITIAL',
                chunk_size=settings.INGESTION_CHUNK_ROW_SIZE,
                progress_callback=lambda payload: progress_report({
                    **payload,
                    **silver_progress,
                }),
            )
            LakehouseIngestionService.record_import_result(dataset_version, import_res)

        gold_payload = LakehouseIngestionService.materialize_gold(dataset_version)
        dataset_version = LakehouseIngestionService.promote(dataset_version)
        _mark_import_published(job)

    context['import_result'] = import_res
    context['dataset_version'] = dataset_version.version_label
    context['data_as_of'] = dataset_version.data_as_of.isoformat()
    context['lake_reconciliation'] = gold_payload['reconciliation']
    context['silver_manifest'] = silver_manifest
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

    dataset_version_id = context.get('dataset_version_id')
    if dataset_version_id:
        try:
            from supplyforge.models import DatasetVersion
            from supplyforge.services.mlops_governance import FeatureSnapshotService

            version = DatasetVersion.objects.get(
                id=dataset_version_id,
                workspace_id=job.workspace_id,
            )
            context['feature_snapshot'] = FeatureSnapshotService.materialize_from_assessments(version)
        except Exception as exc:
            # Snapshots are retriable from the immutable risk assessment data.
            logger.warning('Feature snapshot materialization notice for job %s: %s', job.id, exc)

        try:
            from supplyforge.models import DatasetVersion
            from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService

            version = DatasetVersion.objects.get(
                id=dataset_version_id,
                workspace_id=job.workspace_id,
            )
            context['dashboard_summary'] = LakehouseIngestionService.materialize_dashboard_gold(version)
        except Exception as exc:
            # The dashboard can safely use its legacy aggregate while a later
            # batch retries this optional read-model materialization.
            logger.warning('Dashboard gold materialization notice for job %s: %s', job.id, exc)

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
        'filename': session.original_filename,
        'datasetVersion': context.get('dataset_version', session.dataset_version),
        'dataAsOf': context.get('data_as_of'),
        'reconciliation': context.get('lake_reconciliation'),
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
        return _mark_job_cancelled(job, 'User requested cancellation before the job started.')

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
            job.refresh_from_db()
            if _import_is_published(job):
                _mark_import_published(job)
                continue
            return _mark_job_cancelled(job, f'User requested cancellation before {stage_name}.')

        try:
            context = stage_fn(job, context)
        except ImportCancelled as exc:
            return _mark_job_cancelled(job, str(exc))
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
                    try:
                        from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService

                        LakehouseIngestionService.mark_failed(job.ingestion_session, str(exc))
                    except Exception:
                        logger.exception('Could not mark lake dataset version as failed for job %s.', job_id)

                from supplyforge.metrics import record_task
                record_task(worker_type='data', queue='data_worker', task_type='run_import_pipeline', status='failed')
                return {'failed': True, 'stage': stage_name, 'error': str(exc)}

    # All stages complete
    job.status = 'COMPLETED'
    job.progress_pct = 100
    job.completed_at = timezone.now()
    job.save(update_fields=['status', 'progress_pct', 'completed_at', 'updated_at'])

    from supplyforge.metrics import record_task
    record_task(worker_type='data', queue='data_worker', task_type='run_import_pipeline', status='success')

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
        
        with StorageBackend.localize(file_path) as local_path:
            with open(local_path, 'rb') as f:
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
