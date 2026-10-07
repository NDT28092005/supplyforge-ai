# SF-OPS-15 Verification Document: Operational Runbooks & SLO Specifications

## 1. Overview
Ticket **SF-OPS-15** establishes comprehensive operational runbooks (`ops/runbooks/`) for all P1/P2 alert rules and defines formal Service Level Objectives (SLOs) and Error Budget management rules (`ops/docs/operations/SLO.md`).

## 2. Operational Runbooks Inventory

| Runbook File | Target Service | Addressed Alert Rules | Key Remediation Actions |
| :--- | :--- | :--- | :--- |
| `backend/http-5xx-errors.md` | Django Backend | `BackendHighErrorRate`, `BackendCriticalErrorRate` | Log triage, readiness check, container restart, rollback |
| `mysql/connection-exhaustion.md` | MySQL Database | `MySQLDown`, `MySQLConnectionSaturation` | Processlist inspection, sleeping query termination, max connection tuning |
| `redis/memory-eviction.md` | Redis Cache | `RedisDown`, `RedisMemoryHigh`, `RedisEvictionRateHigh` | Bigkeys analysis, stale cache eviction, maxmemory expansion |
| `celery/queue-backlog.md` | Celery Async Queues | `CeleryWorkerDown`, `CeleryQueueAgeHigh`, `CeleryQueueBacklogHigh` | Worker scale-out, poison-pill task purge, worker restart |
| `ml/model-drift-and-latency.md` | ML Engine | `MLInferenceLatencyHigh`, `MLPredictionErrorRateHigh` | Fast prediction mode toggle, model version rollback, worker restart |
| `monitoring/target-down.md` | Monitoring Plane | `PrometheusTargetDown`, `PrometheusScrapeFailure` | Exporter health check, target reload, disk space verification |

## 3. SLO & Error Budget Document
- Defined 6 quantitative SLIs/SLOs covering API availability (99.9%), API latency (P95 < 500ms), ML inference latency (P95 < 500ms), cache hit ratio (>85%), data ingestion completion (< 5 min), and queue task age (< 300s).
- Standardized PromQL definitions matching recording rules established in SF-OPS-09.
- Defined 3-tier Error Budget action policy (Normal $\rightarrow$ Warning $\rightarrow$ Feature Freeze).

## 4. Verification Results
- All runbook links referenced in alert annotations across `availability.yml`, `backend.yml`, `database.yml`, `redis.yml`, `celery.yml`, `ml.yml`, `business.yml`, and `monitoring.yml` verified to exist.
- Markdown syntax and line formatting verified across all runbook files.
