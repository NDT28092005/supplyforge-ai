# Runbook: Prometheus Target Down & Self-Monitoring (`PrometheusTargetDown`)

## 1. Overview
This runbook guides engineers in diagnosing and recovering unreachable monitoring targets or Prometheus self-monitoring alerts.

- **Severity**: P1 (if critical exporter `backend`, `mysql`, `redis` DOWN) / P2 (if `node-exporter`, `cadvisor` DOWN)
- **Service**: `monitoring`
- **Team**: `platform`
- **Dashboard**: `http://localhost:3001/d/supplyforge-01-executive-overview`

## 2. Trigger Condition
Prometheus metric `up == 0` for target `{{ $labels.job }}` for more than 2 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Check Target Endpoint Status via Prometheus UI / API
```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, lastError: .lastError}'
```

### Step 2: Test Direct Exporter Endpoint Connectivity
```bash
# Test backend exporter
curl -I http://localhost:8000/metrics

# Test node-exporter
curl -I http://localhost:9100/metrics

# Test mysql-exporter
curl -I http://localhost:9104/metrics

# Test redis-exporter
curl -I http://localhost:9121/metrics
```

## 4. Mitigation & Remediation Procedures

### Step 1: Restart Failed Exporter Container
```bash
docker compose restart <exporter-container-name>
```

### Step 2: Reload Prometheus Configuration
If target IP or port configuration changed:
```bash
curl -X POST http://localhost:9090/-/reload
```

## 5. Escalation Path
If monitoring plane self-monitoring alerts persist:
1. Alert `#ops-alerts`
2. Check Prometheus disk space (`df -h /prometheus`)
