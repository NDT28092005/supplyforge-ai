# Runbook: Celery Queue Backlog & Task Age Delay (`CeleryQueueAgeHigh` / `CeleryQueueBacklogHigh`)

## 1. Overview
This runbook provides diagnostic and recovery procedures when Celery async task queues accumulate backlogs or experience processing delays.

- **Severity**: P1 (`CeleryWorkerDown`) / P2 (`CeleryQueueAgeHigh` > 5m) / P3 (`CeleryQueueBacklogHigh`)
- **Service**: `celery`
- **Team**: `platform`
- **Dashboard**: `http://localhost:3001/d/supplyforge-05-celery-queues`

## 2. Trigger Condition
- `CeleryQueueAgeHigh`: Oldest task age in queue exceeds 300 seconds (5 minutes).
- `CeleryQueueBacklogHigh`: Total queue depth across `data_worker`, `ml_worker`, or `decision_worker` exceeds 100 tasks.

## 3. Diagnostic & Triage Steps

### Step 1: Check Celery Worker Process Status
```bash
docker ps | grep worker
```
Ensure all worker containers (`data_worker`, `ml_worker`, `decision_worker`) are running.

### Step 2: Check Active Queue Depths via Redis
```bash
docker exec -it supplyforge_redis redis-cli llen data_worker
docker exec -it supplyforge_redis redis-cli llen ml_worker
docker exec -it supplyforge_redis redis-cli llen decision_worker
```

### Step 3: Inspect Worker Execution Logs
Check for stuck ML model inferences, infinite loops, or unhandled exceptions:
```bash
docker logs --tail 150 supplyforge_ml_worker
```

## 4. Mitigation & Remediation Procedures

### Option A: Scale Celery Worker Concurrency
Increase worker concurrency for choked queues:
```bash
docker compose up -d --scale ml_worker=3
```

### Option B: Purge Corrupted or Stuck Queue Tasks
If an invalid batch job flooded the queue with poison-pill tasks:
```bash
docker exec -it supplyforge_backend python manage.py celery purge -f -Q ml_worker
```

### Option C: Restart Celery Worker Processes
```bash
docker compose restart ml_worker data_worker decision_worker
```

## 5. Escalation Path
If queue backlog persists for $> 30$ minutes:
1. Escalate to Lead ML / Data Platform Engineer
2. Notify `#ops-alerts` channel
