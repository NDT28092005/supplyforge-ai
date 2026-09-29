"""
SupplyForge AI — Celery Background Tasks
===========================================
All long-running tasks for file imports and Shopee sync operations.
"""

from __future__ import annotations

import logging
import time

from celery import shared_task
from django.conf import settings

from supplyforge.services.ingestion import DynamicFileImportService

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 30 * 60  # 30 minutes


@shared_task(name="health_check_task", bind=True)
def health_check_task(self, worker_type: str = "data_worker") -> dict:
    """
    Task 1.3: Celery Health Check Task.
    Verifies worker execution for Data Worker, ML Worker, or Decision Worker.
    """
    from django.utils import timezone
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


@shared_task(bind=True)
def process_file_import_async(self, file_path, mapping_rule, user_id):
    """
    Background Celery worker task to process large Excel/CSV imports asynchronously.
    Updates task state so frontend can poll progress.
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
