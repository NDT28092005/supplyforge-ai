"""Unified DSS Pipeline Orchestration API Module."""
import json
import yaml
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

from src.ingestion.validator import validate_input_data
from src.preprocessing.features import preprocess_features
from src.prediction.predictor import RiskPredictor
from src.explainability.explainer import SHAPExplainer
from src.business_rules.rule_engine import evaluate_business_rules, STANDARD_DSS_CAVEATS
from src.calibration.calibrator import calibrate_probability
from src.decision_policy.policy import assign_decision_policy
from src.llm.narrator import generate_merchant_report

class DSSPipeline:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        
        # Load configs
        with open(project_root / "configs" / "model_config.yaml", "r", encoding="utf-8") as f:
            self.model_config = yaml.safe_load(f)
            
        model_pkl_path = project_root / self.model_config["model_pkl_path"]
        self.predictor = RiskPredictor(model_pkl_path)
        
        # Load Business Feature Mapping
        biz_map_csv = project_root / self.model_config["business_mapping_csv"]
        if biz_map_csv.exists():
            df_map = pd.read_csv(biz_map_csv)
            biz_name_map = dict(zip(df_map["feature_name"], df_map["business_name_vi"]))
        else:
            biz_name_map = {}
            
        self.explainer = SHAPExplainer(self.predictor.model, self.predictor.feature_cols, biz_name_map)

    def run(self, df_gt: pd.DataFrame, df_fc: pd.DataFrame, cutoff_date: str = "2025-10-16") -> Tuple[List[Dict], List[str]]:
        """Run end-to-end DSS pipeline returning (dss_payloads, merchant_reports)."""
        df_merged, _ = preprocess_features(df_gt, df_fc)
        
        preds_enc, preds_lbl, probs = self.predictor.predict(df_merged)
        
        payloads = []
        reports  = []
        
        for i in range(len(df_merged)):
            row = df_merged.iloc[i]
            sku_id = str(row["itemId"])
            risk_lvl = preds_lbl[i]
            
            raw_risk_prob = float(probs[i][self.predictor.critical_idx] + probs[i][self.predictor.high_idx])
            calib_prob = calibrate_probability(raw_risk_prob)
            
            policy_res = assign_decision_policy(calib_prob)
            rule_res   = evaluate_business_rules(row, risk_lvl)
            
            # SHAP evidence
            target_class_idx = self.predictor.critical_idx if risk_lvl == "CRITICAL" else self.predictor.high_idx
            shap_evidence = self.explainer.explain_sku(df_merged[self.predictor.feature_cols].values[i], target_class_idx, top_k=3)
            
            payload = {
                "itemId": sku_id,
                "decision_cutoff_t0": cutoff_date,
                "risk_level": risk_lvl,
                "predicted_risk_prob": round(raw_risk_prob, 4),
                "calibrated_risk_prob": round(calib_prob, 4),
                "priority_tier": policy_res["tier_code"],
                "tier_display": policy_res["tier_display"],
                "demand_pattern": str(row.get("demand_pattern", "Gián đoạn")),
                "sales_velocity_90d": round(float(row.get("sales_velocity_90d", 0)), 4),
                "dsls_days": float(row.get("dsls", 0)),
                "zero_rate_90d": round(float(row.get("zero_rate_90d", 0)), 4),
                "tsb_demand_prob": round(float(row.get("demand_probability", 0)), 4),
                "shap_top_evidence": shap_evidence,
                "business_cause_tags": rule_res["business_cause_tags"],
                "interpretations_vi": rule_res["interpretations_vi"],
                "recommended_actions_vi": rule_res["recommended_actions_vi"],
                "dss_caveats": STANDARD_DSS_CAVEATS
            }
            
            rpt_text = generate_merchant_report(payload)
            payload["merchant_report"] = rpt_text
            
            payloads.append(payload)
            reports.append(rpt_text)
            
        return payloads, reports
