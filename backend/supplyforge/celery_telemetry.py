"""
SupplyForge AI — Celery Telemetry Module (SF-OPS-08)
=====================================================
Collects queue depth (supplyforge_task_queue_depth) and task age (supplyforge_task_age_seconds)
metrics without affecting business task execution or creating high-cardinality labels.
"""

import time
import logging
from celery.signals import before_task_publish, task_prerun

from supplyforge.metrics import TASK_QUEUE_DEPTH, TASK_AGE_SECONDS

logger = logging.getLogger(__name__)

MONITORED_QUEUES = {
    'data_worker': ('data', 'data_worker'),
    'ml_worker': ('ml', 'ml_worker'),
    'decision_worker': ('decision', 'decision_worker'),
}


def update_celery_queue_depths(redis_url=None) -> dict:
    """
    Safely fetches current backlog depth for Celery queues in Redis broker.
    Returns dict mapping queue_name -> depth.
    """
    try:
        import redis as redis_lib
        from django.conf import settings
        url = redis_url or getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
        r = redis_lib.from_url(url)

        depths = {}
        for q_key, (w_type, q_name) in MONITORED_QUEUES.items():
            depth = r.llen(q_key)
            depths[q_name] = depth
            TASK_QUEUE_DEPTH.labels(worker_type=w_type, queue=q_name).set(depth)
        return depths
    except Exception as e:
        logger.warning(f"[CeleryTelemetry] Failed to fetch queue depth from broker: {e}")
        return {'data_worker': 0, 'ml_worker': 0, 'decision_worker': 0}


def record_task_age(queue_name: str, enqueue_time: float, worker_start_time: float = None):
    """
    Safely calculates and records Celery task waiting time in queue before worker execution starts.
    Task Age = worker_start_time - enqueue_time.
    """
    try:
        w_start = worker_start_time if worker_start_time is not None else time.time()
        task_age = max(0.0, float(w_start) - float(enqueue_time))

        w_type = 'data'
        q_clean = str(queue_name)
        if 'ml' in q_clean:
            w_type = 'ml'
        elif 'decision' in q_clean:
            w_type = 'decision'

        TASK_AGE_SECONDS.labels(worker_type=w_type, queue=q_clean).set(task_age)
        return task_age
    except Exception as e:
        logger.warning(f"[CeleryTelemetry] Failed to record task age metric: {e}")
        return 0.0


@before_task_publish.connect
def on_before_task_publish(headers=None, body=None, **kwargs):
    """Signal receiver: attaches enqueue_time timestamp to task headers prior to broker publishing."""
    try:
        if headers is not None:
            headers['enqueue_time'] = time.time()
    except Exception as e:
        logger.warning(f"[CeleryTelemetry] Failed to set enqueue_time in task headers: {e}")


@task_prerun.connect
def on_task_prerun(task_id=None, task=None, *args, **kwargs):
    """Signal receiver: calculates task age upon worker receipt and updates queue depth gauges."""
    try:
        if task and hasattr(task, 'request') and task.request:
            req_headers = getattr(task.request, 'headers', {}) or {}
            enqueue_time = req_headers.get('enqueue_time')
            
            delivery_info = getattr(task.request, 'delivery_info', {}) or {}
            queue_name = delivery_info.get('routing_key') or getattr(task, 'queue', 'data_worker') or 'data_worker'

            if enqueue_time is not None:
                record_task_age(queue_name=queue_name, enqueue_time=enqueue_time)

        update_celery_queue_depths()
    except Exception as e:
        logger.warning(f"[CeleryTelemetry] Error during task_prerun telemetry signal: {e}")
