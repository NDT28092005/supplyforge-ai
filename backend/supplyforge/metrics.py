import time
import logging
from prometheus_client import Counter, Gauge, Histogram, REGISTRY

logger = logging.getLogger(__name__)


def _get_or_create_metric(collector_cls, name, documentation, labelnames=(), **kwargs):
    """
    Helper function to safely get existing metric or register a new metric object.
    Prevents ValueError: Duplicated timeseries in CollectorRegistry during tests or reloads.
    """
    for collector in REGISTRY._names_to_collectors.values():
        if hasattr(collector, '_name') and collector._name == name:
            return collector
    return collector_cls(name, documentation, labelnames=labelnames, **kwargs)


# ── A. Ingestion Metrics ─────────────────────────────────────────────
INGESTION_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_ingestion_total',
    'Total count of data ingestion runs',
    ['pipeline', 'source_type', 'status']
)

INGESTION_FAILED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_ingestion_failed_total',
    'Total count of failed data ingestion runs',
    ['pipeline', 'source_type']
)

INGESTION_DURATION_SECONDS = _get_or_create_metric(
    Histogram,
    'supplyforge_ingestion_duration_seconds',
    'Execution duration of data ingestion pipeline in seconds',
    ['pipeline', 'source_type'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
)

INGESTION_ROWS_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_ingestion_rows_total',
    'Total number of rows processed by ingestion pipeline',
    ['pipeline', 'source_type']
)

INGESTION_LAST_SUCCESS_TIMESTAMP = _get_or_create_metric(
    Gauge,
    'supplyforge_ingestion_last_success_timestamp',
    'Unix timestamp of the last successful data ingestion run',
    ['pipeline']
)


# ── B. ML / Prediction Metrics ───────────────────────────────────────
PREDICTION_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_prediction_total',
    'Total count of ML model risk predictions',
    ['model', 'model_version', 'status']
)

PREDICTION_FAILED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_prediction_failed_total',
    'Total count of failed ML model risk predictions',
    ['model', 'model_version', 'error_type']
)

PREDICTION_DURATION_SECONDS = _get_or_create_metric(
    Histogram,
    'supplyforge_prediction_duration_seconds',
    'Duration of complete prediction process in seconds',
    ['model', 'model_version'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

MODEL_INFERENCE_DURATION_SECONDS = _get_or_create_metric(
    Histogram,
    'supplyforge_model_inference_duration_seconds',
    'Duration of raw ML model inference in seconds',
    ['model', 'model_version'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
)


# ── C. Risk Metrics ──────────────────────────────────────────────────
RISK_ASSESSMENT_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_risk_assessment_total',
    'Total count of risk assessments generated',
    ['risk_level', 'status', 'model_version']
)

RISK_ASSESSMENT_FAILED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_risk_assessment_failed_total',
    'Total count of failed risk assessments',
    ['model_version']
)

HIGH_RISK_SKU_TOTAL = _get_or_create_metric(
    Gauge,
    'supplyforge_high_risk_sku_total',
    'Snapshot count of SKUs classified by risk level',
    ['risk_level']
)


# ── D. Decision Metrics ──────────────────────────────────────────────
DECISION_GENERATED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_decision_generated_total',
    'Total count of decision recommendations generated',
    ['decision_type', 'status']
)

DECISION_APPROVED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_decision_approved_total',
    'Total count of decision recommendations approved by merchants',
    ['decision_type']
)

DECISION_REJECTED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_decision_rejected_total',
    'Total count of decision recommendations rejected by merchants',
    ['decision_type']
)

SIMULATION_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_simulation_total',
    'Total count of financial or inventory simulations executed',
    ['simulation_type', 'status']
)


# ── E. Cache Metrics ─────────────────────────────────────────────────
CACHE_HIT_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_cache_hit_total',
    'Total count of cache hits',
    ['cache_area', 'operation']
)

CACHE_MISS_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_cache_miss_total',
    'Total count of cache misses',
    ['cache_area', 'operation']
)

CACHE_ERROR_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_cache_error_total',
    'Total count of cache errors',
    ['cache_area', 'operation']
)

CACHE_REFRESH_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_cache_refresh_total',
    'Total count of cache refreshes',
    ['cache_area']
)

CACHE_WARM_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_cache_warm_total',
    'Total count of cache warming executions',
    ['cache_area']
)


# ── F. Celery Metrics ────────────────────────────────────────────────
TASK_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_task_total',
    'Total count of Celery tasks executed',
    ['worker_type', 'queue', 'task_type', 'status']
)

TASK_FAILED_TOTAL = _get_or_create_metric(
    Counter,
    'supplyforge_task_failed_total',
    'Total count of failed Celery tasks',
    ['worker_type', 'queue', 'task_type']
)

TASK_DURATION_SECONDS = _get_or_create_metric(
    Histogram,
    'supplyforge_task_duration_seconds',
    'Execution duration of Celery tasks in seconds',
    ['worker_type', 'queue', 'task_type'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0)
)

TASK_QUEUE_DEPTH = _get_or_create_metric(
    Gauge,
    'supplyforge_task_queue_depth',
    'Current task queue depth',
    ['worker_type', 'queue']
)

TASK_AGE_SECONDS = _get_or_create_metric(
    Gauge,
    'supplyforge_task_age_seconds',
    'Age of the oldest task in queue in seconds',
    ['worker_type', 'queue']
)


# ── SAFE NON-INTRUSIVE RECORDING HELPERS ─────────────────────────────

