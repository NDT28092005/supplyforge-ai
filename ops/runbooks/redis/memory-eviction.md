# Runbook: Redis High Memory & Key Eviction (`RedisMemoryHigh` / `RedisEvictionRateHigh`)

## 1. Overview
This runbook guides engineers in troubleshooting Redis cache memory pressure, high key eviction rates, and cache node outages.

- **Severity**: P1 (`RedisDown`) / P2 (`RedisMemoryHigh`) / P3 (`RedisEvictionRateHigh`)
- **Service**: `redis`
- **Team**: `platform`
- **Dashboard**: `http://localhost:3001/d/supplyforge-04-redis-cache`

## 2. Trigger Condition
- `RedisMemoryHigh`: Used memory exceeds 85% of configured `maxmemory` limit for 5 minutes.
- `RedisEvictionRateHigh`: Key eviction rate exceeds 10 keys/sec for 5 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Inspect Memory Info from Redis CLI
```bash
docker exec -it supplyforge_redis redis-cli info memory
```
Check:
- `used_memory_human`
- `maxmemory_human`
- `mem_fragmentation_ratio`

### Step 2: Identify Big Keys in Redis
Run Redis bigkeys scanner to find memory-heavy keys:
```bash
docker exec -it supplyforge_redis redis-cli --bigkeys
```

### Step 3: Check Eviction & Hit Rates
```bash
docker exec -it supplyforge_redis redis-cli info stats | grep -E "keyspace_hits|keyspace_misses|evicted_keys"
```

## 4. Mitigation & Remediation Procedures

### Option A: Flush Non-Critical Temporary Cache Keys
If cache memory is filled with stale session or temporary simulation data:
```bash
docker exec -it supplyforge_redis redis-cli EVAL "return redis.call('del', unpack(redis.call('keys', 'cache:temp:*')))" 0
```

### Option B: Increase Max Memory (If Host RAM permits)
```bash
docker exec -it supplyforge_redis redis-cli CONFIG SET maxmemory 2gb
```

### Option C: Trigger Celery Cache Warmup
If important risk matrix cache was evicted, trigger Cache Warming task to rebuild critical cache entries.

## 5. Escalation Path
If Redis memory pressure causes Celery task broker drop:
1. Alert `#ops-alerts`
2. Restart Celery Workers to reconnect to Redis broker
