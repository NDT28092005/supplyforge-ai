#!/usr/bin/env python3
"""
SupplyForge AI — Enterprise Telemetry & Metric Simulator
Generates 100% complete metrics for Django API, MySQL, Redis, Celery, ML Pipeline, and Domain KPIs.
"""
import time
import random
from prometheus_client import start_http_server, Counter, Histogram, Gauge

# ----------------------------------------------------
# 1. Django API & Recording Rules Metrics
# ----------------------------------------------------
REQ_BEFORE_MW = Counter(
    'django_http_requests_before_middlewares_total',
    'Total HTTP requests before middlewares',
    ['method']
)
RESP_STATUS = Counter(
    'django_http_responses_total_by_status_name_total',
    'Total HTTP responses by status name',
    ['status', 'status_code']
)
REQ_LATENCY = Histogram(
    'django_http_requests_latency_seconds',
    'HTTP request latency bucket',
    ['view', 'method'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
REQ_BY_METHOD = Counter(
    'django_http_requests_total_by_method_total',
    'Total HTTP requests by method',
    ['method']
)
REQ_5XX = Counter(
    'django_http_requests_total_by_status_5xx_total',
    'Total HTTP 5xx error requests'
)

# ----------------------------------------------------
# 2. MySQL Metrics (Mocked for Exporter Dashboard)
# ----------------------------------------------------
MYSQL_UP = Gauge('mysql_up', 'MySQL Up Status')
MYSQL_THREADS = Gauge('mysql_global_status_threads_connected', 'Connected MySQL threads')
MYSQL_MAX_CONN = Gauge('mysql_global_variables_max_connections', 'Max MySQL connections')

MYSQL_COMMANDS = Counter('mysql_global_status_commands_total', 'MySQL commands executed', ['command'])
MYSQL_SLOW_QUERIES = Counter('mysql_global_status_slow_queries_total', 'MySQL slow queries total')
MYSQL_BP_READS = Counter('mysql_global_status_innodb_buffer_pool_reads_total', 'InnoDB buffer pool reads')
MYSQL_BP_REQUESTS = Counter('mysql_global_status_innodb_buffer_pool_read_requests_total', 'InnoDB buffer pool read requests')
MYSQL_BYTES_RCVD = Counter('mysql_global_status_bytes_received_total', 'MySQL bytes received total')
MYSQL_BYTES_SENT = Counter('mysql_global_status_bytes_sent_total', 'MySQL bytes sent total')

# ----------------------------------------------------
# 3. Redis Metrics (Mocked for Exporter Dashboard)
# ----------------------------------------------------
REDIS_UP = Gauge('redis_up', 'Redis Up Status')
REDIS_MEM_USED = Gauge('redis_memory_used_bytes', 'Redis memory used bytes')
REDIS_MEM_MAX = Gauge('redis_memory_max_bytes', 'Redis memory max limit bytes')

REDIS_HITS = Counter('redis_keyspace_hits_total', 'Redis keyspace hits')
REDIS_MISSES = Counter('redis_keyspace_misses_total', 'Redis keyspace misses')
REDIS_EVICTED = Counter('redis_evicted_keys_total', 'Redis evicted keys total')

# ----------------------------------------------------
# 4. SupplyForge Domain Metrics
# ----------------------------------------------------
IMPORT_TOTAL = Counter('supplyforge_import_total', 'Total data import executions', ['status', 'format'])
IMPORT_DURATION = Histogram('supplyforge_import_duration_seconds', 'Data import step execution duration', ['step'], buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0])
IMPORT_ROWS = Counter('supplyforge_import_rows_total', 'Total ingested data rows')

PREDICTION_TOTAL = Counter('supplyforge_prediction_total', 'Total risk predictions', ['model_version', 'status'])
PREDICTION_DURATION = Histogram('supplyforge_prediction_duration_seconds', 'ML inference duration in seconds', ['step'], buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0])
RISK_DISTRIBUTION = Counter('supplyforge_risk_distribution_total', 'Predicted risk level distribution', ['risk_level'])
FEATURE_MISSING_RATE = Gauge('supplyforge_feature_missing_rate', 'Input feature missing rate')
MODEL_GOVERNANCE = Gauge('supplyforge_model_governance_info', 'Active ML model governance info', ['model_version', 'feature_version', 'threshold_version'])

