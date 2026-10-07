# SupplyForge AI Service Level Objectives (SLO) & Error Budget Policy

## 1. Overview & Objectives
This document establishes formal Service Level Objectives (SLOs) and Error Budget management policies for SupplyForge AI. All objectives are continuously measured by Prometheus PromQL rules and reported on Grafana dashboards.

## 2. Core Service Level Indicators (SLIs) & Objectives (SLOs)

| Service Area | Indicator (SLI) | Target SLO (30-Day Window) | PromQL Measurement Definition | Monthly Error Budget |
| :--- | :--- | :--- | :--- | :--- |
| **API Availability** | Successful HTTP Requests (non-5xx) | **99.9%** | `(1 - (sum(rate(django_http_requests_total_by_status_5xx_total[30d])) / sum(rate(django_http_requests_total_by_method_total[30d])))) * 100` | 43 min 12 sec downtime |
| **API Latency** | P95 API Response Latency | **< 500ms** | `histogram_quantile(0.95, sum(rate(django_http_requests_latency_seconds_by_view_bucket[5m])) by (le)) < 0.5` | 5% requests $> 500\text{ms}$ |
| **ML Inference** | P95 Risk Model Prediction Latency | **< 500ms** | `histogram_quantile(0.95, sum(rate(supplyforge_prediction_duration_seconds_bucket[5m])) by (le)) < 0.5` | 5% predictions $> 500\text{ms}$ |
| **Cache Hit Ratio** | P95 Domain Cache Hit Ratio | **> 85%** | `(sum(rate(supplyforge_cache_hit_total[5m])) / (sum(rate(supplyforge_cache_hit_total[5m])) + sum(rate(supplyforge_cache_miss_total[5m])))) * 100 > 85` | N/A |
| **Data Ingestion** | Batch Import Completion Latency | **95% < 5 min** | `histogram_quantile(0.95, sum(rate(supplyforge_import_duration_seconds_bucket[5m])) by (le)) < 300` | 5% imports $> 5\text{min}$ |
| **Celery Queue Delay** | Max Task Age in Queue | **< 300s** | `max(supplyforge_task_age_seconds) < 300` | N/A |

## 3. Error Budget Consumption & Action Policy

- **75% Budget Remaining**: Normal operations. Feature deployments continue as planned.
- **50% Budget Consumed**: Warning state. Engineering teams review minor alerts and perform optimization sprints.
- **100% Budget Exhausted**: Feature Freeze. All non-critical feature deployments are halted. Engineering focus shifts exclusively to reliability, bug fixes, and infrastructure stabilization until budget resets at the start of the next 30-day window.
