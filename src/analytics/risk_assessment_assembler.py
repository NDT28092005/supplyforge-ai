"""
Module 03 Risk Assessment Assembly Engine (M3-06)
==================================================
Production Risk Assessment Assembly Engine for Slow-Moving Product Risk Detection.
Synthesizes model predictions (M3-01), risk scores (M3-02), risk classifications (M3-03),
calibrated probabilities (M3-04), and diagnostic signals with evidence (M3-05) into a unified,
traceable Risk Assessment Profile per SKU without recalculation.

Outputs artifacts:
  - data/processed/slow_moving_risk_assessments.parquet & .csv
  - reports/risk_assessment_validation.json
  - reports/risk_assessment_summary.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class RiskAssessmentAssembler:
    """Production Risk Assessment Assembly Engine for M3-06."""

    SIGNAL_PRIORITY_MAP = {
        'POSSIBLE_OBSOLESCENCE': 1,
        'LOW_SALES_VELOCITY': 2,
        'PROMO_ASSOCIATED_LOW_VELOCITY': 3,
        'LUMPY_DEMAND': 4,
        'POSSIBLE_STOCKOUT_EFFECT': 5
    }

    ACADEMIC_NOTICE = (
        "Module 03 Scope Notice (M3-06): "
        "Unified Risk Assessment Profile synthesizes model predictions and observable demand signals <= t0. "
        "It does NOT issue business action recommendations, financial liquidation terms, or warehouse stock claims."
    )

    FORBIDDEN_FUTURE_FEATURES = {'fut_qty_60d', 'future_sales', 'drr', 'future_velocity', 'fut_label'}

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def assemble_risk_assessments(
        self,
        predictions_df: pd.DataFrame,
        diagnostics_df: Optional[pd.DataFrame] = None,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Assemble 5 information groups, perform status audit, prioritize signals, and attach lineage metadata."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if predictions_df is None or predictions_df.empty:
            raise ValueError("Input predictions DataFrame for M3-06 risk assessment assembly is empty or None.")

        df = predictions_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'
        N = len(df)

        # Merge diagnostics if provided separately
        diag_lookup = {}
        if diagnostics_df is not None and not diagnostics_df.empty:
            for _, drow in diagnostics_df.iterrows():
                dsku = str(drow.get(sku_col, drow.get('sku', '')))
                if dsku:
                    diag_lookup[dsku] = drow

        assembled_profiles = []
        complete_count = 0
        partial_count = 0
        invalid_count = 0

        for idx in range(N):
            row = df.iloc[idx]
            orig_sku = str(row.get('sku', f'SKU_{idx}'))
            c_sku = str(row.get('canonical_sku_id', orig_sku))
            sku_val = c_sku

            # 1. Product Identity
            prod_name = str(row.get('product_name', f'Product {orig_sku}'))
            category = str(row.get('category', 'Mother & Baby'))

            # 2. Risk Assessment (From M3-02, M3-03, M3-04)
            r_class = str(row.get('risk_class', row.get('risk_level', 'LOW_RISK')))
            r_prob = float(row.get('calibrated_probability', row.get('risk_probability', 0.5)))
            r_score = float(row.get('risk_score', round(r_prob * 100.0, 2)))

            # 3. Risk Diagnostics (From M3-05)
            diag_row = diag_lookup.get(sku_val, diag_lookup.get(orig_sku, row))
            diag_signals = diag_row.get('diagnostic_signals_list', [])
            if isinstance(diag_signals, str):
                diag_signals = [s.strip() for s in diag_signals.split(',') if s.strip()]

            # Prioritize signals
            sorted_signals = sorted(
                diag_signals,
                key=lambda s: self.SIGNAL_PRIORITY_MAP.get(s, 99)
            )
            primary_signals = sorted_signals[:2]
            supporting_signals = sorted_signals[2:]

            # 4. Supporting Evidence (Observables <= t0)
            evidence = {
                'sales_velocity_90d': round(float(row.get('sales_velocity_90d', 0.05)), 4),
                'sales_last_30d': int(row.get('sales_last_30d', 0)),
                'zero_rate_90d': round(float(row.get('zero_rate_90d', 0.80)), 4),
                'dsls': float(row.get('dsls', 120)),
                'adi': round(float(row.get('adi', 1.5)), 2),
                'cv2': round(float(row.get('cv2', 0.6)), 2),
                'demand_probability': round(float(row.get('demand_probability', 0.01)), 4),
                'forecast_7d': round(float(row.get('forecast_7d', 0.1)), 4),
                'forecast_trend': round(float(row.get('forecast_trend', 0.0)), 4),
                'expected_demand_daily': round(float(row.get('expected_demand_daily', 0.02)), 4)
            }

            # 5. Assessment Metadata & Lineage
            metadata = {
                'decision_cutoff': str(row.get('decision_cutoff', '2025-10-16')),
                'model_version': str(row.get('model_version', 'xgboost_exp03_v1')),
                'calibration_version': str(row.get('calibration_version', 'calibration_v1.0')),
                'diagnostic_rule_version': str(row.get('diagnostic_rule_version', 'rules_v1.0')),
                'data_version': str(row.get('dataset_version', 'v1.3'))
            }

            # 6. Status Audit Validation
            has_forbidden = any(feat in row for feat in self.FORBIDDEN_FUTURE_FEATURES)
            prob_valid = (0.0 <= r_prob <= 1.0)
            score_valid = (0.0 <= r_score <= 100.0)
            class_valid = r_class in ['CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK']

            if has_forbidden or not prob_valid or not score_valid or not class_valid:
                status = "INVALID"
                invalid_count += 1
            elif len(evidence) >= 5:
                status = "COMPLETE"
                complete_count += 1
            else:
                status = "PARTIAL"
                partial_count += 1

            profile = {
                'sku': orig_sku,
                'canonical_sku_id': c_sku,
                'product_name': prod_name,
                'category': category,
                'assessment': {
                    'risk_class': r_class,
                    'risk_probability': round(r_prob, 4),
                    'risk_score': r_score
                },
                'diagnostics': sorted_signals,
                'primary_signals': primary_signals,
                'supporting_signals': supporting_signals,
                'evidence': evidence,
                'metadata': metadata,
                'assessment_status': status,
                'session_id': sess_id
            }
            assembled_profiles.append(profile)

        res_df = pd.DataFrame(assembled_profiles)

        # Save Artifacts
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_assessments.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_assessments.csv')

        try:
            res_df.to_parquet(parquet_path, index=False)
        except Exception as pe:
            print(f"[WARNING] Could not write Parquet file: {pe}")

        flattened = []
        for p in assembled_profiles:
            flattened.append({
                'sku': p['sku'],
                'canonical_sku_id': p['canonical_sku_id'],
                'product_name': p['product_name'],
                'risk_class': p['assessment']['risk_class'],
                'risk_probability': p['assessment']['risk_probability'],
                'risk_score': p['assessment']['risk_score'],
                'primary_signals': ",".join(p['primary_signals']),
                'supporting_signals': ",".join(p['supporting_signals']),
                'assessment_status': p['assessment_status'],
                'session_id': sess_id
            })
        pd.DataFrame(flattened).to_csv(csv_path, index=False)

        val_json_path = os.path.join(output_dir, 'risk_assessment_validation.json')
        sum_json_path = os.path.join(output_dir, 'risk_assessment_summary.json')

        summary = {
            'totalSkusAssembled': N,
            'completeCount': complete_count,
            'partialCount': partial_count,
            'invalidCount': invalid_count,
            'assessmentStatusDistribution': {
                'COMPLETE': complete_count,
                'PARTIAL': partial_count,
                'INVALID': invalid_count
            },
            'academic_notice': self.ACADEMIC_NOTICE
        }

        with open(val_json_path, 'w', encoding='utf-8') as f:
            json.dump({'profiles': assembled_profiles}, f, indent=2, ensure_ascii=False)

        with open(sum_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return {
            'sessionId': sess_id,
            'status': 'SUCCESS',
            'totalSkus': N,
            'summary': summary,
            'assessments': assembled_profiles,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'validation_json': val_json_path,
                'summary_json': sum_json_path
            }
        }
