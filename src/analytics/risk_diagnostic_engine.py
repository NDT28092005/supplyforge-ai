"""
Module 03 Risk Diagnostic Engine (M3-05)
=========================================
Production Risk Diagnostic Engine for Slow-Moving Product Risk Detection.
Transforms model outputs (M3-01 to M3-04) and observable feature signals (Module 2) into structured
Risk Diagnostic Profiles using 5 deterministic business rules (D01-D05) with attached metric evidence.

Outputs artifacts:
  - data/processed/slow_moving_risk_diagnostics.parquet & .csv
  - reports/diagnostic_rule_validation.json
  - reports/diagnostic_signal_distribution.csv
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class RiskDiagnosticEngine:
    """Production Risk Diagnostic Engine for M3-05."""

    ACADEMIC_NOTICE = (
        "Module 03 Scope Notice (M3-05): "
        "Diagnostic signals describe observable demand and transaction patterns <= t0. "
        "They do NOT constitute causal claims of physical warehouse stockouts or inventory value loss."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def diagnose_sku_risks(
        self,
        predictions_df: pd.DataFrame,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Execute 5 deterministic diagnostic rules, attach metric evidence, and generate Risk Diagnostic Profiles."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if predictions_df is None or predictions_df.empty:
            raise ValueError("Input predictions DataFrame for M3-05 risk diagnostics is empty or None.")

        df = predictions_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'
        N = len(df)

        diagnostic_profiles = []
        signal_counts = {
            'LOW_SALES_VELOCITY': 0,
            'LUMPY_DEMAND': 0,
            'POSSIBLE_OBSOLESCENCE': 0,
            'PROMO_ASSOCIATED_LOW_VELOCITY': 0,
            'POSSIBLE_STOCKOUT_EFFECT': 0
        }

        for idx in range(N):
            row = df.iloc[idx]
            sku_val = str(row.get(sku_col, row.get('sku', f'SKU_{idx}')))

            r_class = str(row.get('risk_class', row.get('risk_level', 'LOW_RISK')))
            r_prob = float(row.get('calibrated_probability', row.get('risk_probability', 0.5)))
            r_score = float(row.get('risk_score', round(r_prob * 100.0, 2)))

            # Observables
            v90 = float(row.get('sales_velocity_90d', 0.05))
            adi = float(row.get('adi', 1.5))
            cv2 = float(row.get('cv2', 0.6))
            dsls = float(row.get('dsls', 120))
            promo_rate = float(row.get('promo_rate', 0.0))
            zero_rate_90d = float(row.get('zero_rate_90d', 0.80))
            sales_last_30d = float(row.get('sales_last_30d', 0))
            active_30d = bool(row.get('active_30d', sales_last_30d > 0 or v90 > 0))

            diagnostics = []
            signal_codes = []

            # Rule D01: LOW_SALES_VELOCITY
            if v90 < 0.1:
                signal_codes.append('LOW_SALES_VELOCITY')
                signal_counts['LOW_SALES_VELOCITY'] += 1
                diagnostics.append({
                    'code': 'LOW_SALES_VELOCITY',
                    'severity': 'HIGH',
                    'evidence': {
                        'metric': 'sales_velocity_90d',
                        'value': round(v90, 4),
                        'threshold': 0.1,
                        'comparison': '<'
                    }
                })

            # Rule D02: LUMPY_DEMAND
            if adi > 1.32 and cv2 > 0.49:
                signal_codes.append('LUMPY_DEMAND')
                signal_counts['LUMPY_DEMAND'] += 1
                diagnostics.append({
                    'code': 'LUMPY_DEMAND',
                    'severity': 'MEDIUM',
                    'evidence': {
                        'adi': round(adi, 2),
                        'adi_threshold': 1.32,
                        'cv2': round(cv2, 2),
                        'cv2_threshold': 0.49
                    }
                })

            # Rule D03: POSSIBLE_OBSOLESCENCE
            if dsls > 180 or r_class == 'CRITICAL':
                signal_codes.append('POSSIBLE_OBSOLESCENCE')
                signal_counts['POSSIBLE_OBSOLESCENCE'] += 1
                diagnostics.append({
                    'code': 'POSSIBLE_OBSOLESCENCE',
                    'severity': 'HIGH',
                    'evidence': {
                        'dsls': dsls,
                        'dsls_threshold': 180,
                        'risk_class': r_class,
                        'trigger_reason': 'dsls > 180' if dsls > 180 else 'risk_class == CRITICAL'
                    }
                })

            # Rule D04: PROMO_ASSOCIATED_LOW_VELOCITY
            if promo_rate > 0.20 and v90 < 0.5:
                signal_codes.append('PROMO_ASSOCIATED_LOW_VELOCITY')
                signal_counts['PROMO_ASSOCIATED_LOW_VELOCITY'] += 1
                diagnostics.append({
                    'code': 'PROMO_ASSOCIATED_LOW_VELOCITY',
                    'severity': 'MEDIUM',
                    'evidence': {
                        'promo_rate': round(promo_rate, 4),
                        'promo_rate_threshold': 0.20,
                        'sales_velocity_90d': round(v90, 4),
                        'velocity_threshold': 0.50
                    }
                })

            # Rule D05: POSSIBLE_STOCKOUT_EFFECT
            if zero_rate_90d > 0.70 and active_30d:
                signal_codes.append('POSSIBLE_STOCKOUT_EFFECT')
                signal_counts['POSSIBLE_STOCKOUT_EFFECT'] += 1
                diagnostics.append({
                    'code': 'POSSIBLE_STOCKOUT_EFFECT',
                    'severity': 'MEDIUM',
                    'evidence': {
                        'zero_rate_90d': round(zero_rate_90d, 4),
                        'zero_rate_threshold': 0.70,
                        'active_30d': active_30d
                    }
                })

            profile = {
                'sku': sku_val,
                'canonical_sku_id': sku_val,
                'product_name': str(row.get('product_name', f'Product {sku_val}')),
                'risk': {
                    'class': r_class,
                    'probability': round(r_prob, 4),
                    'score': r_score
                },
                'diagnostics': diagnostics,
                'diagnostic_signals_list': signal_codes,
                'diagnostic_count': len(diagnostics),
                'model_version': str(row.get('model_version', 'xgboost_exp03_v1')),
                'feature_schema_version': str(row.get('feature_schema_version', 'M2-FEATURE-v1.0')),
                'prediction_timestamp': str(row.get('prediction_timestamp', datetime.now().isoformat())),
                'session_id': sess_id
            }
            diagnostic_profiles.append(profile)

        res_df = pd.DataFrame(diagnostic_profiles)

        # Save Artifacts
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_diagnostics.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_diagnostics.csv')

        try:
            res_df.to_parquet(parquet_path, index=False)
        except Exception as pe:
            print(f"[WARNING] Could not write Parquet file: {pe}")

        # Flatten diagnostics for CSV
        flattened_recs = []
        for p in diagnostic_profiles:
            flattened_recs.append({
                'sku': p['sku'],
                'canonical_sku_id': p['canonical_sku_id'],
                'product_name': p['product_name'],
                'risk_class': p['risk']['class'],
                'risk_probability': p['risk']['probability'],
                'risk_score': p['risk']['score'],
                'diagnostic_signals': ",".join(p['diagnostic_signals_list']),
                'diagnostic_count': p['diagnostic_count'],
                'session_id': sess_id
            })
        pd.DataFrame(flattened_recs).to_csv(csv_path, index=False)

        # Rule Validation & Signal Distribution CSV
        dist_records = [
            {'signal_code': code, 'triggered_count': count, 'trigger_rate': round(count / N, 4) if N > 0 else 0.0}
            for code, count in signal_counts.items()
        ]
        dist_df = pd.DataFrame(dist_records)
        dist_csv_path = os.path.join(output_dir, 'diagnostic_signal_distribution.csv')
        dist_df.to_csv(dist_csv_path, index=False)

        validation_json_path = os.path.join(output_dir, 'diagnostic_rule_validation.json')
        summary = {
            'totalSkusDiagnosed': N,
            'signalCounts': signal_counts,
            'signalDistribution': dist_records,
            'academic_notice': self.ACADEMIC_NOTICE
        }
        with open(validation_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return {
            'sessionId': sess_id,
            'status': 'SUCCESS',
            'totalSkus': N,
            'summary': summary,
            'profiles': diagnostic_profiles,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'validation_json': validation_json_path,
                'distribution_csv': dist_csv_path
            }
        }
