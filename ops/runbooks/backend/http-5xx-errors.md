# Runbook: Backend High HTTP 5xx Error Rate (`BackendHighErrorRate`)

## 1. Overview
This runbook provides emergency triage and remediation steps when Prometheus triggers the `BackendHighErrorRate` or `BackendCriticalErrorRate` alert for SupplyForge AI Django Backend.

- **Severity**: P1 (CRITICAL if 5xx > 5%) / P2 (MAJOR if 5xx > 1%)
- **Service**: `backend`
- **Team**: `platform`
- **Dashboard**: `http://localhost:3001/d/supplyforge-02-backend-performance`

## 2. Trigger Condition
The rate of HTTP 5xx server error responses exceeds 1% (P2) or 5% (P1) of total incoming request volume continuously for more than 3 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Check Active Error Rate on Grafana
Open the **API & Backend Performance** dashboard and inspect:
- Total Request Traffic vs 5xx Error Rate panel
- Affected HTTP View Endpoints and status code breakdown (500 Internal Error, 502 Bad Gateway, 504 Gateway Timeout)

### Step 2: Inspect Live Backend Application Logs
Run the following command to filter HTTP 5xx traceback logs from the Django container:
```bash
docker logs --tail 200 supplyforge_backend | grep -E "ERROR|CRITICAL|Traceback"
```

### Step 3: Check Dependent Services Health
Verify if database connection failures or cache timeouts are causing 500 errors:
```bash
curl -s http://localhost:8000/health/ready | jq .
```
- If MySQL check fails $\rightarrow$ Refer to `ops/runbooks/mysql/connection-exhaustion.md`
- If Redis check fails $\rightarrow$ Refer to `ops/runbooks/redis/memory-eviction.md`

## 4. Mitigation & Remediation Procedures

### Option A: Restart Stalled Backend Container
If memory leak or thread deadlock is detected:
```bash
docker compose restart backend
```

### Option B: Rollback Faulty Application Release
If errors started immediately following a deployment:
```bash
git checkout HEAD~1
docker compose up -d --build backend
```

### Option C: Enable Emergency Rate Limiting
If an upstream traffic spike is overwhelming backend worker threads, enable rate limiting in Nginx reverse proxy.

## 5. Escalation Path
If 5xx error rate remains $>5\%$ after 15 minutes:
1. Page On-Call Platform Engineer via PagerDuty (P1)
2. Notify `#ops-alerts` Slack channel
3. Initiate Incident Severity Level 1 protocol
