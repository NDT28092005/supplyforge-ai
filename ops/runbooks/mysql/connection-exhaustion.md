# Runbook: MySQL Connection Exhaustion & Database Down (`MySQLConnectionSaturation` / `MySQLDown`)

## 1. Overview
This runbook guides engineers in diagnosing and resolving MySQL connection saturation and outage alerts.

- **Severity**: P1 (CRITICAL)
- **Service**: `database`
- **Team**: `platform`
- **Dashboard**: `http://localhost:3001/d/supplyforge-03-mysql-database`

## 2. Trigger Condition
- `MySQLDown`: `mysql_up == 0` for 1 minute.
- `MySQLConnectionSaturation`: Active client threads connected $> 85\%$ of `max_connections` limit for 3 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Check Container Process Status
```bash
docker ps | grep mysql
```
If container has exited, check container exit code and logs:
```bash
docker logs --tail 100 supplyforge_mysql
```

### Step 2: Inspect Active Database Queries
Log into MySQL instance and list running process queries:
```bash
docker exec -it supplyforge_mysql mysql -u root -p -e "SHOW FULL PROCESSLIST;"
```
Look for:
- Long-running unindexed SELECT queries (`Time > 30s`)
- Queries in status `Waiting for table metadata lock` or `Locked`

### Step 3: Check Slow Query Logs
```bash
docker exec -it supplyforge_mysql tail -n 50 /var/log/mysql/slow.log
```

## 4. Mitigation & Remediation Procedures

### Option A: Kill Long-Running Sleeping/Stuck Connections
Kill orphaned sleeping queries that hold connection locks:
```bash
docker exec -it supplyforge_mysql mysql -u root -p -e "
SELECT CONCAT('KILL ', id, ';') 
FROM information_schema.processlist 
WHERE command = 'Sleep' AND time > 60;"
```

### Option B: Increase Max Connections Limit (Temporary Relief)
```bash
docker exec -it supplyforge_mysql mysql -u root -p -e "SET GLOBAL max_connections = 300;"
```

### Option C: Restart MySQL Container
If database is unresponsive or deadlocked:
```bash
docker compose restart mysql
```

## 5. Escalation Path
If database is unrecoverable or data corruption is suspected:
1. Trigger P1 PagerDuty On-Call page
2. Prepare point-in-time database backup restore from latest MySQL snapshot