RISK_ASSESSMENTS = Counter('supplyforge_risk_assessment_total', 'Total risk assessments')
DECISION_GENERATED = Counter('supplyforge_decision_generated_total', 'Total automated decisions generated', ['action_type'])
DECISION_APPROVED = Counter('supplyforge_decision_approved_total', 'Total decisions approved by operators')
CACHE_HIT = Counter('supplyforge_cache_hit_total', 'Total cache hits', ['cache_name'])
CACHE_MISS = Counter('supplyforge_cache_miss_total', 'Total cache misses', ['cache_name'])

QUEUE_DEPTH = Gauge('supplyforge_task_queue_depth', 'Celery queue backlog depth', ['queue'])
TASK_AGE = Gauge('supplyforge_task_age_seconds', 'Oldest task age in queue in seconds', ['queue'])
TASK_TOTAL = Counter('supplyforge_task_total', 'Celery task executions total', ['queue', 'status'])

# Initialize labeled series upfront with non-zero values
def init_series():
    MYSQL_UP.set(1)
    MYSQL_THREADS.set(25)
    MYSQL_MAX_CONN.set(150)
    
    REDIS_UP.set(1)
    REDIS_MEM_USED.set(400000000)
    REDIS_MEM_MAX.set(1073741824)
    
    MODEL_GOVERNANCE.labels(model_version='v1.2', feature_version='v2', threshold_version='v1').set(1)
    DECISION_GENERATED.labels(action_type='PO_REORDER').inc(1)
    DECISION_GENERATED.labels(action_type='CAPITAL_REALLOCATION').inc(1)
    DECISION_APPROVED.inc(1)
    RISK_ASSESSMENTS.inc(1)
    
    for fmt in ['csv', 'excel']:
        IMPORT_TOTAL.labels(status='success', format=fmt).inc(1)
    
    IMPORT_ROWS.inc(500)
    PREDICTION_TOTAL.labels(model_version='v1.2', status='success').inc(1)
    
    for r in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
        RISK_DISTRIBUTION.labels(risk_level=r).inc(1)
        
    for m in ['GET', 'POST', 'PUT', 'DELETE']:
        REQ_BEFORE_MW.labels(method=m).inc(1)
        REQ_BY_METHOD.labels(method=m).inc(1)
        
    RESP_STATUS.labels(status='200', status_code='200').inc(1)
    RESP_STATUS.labels(status='500', status_code='500').inc(1)
    
    for cmd in ['select', 'insert', 'update']:
        MYSQL_COMMANDS.labels(command=cmd).inc(1)
        
    for c_name in ['risk_matrix', 'portfolio', 'sku_lookup']:
        CACHE_HIT.labels(cache_name=c_name).inc(1)
        CACHE_MISS.labels(cache_name=c_name).inc(1)

    for q in ['data_worker', 'ml_worker', 'decision_worker']:
        QUEUE_DEPTH.labels(queue=q).set(2)
        TASK_AGE.labels(queue=q).set(5.0)
        TASK_TOTAL.labels(queue=q, status='success').inc(1)
        TASK_TOTAL.labels(queue=q, status='failed').inc(1)

    REQ_LATENCY.labels(view='api_risk_matrix', method='GET').observe(0.05)
    FEATURE_MISSING_RATE.set(0.005)
    
    MYSQL_SLOW_QUERIES.inc(1)
    MYSQL_BP_READS.inc(10)
    MYSQL_BP_REQUESTS.inc(500)
    MYSQL_BYTES_RCVD.inc(10240)
    MYSQL_BYTES_SENT.inc(40960)
    
    REDIS_HITS.inc(100)
    REDIS_MISSES.inc(5)
    REDIS_EVICTED.inc(2)

init_series()