def record_ingestion(pipeline='medallion', source_type='csv', status='success', duration=None, rows=0):
    """Safely record ingestion metrics."""
    try:
        INGESTION_TOTAL.labels(pipeline=pipeline, source_type=source_type, status=status).inc()
        if status == 'failed':
            INGESTION_FAILED_TOTAL.labels(pipeline=pipeline, source_type=source_type).inc()
        else:
            INGESTION_LAST_SUCCESS_TIMESTAMP.labels(pipeline=pipeline).set(time.time())
        if duration is not None:
            INGESTION_DURATION_SECONDS.labels(pipeline=pipeline, source_type=source_type).observe(duration)
        if rows > 0:
            INGESTION_ROWS_TOTAL.labels(pipeline=pipeline, source_type=source_type).inc(rows)
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record ingestion metrics: {e}")


def record_prediction(model='xgboost', model_version='v1', status='success', duration=None, inference_duration=None, error_type=None):
    """Safely record prediction & inference metrics."""
    try:
        PREDICTION_TOTAL.labels(model=model, model_version=model_version, status=status).inc()
        if status == 'failed':
            PREDICTION_FAILED_TOTAL.labels(
                model=model,
                model_version=model_version,
                error_type=error_type or 'unknown',
            ).inc()
        if duration is not None:
            PREDICTION_DURATION_SECONDS.labels(model=model, model_version=model_version).observe(duration)
        if inference_duration is not None:
            MODEL_INFERENCE_DURATION_SECONDS.labels(model=model, model_version=model_version).observe(inference_duration)
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record prediction metrics: {e}")


def record_risk_assessment(risk_level='MEDIUM_RISK', status='success', model_version='v1'):
    """Safely record risk assessment metrics."""
    try:
        RISK_ASSESSMENT_TOTAL.labels(risk_level=risk_level, status=status, model_version=model_version).inc()
        if status == 'failed':
            RISK_ASSESSMENT_FAILED_TOTAL.labels(model_version=model_version).inc()
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record risk assessment metrics: {e}")


def update_high_risk_sku_gauge(critical_count=0, high_count=0, medium_count=0, low_count=0):
    """Safely update high-risk SKU gauge snapshot."""
    try:
        HIGH_RISK_SKU_TOTAL.labels(risk_level='CRITICAL').set(critical_count)
        HIGH_RISK_SKU_TOTAL.labels(risk_level='HIGH_RISK').set(high_count)
        HIGH_RISK_SKU_TOTAL.labels(risk_level='MEDIUM_RISK').set(medium_count)
        HIGH_RISK_SKU_TOTAL.labels(risk_level='LOW_RISK').set(low_count)
    except Exception as e:
        logger.warning(f"[Metrics] Failed to update high-risk SKU gauge: {e}")


def record_decision(decision_type='PO_REORDER', action='generated', status='success'):
    """Safely record decision engine metrics (action: generated, approved, rejected, simulation)."""
    try:
        if action == 'generated':
            DECISION_GENERATED_TOTAL.labels(decision_type=decision_type, status=status).inc()
        elif action == 'approved':
            DECISION_APPROVED_TOTAL.labels(decision_type=decision_type).inc()
        elif action == 'rejected':
            DECISION_REJECTED_TOTAL.labels(decision_type=decision_type).inc()
        elif action == 'simulation':
            SIMULATION_TOTAL.labels(simulation_type=decision_type, status=status).inc()
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record decision metrics: {e}")


def record_cache(cache_area='dashboard', operation='get', result='hit'):
    """Safely record cache hit/miss/error/refresh/warm metrics."""
    try:
        if result == 'hit':
            CACHE_HIT_TOTAL.labels(cache_area=cache_area, operation=operation).inc()
        elif result == 'miss':
            CACHE_MISS_TOTAL.labels(cache_area=cache_area, operation=operation).inc()
        elif result == 'error':
            CACHE_ERROR_TOTAL.labels(cache_area=cache_area, operation=operation).inc()
        elif result == 'refresh':
            CACHE_REFRESH_TOTAL.labels(cache_area=cache_area).inc()
        elif result == 'warm':
            CACHE_WARM_TOTAL.labels(cache_area=cache_area).inc()
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record cache metrics: {e}")


def record_task(worker_type='data', queue='data_worker', task_type='process_file', status='success', duration=None):
    """Safely record Celery task execution metrics."""
    try:
        TASK_TOTAL.labels(worker_type=worker_type, queue=queue, task_type=task_type, status=status).inc()
        if status == 'failed':
            TASK_FAILED_TOTAL.labels(worker_type=worker_type, queue=queue, task_type=task_type).inc()
        if duration is not None:
            TASK_DURATION_SECONDS.labels(worker_type=worker_type, queue=queue, task_type=task_type).observe(duration)
    except Exception as e:
        logger.warning(f"[Metrics] Failed to record celery task metrics: {e}")


def update_task_queue_metrics(worker_type='data', queue='data_worker', depth=0, oldest_age_seconds=0):
    """Safely update Celery queue depth and oldest task age gauges."""
    try:
        TASK_QUEUE_DEPTH.labels(worker_type=worker_type, queue=queue).set(depth)
        TASK_AGE_SECONDS.labels(worker_type=worker_type, queue=queue).set(oldest_age_seconds)
    except Exception as e:
        logger.warning(f"[Metrics] Failed to update task queue metrics: {e}")
