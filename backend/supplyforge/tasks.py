"""
SupplyForge AI — Celery Background Tasks
===========================================
All long-running tasks for file imports and Odoo sync operations.
"""

from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from supplyforge.models import BackgroundJob, IngestionSession, NotificationRecord
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.services.ingestion import DynamicFileImportService, GeminiColumnMappingService
from supplyforge.services.storage_backend import StorageBackend
import supplyforge.celery_telemetry

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 30 * 60  # 30 minutes
MAX_REPORTED_PARTITIONS = 200


@shared_task(
    bind=True,
    queue='integration_worker',
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def run_integration_sync(self, run_id: str) -> dict:
    """Execute a bounded provider validation/sync run outside the HTTP request."""
    from supplyforge.models import BackgroundJob, IntegrationConnection, IntegrationSyncRun
    from supplyforge.services.integration_security import decrypt_credentials
    from supplyforge.services.integration_sync import OdooMetricProjectionService
    from supplyforge.services.integration_health import IntegrationHealthService
    from supplyforge.services.odoo_connector import OdooConnector, OdooConnectorError

    started_monotonic = time.monotonic()
    run = IntegrationSyncRun.objects.select_related('connection', 'connection__workspace', 'background_job').get(id=run_id)
    connection = run.connection
    job = run.background_job
    lock_key = f'integration-sync:{connection.id}'
    if not cache.add(lock_key, 'locked', timeout=LOCK_TTL_SECONDS):
        # A duplicate trigger must not remain PENDING forever. The caller can
        # inspect this terminal run and the connection keeps its current data.
        IntegrationSyncRun.objects.filter(id=run.id).update(
            status='FAILED',
            finished_at=timezone.now(),
            error_code='SYNC_ALREADY_RUNNING',
            error_message='Một lượt đồng bộ khác của kết nối này đang chạy.',
        )
        if job:
            BackgroundJob.objects.filter(id=job.id).update(
                status='FAILED',
                error_message='Một lượt đồng bộ khác đang chạy.',
                completed_at=timezone.now(),
            )
        return {'status': 'SKIPPED', 'reason': 'connection_lock_held'}
    started = timezone.now()
    try:
        run.status, run.started_at = 'RUNNING', started
        run.save(update_fields=['status', 'started_at'])
        connection.status = 'VALIDATING'
        connection.save(update_fields=['status', 'updated_at'])
        if job:
            BackgroundJob.objects.filter(id=job.id).update(status='RUNNING', progress_pct=20, current_stage='INTEGRATION_SYNC')
        if connection.provider != 'ODOO':
            raise ValueError('SupplyForge chỉ hỗ trợ kết nối Odoo.')
        credentials = decrypt_credentials(connection.credential_encrypted)
        connector = OdooConnector(connection.base_url, credentials['database'], credentials['username'], credentials['api_key'])
        projection = OdooMetricProjectionService(connection, connector)
        if run.run_type == 'VALIDATE':
            summary = projection.validate_and_discover()
        else:
            summary = projection.sync(run.run_type)
        summary['refresh'] = '15_MINUTES_PULL'
        summary['provider'] = connection.provider
        summary['run_type'] = run.run_type
        # Validation alone only proves that the service account is valid. A
        # connection becomes active after the merchant has selected a company
        # and at least one warehouse, preventing empty scheduled pulls.
        connection.status = (
            'ACTIVE' if connection.external_company_id and connection.warehouse_ids else 'DRAFT'
        ) if connection.provider == 'ODOO' else 'ACTIVE'
        connection.last_successful_sync_at = timezone.now()
        connection.last_error_code = ''
        connection.last_error_message = ''
        connection.cursor_json = {
            **(connection.cursor_json or {}),
            'last_successful_run_type': run.run_type,
            'last_successful_sync_at': connection.last_successful_sync_at.isoformat(),
            'history_start': summary.get('history_start') or (connection.cursor_json or {}).get('history_start'),
        }
        if summary.get('discovery'):
            connection.cursor_json['discovery'] = summary['discovery']
        connection.save(update_fields=['status', 'last_successful_sync_at', 'last_error_code', 'last_error_message', 'cursor_json', 'updated_at'])
        # A sync worker is the only place that materialises the operational
        # dashboard source. CSV/LightGBM assessments remain untouched.
        if run.run_type in {'INITIAL', 'INCREMENTAL'} and connection.provider == 'ODOO':
            try:
                from supplyforge.services.operational_analytics import OdooOperationalAnalyticsService
                summary['operational_analytics'] = OdooOperationalAnalyticsService.refresh(connection)
            except Exception:
                # Raw ERP projection has already completed successfully. Keep
                # it available for reconciliation and retry dashboard
                # materialisation separately rather than reporting a false
                # source-sync failure to the merchant.
                logger.exception('Operational Odoo analytics refresh failed for connection=%s', connection.id)
                summary['operational_analytics'] = {
                    'status': 'FAILED',
                    'reason': 'ANALYTICS_REFRESH_FAILED',
                }
            try:
                from supplyforge.services.erp_inventory_snapshot import ErpInventorySnapshotProjectionService
                summary['inventory_snapshot_projection'] = ErpInventorySnapshotProjectionService.refresh(connection)
            except Exception:
                logger.exception('ERP inventory snapshot projection failed for connection=%s', connection.id)
                summary['inventory_snapshot_projection'] = {
                    'status': 'FAILED',
                    'reason': 'INVENTORY_SNAPSHOT_PROJECTION_FAILED',
                }
            try:
                from supplyforge.services.action_outcome_reconciliation import ActionOutcomeReconciliationService
                summary['action_outcome_reconciliation'] = ActionOutcomeReconciliationService.reconcile_connection(
                    connection=connection
                )
            except Exception:
                logger.exception('ERP action outcome reconciliation failed for connection=%s', connection.id)
                summary['action_outcome_reconciliation'] = {
                    'status': 'FAILED',
                    'reason': 'ACTION_OUTCOME_RECONCILIATION_FAILED',
                }
        if run.run_type in {'INITIAL', 'INCREMENTAL'}:
            summary['data_health'] = IntegrationHealthService.refresh(connection)
        run.status, run.finished_at, run.summary, run.cursor_after = 'COMPLETED', timezone.now(), summary, connection.cursor_json
        run.save(update_fields=['status', 'finished_at', 'summary', 'cursor_after'])
        if job:
            BackgroundJob.objects.filter(id=job.id).update(status='COMPLETED', progress_pct=100, completed_at=timezone.now(), result_summary_json=summary)
        from supplyforge.metrics import record_erp_sync
        record_erp_sync(
            provider=connection.provider,
            run_type=run.run_type,
            status='success',
            duration=time.monotonic() - started_monotonic,
            summary=summary,
        )
        return summary
    except Exception as exc:
        logger.exception('Integration sync failed for run=%s', run_id)
        code = f'{connection.provider}_SYNC_FAILED' if run.run_type != 'VALIDATE' else 'CONNECTION_VALIDATION_FAILED'
        public_message = str(exc)[:512] if isinstance(exc, (OdooConnectorError, ValueError)) else 'Không thể xác thực hoặc đọc dữ liệu từ Odoo.'
        IntegrationConnection.objects.filter(id=connection.id).update(status='ERROR', last_error_code=code, last_error_message=public_message)
        IntegrationSyncRun.objects.filter(id=run.id).update(status='FAILED', finished_at=timezone.now(), error_code=code, error_message=public_message)
        if job:
            BackgroundJob.objects.filter(id=job.id).update(status='FAILED', error_message=f'Đồng bộ {connection.display_name} thất bại.', completed_at=timezone.now())
        from supplyforge.metrics import record_erp_sync
        record_erp_sync(
            provider=connection.provider,
            run_type=run.run_type,
            status='failed',
            duration=time.monotonic() - started_monotonic,
        )
        raise
    finally:
        cache.delete(lock_key)


@shared_task(
    bind=True,
    queue='integration_worker',
    max_retries=1,
    default_retry_delay=15,
    acks_late=True,
)
def refresh_integration_operational_analytics(self, connection_id: str) -> dict:
    """Refresh the affected read model after a governed SKU mapping change."""
    from supplyforge.models import IntegrationConnection

    connection = IntegrationConnection.objects.get(id=connection_id)
    if connection.provider != IntegrationConnection.PROVIDER_ODOO:
        raise ValueError('SupplyForge chỉ hỗ trợ kết nối Odoo.')
    from supplyforge.services.operational_analytics import OdooOperationalAnalyticsService
    return OdooOperationalAnalyticsService.refresh(connection)


@shared_task(
    bind=True,
    queue='integration_worker',
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def process_integration_event(self, event_id: str) -> dict:
    """Idempotently classify webhook events and surface unmapped external SKUs."""
    from supplyforge.models import BackgroundJob, IntegrationEvent, IntegrationSkuMapping, IntegrationSyncRun

    event = IntegrationEvent.objects.select_related('connection').get(id=event_id)
    if event.status in {'PROCESSED', 'NEEDS_MAPPING'}:
        return {'status': event.status, 'idempotent': True}
    event.status = 'PROCESSING'
    event.save(update_fields=['status'])
    payload = event.payload or {}
    sku = str(payload.get('sku') or payload.get('default_code') or '').strip()
    if sku:
        mapping, _ = IntegrationSkuMapping.objects.get_or_create(
            connection=event.connection, external_sku=sku,
            defaults={'external_name': str(payload.get('name') or '')[:512], 'status': 'NEEDS_REVIEW'},
        )
        event.status = 'PROCESSED' if mapping.status in {'AUTO_MAPPED', 'CONFIRMED'} else 'NEEDS_MAPPING'
    else:
        event.status = 'PROCESSED'
    event.processed_at = timezone.now()
    event.save(update_fields=['status', 'processed_at'])
    # Odoo webhooks are treated only as a signed acceleration signal. The
    # worker re-reads Odoo, which preserves the source-of-truth and avoids
    # accepting customer or order detail in the webhook body.
    queued = False
    connection = event.connection
    if connection.status == 'ACTIVE' and not connection.sync_runs.filter(status__in=['PENDING', 'RUNNING']).exists():
        run = IntegrationSyncRun.objects.create(
            connection=connection,
            run_type='INCREMENTAL',
            cursor_before=connection.cursor_json,
        )
        job = BackgroundJob.objects.create(
            workspace=connection.workspace,
            job_type='INTEGRATION_SYNC',
            status='PENDING',
            current_stage='INTEGRATION_SYNC',
            stages_json={'INTEGRATION_SYNC': {'status': 'PENDING', 'progress': 0, 'provider': connection.provider, 'runType': 'INCREMENTAL', 'trigger': 'WEBHOOK'}},
            idempotency_key=f'integration:{connection.id}:webhook:{run.id}',
        )
        run.background_job = job
        run.save(update_fields=['background_job'])
        task = run_integration_sync.delay(str(run.id))
        job.celery_task_id = str(task.id)
        job.save(update_fields=['celery_task_id', 'updated_at'])
        queued = True
    return {'status': event.status, 'event_type': event.event_type, 'follow_up_sync_queued': queued}


@shared_task(
    name='supplyforge.tasks.enqueue_due_integration_syncs',
    queue='integration_worker',
)
def enqueue_due_integration_syncs() -> dict:
    """Schedule 15-minute incremental pulls without overlapping a connection."""
    from supplyforge.models import IntegrationConnection, IntegrationSyncRun

    # The indexed coarse filter keeps Beat from scanning every active source;
    # the per-connection interval below remains the final due decision.
    earliest_due_before = timezone.now() - timedelta(minutes=1)
    connections = IntegrationConnection.objects.filter(
        status='ACTIVE', last_successful_sync_at__lte=earliest_due_before,
    ).exclude(
        sync_runs__status__in=['PENDING', 'RUNNING'],
    ).distinct()
    queued = 0
    for connection in connections.iterator():
        # Odoo remains scoped to a selected company and warehouse. Seller
        # sources already receive their scope through OAuth, so they do not
        # inherit this ERP-only gate.
        if connection.provider == IntegrationConnection.PROVIDER_ODOO and (
            not connection.external_company_id or not connection.warehouse_ids
        ):
            continue
        due_before = timezone.now() - timedelta(
            minutes=max(1, connection.sync_interval_minutes)
        )
        if connection.last_successful_sync_at and connection.last_successful_sync_at > due_before:
            continue
        run = IntegrationSyncRun.objects.create(
            connection=connection,
            run_type='INCREMENTAL',
            cursor_before=connection.cursor_json,
        )
        job = BackgroundJob.objects.create(
            workspace=connection.workspace,
            job_type='INTEGRATION_SYNC',
            status='PENDING',
            current_stage='INTEGRATION_SYNC',
            stages_json={'INTEGRATION_SYNC': {'status': 'PENDING', 'progress': 0, 'provider': connection.provider, 'runType': 'INCREMENTAL', 'trigger': 'SCHEDULE'}},
            idempotency_key=f'integration:{connection.id}:schedule:{run.id}',
        )
        run.background_job = job
        run.save(update_fields=['background_job'])
        task = run_integration_sync.delay(str(run.id))
        job.celery_task_id = str(task.id)
        job.save(update_fields=['celery_task_id', 'updated_at'])
        queued += 1
    return {'queued': queued, 'evaluated_at': timezone.now().isoformat()}


@shared_task(
    name='supplyforge.tasks.send_due_action_plan_reminders',
    queue='decision_worker',
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def send_due_action_plan_reminders() -> dict:
    """Deliver in-app/email deadline reminders with an idempotent delivery ledger."""
    from supplyforge.services.action_execution import ActionReminderService
    return ActionReminderService.send_due_reminders()


@shared_task(
    bind=True,
    name='supplyforge.tasks.submit_supplier_return_request',
    queue='integration_worker',
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def submit_supplier_return_request(self, request_id: int) -> dict:
    """Send exactly one approved return request through the narrow Odoo write surface."""
    from supplyforge.services.supplier_return import SupplierReturnService
    try:
        return SupplierReturnService.submit(request_id)
    except (ValueError, Exception) as exc:
        # The persisted request carries the visible failure; retries only cover
        # transient connector faults rather than approval/data validation errors.
        if isinstance(exc, ValueError):
            raise
        raise self.retry(exc=exc)


@shared_task(
    name='supplyforge.tasks.mature_temporal_shadow_predictions',
    queue='ml_worker',
    acks_late=True,
)
def mature_temporal_shadow_predictions() -> dict:
    """Mature eligible SHADOW/CANARY cohorts once per day.

    The task only reconstructs the predeclared 60-day demand label and emits
    monitoring quality. It neither retrains a candidate nor interprets the
    result as inventory, capital, or causal action impact.
    """
    from supplyforge.services.temporal_shadow_monitoring import TemporalShadowMonitoringService

    lock_key = 'sf:temporal-shadow-monitoring:daily'
    try:
        acquired = cache.add(lock_key, '1', timeout=55 * 60)
    except Exception:
        acquired = True
    if not acquired:
        return {'status': 'SKIPPED', 'reason': 'monitoring_already_running'}
    try:
        maturity = TemporalShadowMonitoringService.mature_outcomes()
        quality = TemporalShadowMonitoringService.quality_report()
        alerts = sum(1 for cohort in quality['cohorts'] if cohort['drift_status'] == 'ALERT')
        summary = {
            'status': 'COMPLETED',
            'evaluated_at': timezone.now().isoformat(),
            'maturity': maturity,
            'matured_prediction_count': quality['matured_prediction_count'],
            'cohort_count': quality['cohort_count'],
            'probability_drift_alert_count': alerts,
            'scope': quality['scope'],
        }
        logger.info('Temporal SHADOW monitoring completed: %s', summary)
        return summary
    finally:
        try:
            cache.delete(lock_key)
        except Exception:
            pass


@shared_task(
    name='supplyforge.tasks.mature_slow_moving_outcomes',
    queue='data_worker',
    acks_late=True,
)
def mature_slow_moving_outcomes() -> dict:
    """Mature slow-moving 30/60/90-day outcome cohorts without retuning rules."""
    from supplyforge.services.slow_moving_outcomes import SlowMovingOutcomeService

    lock_key = 'sf:slow-moving-outcomes:daily'
    try:
        acquired = cache.add(lock_key, '1', timeout=55 * 60)
    except Exception:
        acquired = True
    if not acquired:
        return {'status': 'SKIPPED', 'reason': 'monitoring_already_running'}
    try:
        maturity = SlowMovingOutcomeService.mature_outcomes()
        summary = {
            'status': 'COMPLETED',
            'evaluated_at': timezone.now().isoformat(),
            'maturity': maturity,
            'scope': 'Future net fulfilled demand only; no inventory, capital, or causal action claim.',
        }
        logger.info('Slow-moving outcome maturation completed: %s', summary)
        return summary
    finally:
        try:
            cache.delete(lock_key)
        except Exception:
            pass


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
    # Keep the source's final observed date as the later decision cutoff.
    # Import completion time is operational metadata, not demand evidence.
    try:
        session.date_range_start = (
            datetime.strptime(profile.date_range_start, '%Y-%m-%d').date()
            if profile.date_range_start else None
        )
        session.date_range_end = (
            datetime.strptime(profile.date_range_end, '%Y-%m-%d').date()
            if profile.date_range_end else None
        )
    except (TypeError, ValueError):
        session.date_range_start = None
        session.date_range_end = None
    session.dataset_profile_json = {
        'totalRows': profile.total_rows,
        'totalColumns': profile.total_columns,
        'headers': profile.headers,
        'columnTypes': profile.column_types,
        'previewRows': profile.preview_rows,
        'missingValues': profile.missing_values,
        'uniqueSkus': getattr(profile, 'unique_skus', getattr(profile, 'unique_sku_count', 0)),
        'dateRange': {
            'start': profile.date_range_start,
            'end': profile.date_range_end,
        },
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
        'preview_rows_json', 'missing_values_json', 'date_range_start', 'date_range_end', 'dataset_profile_json',
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
                # Publish one operational run only after the dataset version
                # is active; the legacy hook uses a different source path.
                run_post_import_hooks=False,
                progress_callback=lambda payload: progress_report({
                    **payload,
                    **silver_progress,
                }),
            )
            LakehouseIngestionService.record_import_result(dataset_version, import_res)

        # The importer has the mapped business-date column, so it is more
        # authoritative than profiler heuristics when defining CSV as-of time.
        temporal_range = import_res.get('temporal_range') or {}
        try:
            incoming_start = temporal_range.get('incoming_start')
            incoming_end = temporal_range.get('incoming_end')
            if incoming_start:
                session.date_range_start = datetime.strptime(incoming_start, '%Y-%m-%d').date()
            if incoming_end:
                session.date_range_end = datetime.strptime(incoming_end, '%Y-%m-%d').date()
            if incoming_start or incoming_end:
                session.save(update_fields=['date_range_start', 'date_range_end', 'updated_at'])
        except (TypeError, ValueError):
            logger.warning('Could not persist CSV temporal range for session=%s.', session.id)

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

    try:
        dataset_version_id = context.get('dataset_version_id')
        if dataset_version_id:
            from supplyforge.models import DatasetVersion
            from supplyforge.services.slow_moving_run_service import SlowMovingRunService

            version = DatasetVersion.objects.get(
                id=dataset_version_id,
                workspace_id=job.workspace_id,
            )
            slow_moving_run = SlowMovingRunService.run_csv_for_dataset(version)
            # The capital read model is calculated by the worker immediately
            # after risk assessments are persisted, never by a dashboard GET.
            from supplyforge.services.capital_exposure_service import CapitalExposureAnalysisService

            CapitalExposureAnalysisService.ensure_current_analysis(job.workspace_id)
            context['ml_result'] = {
                'status': 'SUCCESS',
                'slow_moving_run_id': str(slow_moving_run.id),
                'analysis_as_of': slow_moving_run.analysis_as_of.isoformat(),
            }
        else:
            context['ml_result'] = {'status': 'SKIPPED', 'reason': 'DATASET_VERSION_MISSING'}
    except Exception as e:
        # Publishing a current risk run is a required operational stage.  Do
        # not mark an import successful while the dashboard would otherwise
        # serve an older source or no trustworthy assessment at all.
        logger.exception('Slow-moving operational run failed for import job %s.', job.id)
        context['ml_result'] = {'status': 'FAILED', 'reason': str(e)[:512]}
        raise

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


@shared_task(bind=True, queue='data_worker', max_retries=2, default_retry_delay=60)
def run_capital_exposure_analysis(self, workspace_id: int) -> dict:
    """Backfill a capital read model without making an HTTP worker calculate it."""
    from supplyforge.services.capital_exposure_service import CapitalExposureAnalysisService

    try:
        analysis = CapitalExposureAnalysisService.ensure_current_analysis(int(workspace_id))
        return {
            'status': 'COMPLETED' if analysis else 'SKIPPED',
            'analysis_id': str(analysis.analysis_id) if analysis else None,
        }
    except Exception as exc:
        logger.exception('Capital exposure analysis failed for workspace %s.', workspace_id)
        raise self.retry(exc=exc)


@shared_task(queue='data_worker')
def warm_workspace_cache(workspace_id: int) -> dict:
    """Run cache warming in a worker, never in the API process."""
    from supplyforge.services.cache_warming_service import CacheWarmingService

    CacheWarmingService.warm_workspace_cache(int(workspace_id))
    return {'status': 'QUEUED_AND_WARMED', 'workspace_id': int(workspace_id)}


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


@shared_task(bind=True, queue='data_worker')
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


@shared_task(queue='data_worker', acks_late=True)
def capture_slow_moving_candidate_shadow(run_id: str) -> dict:
    """Capture governed SHADOW/CANARY diagnostics outside the rule run path."""
    from supplyforge.services.slow_moving_candidate_shadow import SlowMovingCandidateShadowService

    return SlowMovingCandidateShadowService.capture_run(str(run_id))
