# Runbook: ML Inference Latency & Prediction Failures

## 1. Overview
This runbook guides ML Engineers and SREs in resolving inference degradation and prediction error spikes.

- **Severity**: P2 (`SupplyForgeMLInferenceLatencyHigh` > 2s) / P2 (`SupplyForgePredictionFailureRateHigh` > 5%)
- **Service**: `ml`
- **Team**: `ml_engineering`
- **Dashboard**: `http://localhost:3001/d/supplyforge-06-ml-pipeline-health`

## 2. Trigger Condition
- `SupplyForgeMLInferenceLatencyHigh`: P95 raw model inference exceeds 2 seconds for 5 minutes.
- `SupplyForgePredictionFailureRateHigh`: Prediction failure rate exceeds 5% for 5 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Inspect ML Pipeline Metrics on Grafana
Check:
- Prediction volume and `supplyforge:business:prediction_failure_rate` by model/version.
- `supplyforge:business:model_inference_duration:p95` by model/version.
- Current `supplyforge_business_portfolio_skus` distribution to determine whether the observed workload changed.
- `supplyforge_business_dataset_quality_score` before treating the issue as a model problem.

### Step 2: Inspect ML Worker Memory & CPU Usage
```bash
docker stats supplyforge_ml_worker
```
High memory usage may indicate memory leakage during feature array allocation or SHAP explainer evaluation.

### Step 3: Check Input and Model Worker Logs
```bash
docker logs --tail 200 supplyforge_ml_worker | grep -E "ValueError|KeyError|NaN"
```

## 4. Mitigation & Remediation Procedures

### Option A: Reduce Explainability Workload Outside the Critical Path
If explanation generation is contributing to worker pressure, move it to the existing asynchronous path. Do not remove audit explanations without an approved product and governance decision.

### Option B: Fallback to Previous Stable Model Version
If a newly deployed model version causes latency or errors, use the approved model-governance rollback path. Do not edit a deployed model version directly in source code during an incident.

### Option C: Restart ML Worker
```bash
docker compose restart ml_worker
```

## 5. Escalation Path
If model prediction failure rate $> 10\%$:
1. Notify `#ml-alerts` Slack channel
2. Assign incident ticket to ML Engineering On-Call
