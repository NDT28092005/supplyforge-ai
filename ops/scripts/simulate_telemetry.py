#!/usr/bin/env python3
"""Expose realistic SupplyForge metrics for local dashboard demonstrations.

This process is deliberately separate from Django and listens on port 9108 by
default. It is a dashboard fixture, not a traffic generator: never scrape it
at the same time as the real backend because the two sources would represent
different realities in one Prometheus instance.
"""

from __future__ import annotations

import os
import random
import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server


PORT = int(os.getenv('TELEMETRY_SIMULATOR_PORT', '9108'))
INTERVAL_SECONDS = max(1.0, float(os.getenv('TELEMETRY_SIMULATOR_INTERVAL_SECONDS', '2')))


# These schemas intentionally match backend/supplyforge/metrics.py.
HTTP_REQUESTS_BEFORE = Counter(
    'django_http_requests_before_middlewares_total',
    'Total HTTP requests before Django middleware.',
    ['method'],
)
HTTP_REQUESTS_BY_METHOD = Counter(
    'django_http_requests_total_by_method_total',
    'Total HTTP requests by method.',
    ['method'],
)
HTTP_RESPONSES = Counter(
    'django_http_responses_total_by_status_name_total',
    'Total HTTP responses by status.',
    ['status', 'status_code'],
)
HTTP_5XX = Counter(
    'django_http_requests_total_by_status_5xx_total',
    'Total HTTP 5xx responses.',
)
HTTP_DURATION = Histogram(
    'django_http_requests_latency_seconds',
    'Django request latency.',
    ['view', 'method'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

INGESTION_TOTAL = Counter(
    'supplyforge_ingestion_total',
    'Total count of data ingestion runs.',
    ['pipeline', 'source_type', 'status'],
)
INGESTION_FAILED_TOTAL = Counter(
    'supplyforge_ingestion_failed_total',
    'Total failed data ingestion runs.',
    ['pipeline', 'source_type'],
)
INGESTION_DURATION = Histogram(
    'supplyforge_ingestion_duration_seconds',
    'Ingestion pipeline duration.',
    ['pipeline', 'source_type'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)
INGESTION_ROWS = Counter(
    'supplyforge_ingestion_rows_total',
    'Rows processed by ingestion.',
    ['pipeline', 'source_type'],
)
INGESTION_LAST_SUCCESS = Gauge(
    'supplyforge_ingestion_last_success_timestamp',
    'Unix timestamp of the most recent successful ingestion.',
    ['pipeline'],
)

PREDICTION_TOTAL = Counter(
    'supplyforge_prediction_total',
    'Total risk predictions.',
    ['model', 'model_version', 'status'],
)
PREDICTION_FAILED_TOTAL = Counter(
    'supplyforge_prediction_failed_total',
    'Total failed risk predictions.',
    ['model', 'model_version', 'error_type'],
)
PREDICTION_DURATION = Histogram(
    'supplyforge_prediction_duration_seconds',
    'End-to-end prediction duration.',
    ['model', 'model_version'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
INFERENCE_DURATION = Histogram(
    'supplyforge_model_inference_duration_seconds',
    'Raw model inference duration.',
    ['model', 'model_version'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
RISK_ASSESSMENT_TOTAL = Counter(
    'supplyforge_risk_assessment_total',
    'Total risk assessments generated.',
    ['risk_level', 'status', 'model_version'],
)
RISK_ASSESSMENT_FAILED_TOTAL = Counter(
    'supplyforge_risk_assessment_failed_total',
    'Total failed risk assessments.',
    ['model_version'],
)
HIGH_RISK_SKUS = Gauge(
    'supplyforge_high_risk_sku_total',
    'Snapshot count of SKUs by risk level.',
    ['risk_level'],
)

DECISION_GENERATED_TOTAL = Counter(
    'supplyforge_decision_generated_total',
    'Total decision recommendations generated.',
    ['decision_type', 'status'],
)
DECISION_APPROVED_TOTAL = Counter(
    'supplyforge_decision_approved_total',
    'Total recommendations approved.',
    ['decision_type'],
)
DECISION_REJECTED_TOTAL = Counter(
    'supplyforge_decision_rejected_total',
    'Total recommendations rejected.',
    ['decision_type'],
)
SIMULATION_TOTAL = Counter(
    'supplyforge_simulation_total',
    'Total simulations executed.',
    ['simulation_type', 'status'],
)

CACHE_HIT_TOTAL = Counter(
    'supplyforge_cache_hit_total',
    'Total cache hits.',
    ['cache_area', 'operation'],
)
CACHE_MISS_TOTAL = Counter(
    'supplyforge_cache_miss_total',
    'Total cache misses.',
    ['cache_area', 'operation'],
)
CACHE_ERROR_TOTAL = Counter(
    'supplyforge_cache_error_total',
    'Total cache errors.',
    ['cache_area', 'operation'],
)
CACHE_REFRESH_TOTAL = Counter(
    'supplyforge_cache_refresh_total',
    'Total cache refreshes.',
    ['cache_area'],
)
CACHE_WARM_TOTAL = Counter(
    'supplyforge_cache_warm_total',
    'Total cache warming executions.',
    ['cache_area'],
)

TASK_TOTAL = Counter(
    'supplyforge_task_total',
    'Total Celery tasks executed.',
    ['worker_type', 'queue', 'task_type', 'status'],
)
TASK_FAILED_TOTAL = Counter(
    'supplyforge_task_failed_total',
    'Total failed Celery tasks.',
    ['worker_type', 'queue', 'task_type'],
)
TASK_DURATION = Histogram(
    'supplyforge_task_duration_seconds',
    'Celery task execution duration.',
    ['worker_type', 'queue', 'task_type'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
)
TASK_QUEUE_DEPTH = Gauge(
    'supplyforge_task_queue_depth',
    'Current task queue depth.',
    ['worker_type', 'queue'],
)
TASK_AGE = Gauge(
    'supplyforge_task_age_seconds',
    'Age of the oldest queued task.',
    ['worker_type', 'queue'],
)

# Snapshot metrics mirror business_metrics_collector.py and have no tenant,
# SKU, user, email, request ID, or other high-cardinality labels.
BUSINESS_SNAPSHOT_UP = Gauge(
    'supplyforge_business_snapshot_up',
    'Whether business snapshot collection succeeded.',
)
BUSINESS_ACTIVE_DATASETS = Gauge(
    'supplyforge_business_active_datasets',
    'Number of active dataset versions.',
)
BUSINESS_FRESHNESS_DAYS = Gauge(
    'supplyforge_business_dataset_freshness_days',
    'Maximum active dataset age in days.',
)
BUSINESS_QUALITY = Gauge(
    'supplyforge_business_dataset_quality_score',
    'Active dataset quality score.',
    ['stat'],
)
BUSINESS_RISK_SKUS = Gauge(
    'supplyforge_business_portfolio_skus',
    'Current SKU count by risk class.',
    ['risk_class'],
)
BUSINESS_CAPITAL = Gauge(
    'supplyforge_business_capital_exposure_vnd',
    'Current capital exposure in VND.',
    ['metric'],
)
BUSINESS_BACKLOG = Gauge(
    'supplyforge_business_action_backlog_total',
    'Actionable decision backlog by priority tier.',
    ['priority_tier'],
)
BUSINESS_UNREAD = Gauge(
    'supplyforge_business_unread_notifications_total',
    'Unread notification count by severity.',
    ['severity'],
)


MODEL = 'lightgbm'
MODEL_VERSION = 'risk-v1'
RISK_CLASSES = ('CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK')
WORKERS = (
    ('data', 'data_worker', 'run_import_pipeline'),
    ('ml', 'ml_worker', 'run_risk_inference'),
    ('decision', 'decision_worker', 'generate_decisions'),
)


def initialize() -> None:
    """Create all stable label series so empty dashboard states are explicit."""
    HTTP_5XX.inc(0)
    HTTP_RESPONSES.labels(status='500', status_code='500').inc(0)
    BUSINESS_SNAPSHOT_UP.set(1)
    BUSINESS_ACTIVE_DATASETS.set(1)
    BUSINESS_FRESHNESS_DAYS.set(3)
    BUSINESS_QUALITY.labels(stat='average').set(94.5)
    BUSINESS_QUALITY.labels(stat='minimum').set(91.0)

    for risk_class, count in {
        'CRITICAL': 36,
        'HIGH_RISK': 124,
        'MEDIUM_RISK': 380,
        'LOW_RISK': 1_260,
    }.items():
        BUSINESS_RISK_SKUS.labels(risk_class=risk_class).set(count)
        HIGH_RISK_SKUS.labels(risk_level=risk_class).set(count)

    for metric, value in {
        'inventory_value': 4_800_000_000,
        'risk_weighted_exposure': 1_160_000_000,
        'probability_adjusted_exposure': 760_000_000,
        'opportunity_cost': 135_000_000,
    }.items():
        BUSINESS_CAPITAL.labels(metric=metric).set(value)

    for tier, count in {'P1': 11, 'P2': 27, 'P3': 95, 'P4': 220}.items():
        BUSINESS_BACKLOG.labels(priority_tier=tier).set(count)
    for severity, count in {'CRITICAL': 1, 'HIGH': 4, 'WARNING': 9, 'INFO': 15}.items():
        BUSINESS_UNREAD.labels(severity=severity).set(count)

    INGESTION_LAST_SUCCESS.labels(pipeline='medallion').set(time.time())
    INGESTION_FAILED_TOTAL.labels(pipeline='medallion', source_type='csv').inc(0)
    PREDICTION_FAILED_TOTAL.labels(
        model=MODEL,
        model_version=MODEL_VERSION,
        error_type='unknown',
    ).inc(0)
    RISK_ASSESSMENT_FAILED_TOTAL.labels(model_version=MODEL_VERSION).inc(0)
    CACHE_ERROR_TOTAL.labels(cache_area='dashboard', operation='get').inc(0)
    for worker_type, queue, task_type in WORKERS:
        TASK_QUEUE_DEPTH.labels(worker_type=worker_type, queue=queue).set(0)
        TASK_AGE.labels(worker_type=worker_type, queue=queue).set(0)
        TASK_TOTAL.labels(
            worker_type=worker_type,
            queue=queue,
            task_type=task_type,
            status='success',
        ).inc()
        TASK_FAILED_TOTAL.labels(
            worker_type=worker_type,
            queue=queue,
            task_type=task_type,
        ).inc(0)


def record_step() -> None:
    """Advance counters and alter gauges inside realistic, non-alerting ranges."""
    for _ in range(random.randint(12, 28)):
        method = random.choices(('GET', 'POST'), weights=(9, 1))[0]
        view = random.choice(('dashboard_summary', 'risk_assessment_list', 'jobs_list'))
        latency = random.lognormvariate(-2.5, 0.45)
        HTTP_REQUESTS_BEFORE.labels(method=method).inc()
        HTTP_REQUESTS_BY_METHOD.labels(method=method).inc()
        HTTP_DURATION.labels(view=view, method=method).observe(latency)
        HTTP_RESPONSES.labels(status='200', status_code='200').inc()

    if random.random() < 0.10:
        rows = random.randint(2_000, 15_000)
        INGESTION_TOTAL.labels(
            pipeline='medallion', source_type='csv', status='success'
        ).inc()
        INGESTION_DURATION.labels(pipeline='medallion', source_type='csv').observe(
            random.uniform(4.0, 18.0)
        )
        INGESTION_ROWS.labels(pipeline='medallion', source_type='csv').inc(rows)
        INGESTION_LAST_SUCCESS.labels(pipeline='medallion').set(time.time())

    for _ in range(random.randint(8, 20)):
        PREDICTION_TOTAL.labels(
            model=MODEL, model_version=MODEL_VERSION, status='success'
        ).inc()
        PREDICTION_DURATION.labels(model=MODEL, model_version=MODEL_VERSION).observe(
            random.uniform(0.08, 0.35)
        )
        INFERENCE_DURATION.labels(model=MODEL, model_version=MODEL_VERSION).observe(
            random.uniform(0.02, 0.16)
        )
        risk_class = random.choices(
            RISK_CLASSES, weights=(3, 10, 27, 60), k=1
        )[0]
        RISK_ASSESSMENT_TOTAL.labels(
            risk_level=risk_class,
            status='success',
            model_version=MODEL_VERSION,
        ).inc()

    for _ in range(random.randint(20, 50)):
        CACHE_HIT_TOTAL.labels(cache_area='dashboard', operation='get').inc()
    for _ in range(random.randint(1, 4)):
        CACHE_MISS_TOTAL.labels(cache_area='dashboard', operation='get').inc()

    for worker_type, queue, task_type in WORKERS:
        depth = random.randint(0, 5 if worker_type != 'ml' else 8)
        TASK_QUEUE_DEPTH.labels(worker_type=worker_type, queue=queue).set(depth)
        TASK_AGE.labels(worker_type=worker_type, queue=queue).set(
            random.uniform(0.0, 12.0 if depth else 1.0)
        )
        TASK_TOTAL.labels(
            worker_type=worker_type,
            queue=queue,
            task_type=task_type,
            status='success',
        ).inc(random.randint(1, 5))
        TASK_DURATION.labels(
            worker_type=worker_type,
            queue=queue,
            task_type=task_type,
        ).observe(random.uniform(0.2, 3.0))

    decision_type = random.choice(('DISCOUNT_CLEARANCE', 'BUNDLE_PROMOTION'))
    DECISION_GENERATED_TOTAL.labels(
        decision_type=decision_type, status='success'
    ).inc()
    if random.random() < 0.7:
        DECISION_APPROVED_TOTAL.labels(decision_type=decision_type).inc()
    SIMULATION_TOTAL.labels(
        simulation_type='DISCOUNT_SIMULATION', status='success'
    ).inc(random.randint(0, 2))


def main() -> None:
    initialize()
    start_http_server(PORT)
    print(
        f'SupplyForge telemetry simulator listening on http://127.0.0.1:{PORT}/metrics '
        f'(interval={INTERVAL_SECONDS:g}s).'
    )
    while True:
        record_step()
        time.sleep(INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
