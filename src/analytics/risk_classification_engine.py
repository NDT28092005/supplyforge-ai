"""
Module 03 Risk Classification Engine (M3-03)
=============================================
Production Risk Classification Engine for Slow-Moving Product Risk Detection.
Maps model class probabilities into formal Argmax Risk Classes (CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK),
assigns Operational Severity (SEVERE, HIGH, MODERATE, LOW), calculates Classification Confidence,
and performs Ambiguity Detection based on top-1 vs top-2 probability margin.

Outputs artifacts:
  - data/processed/slow_moving_risk_classifications.parquet & .csv
  - reports/risk_classification_results.json
  - reports/risk_classification_summary.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class RiskClassificationEngine:
    """Production Risk Classification Engine for M3-03 Risk Classification."""

    SEVERITY_MAPPING = {
        'CRITICAL': 'SEVERE',
        'HIGH_RISK': 'HIGH',
        'MEDIUM_RISK': 'MODERATE',
        'LOW_RISK': 'LOW'
    }

    IDX_TO_CLASS_NAME = {
        0: 'LOW_RISK',
        1: 'MEDIUM_RISK',
        2: 'HIGH_RISK',
        3: 'CRITICAL'
    }

    CLASS_NAME_TO_IDX = {
        'LOW_RISK': 0,
        'MEDIUM_RISK': 1,
        'HIGH_RISK': 2,
        'CRITICAL': 3
    }

    ACADEMIC_NOTICE = (
        "Module 03 Scope Notice (M3-03): "
        "Slow-Moving Product Risk Classification is derived strictly from observable demand signals <= t0. "
        "It does NOT represent physical inventory stockout, dead stock, or warehouse asset loss."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def classify_sku_risks(
        self,
        scored_df: pd.DataFrame,
        ambiguity_threshold: float = 0.10,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Execute Argmax classification, Severity mapping, Confidence calculation, and Ambiguity detection."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if scored_df is None or scored_df.empty:
            raise ValueError("Input scored DataFrame for M3-03 risk classification is empty or None.")

        df = scored_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'

        classification_records = []
        confident_count = 0
        ambiguous_count = 0

        for idx in range(len(df)):
            row = df.iloc[idx]
            sku_val = str(row.get(sku_col, row.get('sku', f'SKU_{idx}')))

            p_crit = float(row.get('critical_probability', 0.0))
            p_high = float(row.get('high_risk_probability', 0.0))
            p_med = float(row.get('medium_risk_probability', 0.0))
            p_low = float(row.get('low_risk_probability', 0.0))

            probs = [p_low, p_med, p_high, p_crit]

            # 1. Formal Argmax Classification Rule
            if sum(probs) > 0:
                argmax_idx = int(np.argmax(probs))
                r_class = self.IDX_TO_CLASS_NAME.get(argmax_idx, 'LOW_RISK')
                p_max = float(probs[argmax_idx])
            else:
                r_class = str(row.get('risk_class', 'LOW_RISK'))
                p_max = float(row.get('risk_probability', 0.5))

            # 2. Operational Severity Mapping
            severity = self.SEVERITY_MAPPING.get(r_class, 'LOW')

            # 3. Classification Confidence Calculation
            confidence = round(p_max, 4)
            confidence_pct = round(p_max * 100.0, 2)

            # 4. Ambiguity Detection (Margin Analysis)
            sorted_probs = sorted(probs, reverse=True) if sum(probs) > 0 else [p_max, 0.0]
            p_second = float(sorted_probs[1]) if len(sorted_probs) > 1 else 0.0
            margin = round(p_max - p_second, 4)
            margin_pct = round(margin * 100.0, 2)

            status = "AMBIGUOUS" if margin < ambiguity_threshold else "CONFIDENT"
            if status == "CONFIDENT":
                confident_count += 1
            else:
                ambiguous_count += 1

            r_score = float(row.get('risk_score', round(p_max * 100.0, 2)))

            rec = {
                'sku': sku_val,
                'canonical_sku_id': sku_val,
                'product_name': str(row.get('product_name', f'Product {sku_val}')),
                'risk_class': r_class,
                'risk_score': r_score,
                'classification_confidence': confidence,
                'confidence_percentage': f"{confidence_pct}%",
                'severity': severity,
                'classification_status': status,
                'prob_margin': margin,
                'margin_percentage': f"{margin_pct}%",
                'critical_probability': round(p_crit, 4),
                'high_risk_probability': round(p_high, 4),
                'medium_risk_probability': round(p_med, 4),
                'low_risk_probability': round(p_low, 4),
                'model_version': str(row.get('model_version', 'xgboost_exp03_v1')),
                'feature_schema_version': str(row.get('feature_schema_version', 'M2-FEATURE-v1.0')),
                'prediction_timestamp': str(row.get('prediction_timestamp', datetime.now().isoformat())),
                'session_id': sess_id
            }
            classification_records.append(rec)

        res_df = pd.DataFrame(classification_records)

        # 5. Save Artifacts
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_classifications.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')

        try:
            res_df.to_parquet(parquet_path, index=False)
        except Exception as pe:
            print(f"[WARNING] Could not write Parquet file: {pe}")

        res_df.to_csv(csv_path, index=False)

        class_counts = res_df['risk_class'].value_counts().to_dict()
        severity_counts = res_df['severity'].value_counts().to_dict()
        status_counts = res_df['classification_status'].value_counts().to_dict()

        summary = {
            'totalSkusClassified': len(res_df),
            'confidentCount': confident_count,
            'ambiguousCount': ambiguous_count,
            'ambiguityThreshold': ambiguity_threshold,
            'classDistribution': {
                'CRITICAL': int(class_counts.get('CRITICAL', 0)),
                'HIGH_RISK': int(class_counts.get('HIGH_RISK', 0)),
                'MEDIUM_RISK': int(class_counts.get('MEDIUM_RISK', 0)),
                'LOW_RISK': int(class_counts.get('LOW_RISK', 0)),
            },
            'severityDistribution': {
                'SEVERE': int(severity_counts.get('SEVERE', 0)),
                'HIGH': int(severity_counts.get('HIGH', 0)),
                'MODERATE': int(severity_counts.get('MODERATE', 0)),
                'LOW': int(severity_counts.get('LOW', 0)),
            },
            'statusDistribution': {
                'CONFIDENT': int(status_counts.get('CONFIDENT', 0)),
                'AMBIGUOUS': int(status_counts.get('AMBIGUOUS', 0)),
            },
            'avgConfidence': round(float(res_df['classification_confidence'].mean()), 4) if not res_df.empty else 0.0,
            'academic_notice': self.ACADEMIC_NOTICE
        }

        res_json_path = os.path.join(output_dir, 'risk_classification_results.json')
        sum_json_path = os.path.join(output_dir, 'risk_classification_summary.json')

        with open(res_json_path, 'w', encoding='utf-8') as f:
            json.dump({'classifications': classification_records}, f, indent=2, ensure_ascii=False)

        with open(sum_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return {
            'sessionId': sess_id,
            'status': 'SUCCESS',
            'totalSkus': len(res_df),
            'summary': summary,
            'classifications': classification_records,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'results_json': res_json_path,
                'summary_json': sum_json_path
            }
        }
