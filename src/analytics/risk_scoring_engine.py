"""
Module 03 Risk Scoring Engine (M3-02)
======================================
Production Risk Scoring Engine for Slow-Moving Product Risk Detection.
Normalizes XGBoost inference class probabilities into a standardized Slow-Moving Risk Score (0-100),
assigns operational Risk Priorities (P0-P3), and audits 4 Score Consistency Rules.

Outputs artifacts:
  - data/processed/slow_moving_risk_scores.parquet & .csv
  - reports/risk_scoring_results.json
  - reports/risk_scoring_summary.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class RiskScoringEngine:
    """Production Risk Scoring Engine for M3-02 Risk Scoring Engine."""

    PRIORITY_MAPPING = {
        'CRITICAL': 'P0',
        'HIGH_RISK': 'P1',
        'MEDIUM_RISK': 'P2',
        'LOW_RISK': 'P3'
    }

    CLASS_NAME_TO_IDX = {
        'LOW_RISK': 0,
        'MEDIUM_RISK': 1,
        'HIGH_RISK': 2,
        'CRITICAL': 3
    }

    IDX_TO_CLASS_NAME = {
        0: 'LOW_RISK',
        1: 'MEDIUM_RISK',
        2: 'HIGH_RISK',
        3: 'CRITICAL'
    }

    ACADEMIC_NOTICE = (
        "Module 03 Scope Notice (M3-02): "
        "The Slow-Moving Risk Score (0-100) measures product-level demand stagnation risk based strictly on transaction signals <= t0. "
        "It does NOT represent physical inventory value, stock-on-hand quantities, or financial loss."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def calculate_risk_scores(
        self,
        predictions_df: pd.DataFrame,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Compute normalized risk score (0-100), assign priority (P0-P3), and audit score consistency rules."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if predictions_df is None or predictions_df.empty:
            raise ValueError("Input predictions DataFrame for M3-02 risk scoring is empty or None.")

        df = predictions_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'

        scored_records = []
        valid_count = 0
        invalid_count = 0

        for idx in range(len(df)):
            row = df.iloc[idx]
            sku_val = str(row.get(sku_col, row.get('sku', f'SKU_{idx}')))
            r_class = str(row.get('risk_level', row.get('risk_class', 'LOW_RISK')))

            p_crit = float(row.get('critical_probability', 0.0))
            p_high = float(row.get('high_risk_probability', 0.0))
            p_med = float(row.get('medium_risk_probability', 0.0))
            p_low = float(row.get('low_risk_probability', 0.0))

            probs = [p_low, p_med, p_high, p_crit]
            max_prob = max(probs) if sum(probs) > 0 else float(row.get('risk_probability', 0.5))

            # 1. Normalized Risk Score (0-100)
            r_prob = float(row.get('risk_probability', max_prob))
            r_score = round(r_prob * 100.0, 2)
            r_score = min(max(r_score, 0.0), 100.0)

            # 2. Operational Priority (P0-P3)
            priority = self.PRIORITY_MAPPING.get(r_class, 'P3')

            # 3. Audit 4 Score Consistency Rules
            rule1_pass = 0.0 <= r_prob <= 1.0
            rule2_pass = 0.0 <= r_score <= 100.0
            rule3_pass = abs(r_score - (r_prob * 100.0)) <= 0.05

            argmax_idx = int(np.argmax(probs))
            expected_class = self.IDX_TO_CLASS_NAME.get(argmax_idx, 'LOW_RISK')
            rule4_pass = (r_class == expected_class) if sum(probs) > 0 else True

            status = "VALID" if (rule1_pass and rule2_pass and rule3_pass and rule4_pass) else "INVALID"
            if status == "VALID":
                valid_count += 1
            else:
                invalid_count += 1

            scored_rec = {
                'sku': sku_val,
                'canonical_sku_id': sku_val,
                'product_name': str(row.get('product_name', f'Product {sku_val}')),
                'risk_class': r_class,
                'risk_probability': round(r_prob, 4),
                'risk_score': r_score,
                'risk_priority': priority,
                'critical_probability': round(p_crit, 4),
                'high_risk_probability': round(p_high, 4),
                'medium_risk_probability': round(p_med, 4),
                'low_risk_probability': round(p_low, 4),
                'scoring_status': status,
                'model_version': str(row.get('model_version', 'xgboost_exp03_v1')),
                'feature_schema_version': str(row.get('feature_schema_version', 'M2-FEATURE-v1.0')),
                'prediction_timestamp': str(row.get('prediction_timestamp', datetime.now().isoformat())),
                'session_id': sess_id
            }
            scored_records.append(scored_rec)

        res_df = pd.DataFrame(scored_records)

        # 4. Save Artifacts
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_scores.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_scores.csv')

        try:
            res_df.to_parquet(parquet_path, index=False)
        except Exception as pe:
            print(f"[WARNING] Could not write Parquet file: {pe}")

        res_df.to_csv(csv_path, index=False)

        class_counts = res_df['risk_class'].value_counts().to_dict()
        priority_counts = res_df['risk_priority'].value_counts().to_dict()

        summary = {
            'totalSkusScored': len(res_df),
            'validScoresCount': valid_count,
            'invalidScoresCount': invalid_count,
            'classDistribution': {
                'CRITICAL': int(class_counts.get('CRITICAL', 0)),
                'HIGH_RISK': int(class_counts.get('HIGH_RISK', 0)),
                'MEDIUM_RISK': int(class_counts.get('MEDIUM_RISK', 0)),
                'LOW_RISK': int(class_counts.get('LOW_RISK', 0)),
            },
            'priorityDistribution': {
                'P0': int(priority_counts.get('P0', 0)),
                'P1': int(priority_counts.get('P1', 0)),
                'P2': int(priority_counts.get('P2', 0)),
                'P3': int(priority_counts.get('P3', 0)),
            },
            'avgRiskScore': round(float(res_df['risk_score'].mean()), 2) if not res_df.empty else 0.0,
            'maxRiskScore': round(float(res_df['risk_score'].max()), 2) if not res_df.empty else 0.0,
            'minRiskScore': round(float(res_df['risk_score'].min()), 2) if not res_df.empty else 0.0,
            'academic_notice': self.ACADEMIC_NOTICE
        }

        res_json_path = os.path.join(output_dir, 'risk_scoring_results.json')
        sum_json_path = os.path.join(output_dir, 'risk_scoring_summary.json')

        with open(res_json_path, 'w', encoding='utf-8') as f:
            json.dump({'scored_records': scored_records}, f, indent=2, ensure_ascii=False)

        with open(sum_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return {
            'sessionId': sess_id,
            'status': 'SUCCESS',
            'totalSkus': len(res_df),
            'summary': summary,
            'scores': scored_records,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'results_json': res_json_path,
                'summary_json': sum_json_path
            }
        }
