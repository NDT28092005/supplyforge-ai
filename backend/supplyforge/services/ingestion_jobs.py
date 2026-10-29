"""Idempotent creation and dispatch of CSV import jobs."""

from __future__ import annotations

import logging

from django.db import transaction

from supplyforge.models import BackgroundJob, IngestionSession

logger = logging.getLogger(__name__)


class ImportJobDispatchError(RuntimeError):
    """Raised when the configured asynchronous worker cannot accept a job."""


IMPORT_STAGES = {
    'PARSING': {'status': 'PENDING', 'progress': 0},
    'PROFILING': {'status': 'PENDING', 'progress': 0},
    'MAPPING': {'status': 'PENDING', 'progress': 0},
    'IMPORTING': {'status': 'PENDING', 'progress': 0},
    'ML_INFERENCE': {'status': 'PENDING', 'progress': 0},
    'FINALIZING': {'status': 'PENDING', 'progress': 0},
}


def create_or_get_import_job(
    session: IngestionSession,
    idempotency_key: str,
) -> tuple[BackgroundJob, bool]:
    """Serialize creation per session so duplicate S3 events cannot enqueue twice."""
    with transaction.atomic():
        locked_session = IngestionSession.objects.select_for_update().get(id=session.id)
        existing = (
            BackgroundJob.objects.select_for_update()
            .filter(ingestion_session=locked_session, job_type='CSV_IMPORT')
            .order_by('-created_at')
            .first()
        )
        if existing:
            return existing, False

        job = BackgroundJob.objects.create(
            workspace=locked_session.workspace,
            job_type='CSV_IMPORT',
            ingestion_session=locked_session,
            idempotency_key=idempotency_key,
            status='PENDING',
            current_stage='PARSING',
            progress_pct=0,
            stages_json=IMPORT_STAGES.copy(),
        )
        if locked_session.status == 'UPLOADING':
            locked_session.status = 'QUEUED'
            locked_session.save(update_fields=['status', 'updated_at'])
        return job, True


def dispatch_import_job(job: BackgroundJob) -> str:
    """Queue an import job without ever moving worker execution into HTTP."""
    from supplyforge.tasks import run_import_pipeline

    try:
        async_result = run_import_pipeline.delay(str(job.id))
        task_id = str(async_result.id)
    except Exception as exc:
        logger.exception('Celery dispatch failed for import job %s.', job.id)
        BackgroundJob.objects.filter(id=job.id).update(
            status='FAILED',
            error_message='Không thể kết nối hàng chờ xử lý. Vui lòng thử lại sau.',
        )
        raise ImportJobDispatchError('Không thể kết nối hàng chờ xử lý.') from exc

    BackgroundJob.objects.filter(id=job.id).update(celery_task_id=task_id)
    return task_id