def generate_telemetry_step():
    # 1. API Requests
    methods = ['GET', 'POST', 'PUT', 'DELETE']
    views = ['api_risk_matrix', 'api_decision_recommend', 'api_batch_import', 'api_portfolio']
    
    for _ in range(random.randint(10, 25)):
        m = random.choice(methods)
        v = random.choice(views)
        REQ_BEFORE_MW.labels(method=m).inc()
        REQ_BY_METHOD.labels(method=m).inc()
        REQ_LATENCY.labels(view=v, method=m).observe(random.uniform(0.02, 0.25))
        
        if random.random() < 0.02:
            RESP_STATUS.labels(status='500', status_code='500').inc()
            REQ_5XX.inc()
        else:
            RESP_STATUS.labels(status='200', status_code='200').inc()

    # 2. MySQL Metrics
    MYSQL_THREADS.set(random.randint(15, 50))
    MYSQL_COMMANDS.labels(command='select').inc(random.randint(30, 90))
    MYSQL_COMMANDS.labels(command='insert').inc(random.randint(5, 25))
    MYSQL_COMMANDS.labels(command='update').inc(random.randint(2, 12))
    
    MYSQL_BP_REQUESTS.inc(random.randint(200, 600))
    MYSQL_BP_READS.inc(random.randint(2, 10))
    MYSQL_BYTES_RCVD.inc(random.randint(2048, 20480))
    MYSQL_BYTES_SENT.inc(random.randint(8192, 81920))
    MYSQL_SLOW_QUERIES.inc(random.randint(1, 3))

    # 3. Redis Metrics
    REDIS_MEM_USED.set(random.randint(300000000, 550000000))
    REDIS_HITS.inc(random.randint(40, 120))
    REDIS_MISSES.inc(random.randint(1, 8))
    REDIS_EVICTED.inc(random.randint(1, 3))

    # 4. Ingestion & Domain
    fmt = random.choice(['csv', 'excel'])
    IMPORT_TOTAL.labels(status='success', format=fmt).inc()
    IMPORT_ROWS.inc(random.randint(300, 6000))
    IMPORT_DURATION.labels(step='insert').observe(random.uniform(0.5, 4.0))

    # 5. ML Model
    for _ in range(random.randint(4, 12)):
        PREDICTION_TOTAL.labels(model_version='v1.2', status='success').inc()
        PREDICTION_DURATION.labels(step='inference').observe(random.uniform(0.03, 0.18))
        PREDICTION_DURATION.labels(step='shap').observe(random.uniform(0.05, 0.22))
        
        r_level = random.choices(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'], weights=[65, 20, 10, 5])[0]
        RISK_DISTRIBUTION.labels(risk_level=r_level).inc()

    FEATURE_MISSING_RATE.set(random.uniform(0.001, 0.018))
    RISK_ASSESSMENTS.inc(random.randint(2, 8))

    # 6. Decisions & Cache
    action = random.choice(['PO_REORDER', 'CAPITAL_REALLOCATION'])
    DECISION_GENERATED.labels(action_type=action).inc()
    if random.random() < 0.85:
        DECISION_APPROVED.inc()

    for c_name in ['risk_matrix', 'portfolio', 'sku_lookup']:
        CACHE_HIT.labels(cache_name=c_name).inc(random.randint(15, 50))
        if random.random() < 0.12:
            CACHE_MISS.labels(cache_name=c_name).inc(random.randint(1, 5))

    # 7. Celery
    QUEUE_DEPTH.labels(queue='data_worker').set(random.randint(0, 4))
    QUEUE_DEPTH.labels(queue='ml_worker').set(random.randint(0, 6))
    QUEUE_DEPTH.labels(queue='decision_worker').set(random.randint(0, 2))

    TASK_AGE.labels(queue='data_worker').set(random.uniform(0.5, 8.0))
    TASK_AGE.labels(queue='ml_worker').set(random.uniform(1.0, 18.0))
    TASK_AGE.labels(queue='decision_worker').set(random.uniform(0.1, 3.0))

    TASK_TOTAL.labels(queue='ml_worker', status='success').inc(random.randint(2, 8))
    TASK_TOTAL.labels(queue='data_worker', status='success').inc(random.randint(1, 4))
    TASK_TOTAL.labels(queue='decision_worker', status='success').inc(random.randint(1, 5))
    if random.random() < 0.1:
        TASK_TOTAL.labels(queue='ml_worker', status='failed').inc(1)


def main():
    port = 8080
    start_http_server(port)
    print(f"🚀 Telemetry Simulator listening on port {port}...")
    
    loop_count = 0
    while True:
        generate_telemetry_step()
        loop_count += 1
        if loop_count % 10 == 0:
            print(f"📊 [Telemetry Simulator - Loop {loop_count}] Generated synthetic operational telemetry.")
        time.sleep(1)


if __name__ == '__main__':
    main()
