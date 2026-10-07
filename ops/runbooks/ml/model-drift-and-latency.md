# Runbook: ML Inference Latency & Model Performance (`MLInferenceLatencyHigh` / `MLPredictionErrorRateHigh`)

## 1. Overview
This runbook guides ML Engineers and SREs in resolving ML model inference degradation, prediction error spikes, and feature data missingness.

- **Severity**: P2 (`MLInferenceLatencyHigh` > 1s) / P2 (`MLPredictionErrorRateHigh` > 5%) / P3 (`MLFeatureMissingRateHigh`)
- **Service**: `ml`
- **Team**: `ml_engineering`
- **Dashboard**: `http://localhost:3001/d/supplyforge-06-ml-pipeline-health`

## 2. Trigger Condition
- `MLInferenceLatencyHigh`: P95 model inference & SHAP calculation duration exceeds 1.0 second for 5 minutes.
- `MLPredictionErrorRateHigh`: Prediction failure rate exceeds 5% for 5 minutes.

## 3. Diagnostic & Triage Steps

### Step 1: Inspect ML Pipeline Metrics on Grafana
Check:
- Prediction Volume & Error Rate by `model_version`
- SHAP calculation duration quantile breakdown
- `supplyforge_feature_missing_rate` trend

### Step 2: Inspect ML Worker Memory & CPU Usage
```bash
docker stats supplyforge_ml_worker
```
High memory usage may indicate memory leakage during feature array allocation or SHAP explainer evaluation.

### Step 3: Check Input Feature Pipeline Logs
```bash
docker logs --tail 200 supplyforge_ml_worker | grep -E "ValueError|KeyError|NaN"
```

## 4. Mitigation & Remediation Procedures

### Option A: Fallback to Fast Prediction Mode (Bypass SHAP Explainer)
If SHAP explainability is overloading CPU latency budget, toggle configuration setting to skip SHAP calculation for low-risk items.

### Option B: Fallback to Previous Stable Model Version
If a newly deployed model version causes memory spikes or errors, update model governance version in `ml_model.py` to revert to previous model artifact (`v1.1`).

### Option C: Restart ML Worker
```bash
docker compose restart ml_worker
```

## 5. Escalation Path
If model prediction failure rate $> 10\%$:
1. Notify `#ml-alerts` Slack channel
2. Assign incident ticket to ML Engineering On-Call
