"""
Slow-Moving Risk Feature Scoring Engine — Module 02 Analytics (M2-05)
========================================================================
Calculates deterministic diagnostic risk signals, component risk scores, and a
composite Slow-Moving Signal Score (0.0 -> 1.0) for each SKU at decision cutoff t0.

Guardrails & Positioning:
  G1 — No Future Leakage: Intercepts future-derived variables (fut_qty_60d, DRR, risk_label).
  G2 — No Inventory Overclaim: Interrupted signals state transaction risk evidence, NOT actual stock on hand.
  G3 — No Causal Claim: Diagnostic flags express correlation/association, NOT causality.
  G4 — No Ground Truth Modification: Scoring is a feature layer, does NOT modify frozen EXP-02 labels.

Outputs artifacts to:
  - data/processed/slow_moving_risk_scores.parquet & .csv
  - reports/risk_scoring_config.json
  - reports/risk_scoring_summary.json
  - reports/risk_scoring_distribution.csv
  - reports/risk_scoring_quality.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class FeatureLeakageError(Exception):
    """Raised when forbidden future-derived features are detected in feature matrix."""
    pass


class RiskFeatureScorer:
    """Canonical Slow-Moving Risk Feature Scoring Engine (M2-05)."""

    FORBIDDEN_COLUMNS = {
        'fut_qty_60d', 'fut_velocity', 'fut_velocity_60d', 'future_velocity',
        'drr', 'drr_ratio', 'slow_moving_label', 'risk_label', 'future_sales',
        'future_quantity', 'ground_truth_label', 'future_demand', 'label'
    }

    DEFAULT_THRESHOLDS = {
        'velocity_low_threshold': 0.05,
        'velocity_very_low_threshold': 0.01,
        'dsls_stale_threshold': 60,
        'dsls_high_recency_threshold': 120,
        'zero_rate_high_threshold': 0.80,
        'demand_prob_low_threshold': 0.15,
        'weights': {
            'recency': 0.25,
            'velocity': 0.25,
            'zero_rate': 0.20,
            'intermittency': 0.15,
            'forecast': 0.15
        }
    }

    ACADEMIC_DISCLAIMER = (
        "Academic Boundary & Guardrail Notice (G2/G3): "
        "Diagnostic signals and composite scores reflect slow-moving product risk evidence based on transaction data <= t0. "
        "They do NOT constitute stock-on-hand inventory valuation or causal claims."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def compute_risk_scores(
        self,
        risk_matrix_df: pd.DataFrame,
        custom_thresholds: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Compute 5 groups of risk signals and composite slow-moving score for all SKUs."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if risk_matrix_df is None or risk_matrix_df.empty:
            raise ValueError("Input M2-04 Risk Feature Matrix DataFrame is empty or None.")

        # 1. Automated Temporal Leakage Inspection (G1)
        self._inspect_feature_leakage(risk_matrix_df)

        # Merge threshold configuration
        thresholds = self.DEFAULT_THRESHOLDS.copy()
        if custom_thresholds:
            thresholds.update(custom_thresholds)

        df = risk_matrix_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'

        v_low_t = thresholds['velocity_low_threshold']
        v_vlow_t = thresholds['velocity_very_low_threshold']
        dsls_stale_t = thresholds['dsls_stale_threshold']
        dsls_high_t = thresholds['dsls_high_recency_threshold']
        zero_high_t = thresholds['zero_rate_high_threshold']
        prob_low_t = thresholds['demand_prob_low_threshold']
        weights = thresholds['weights']

        records = []
        for _, row in df.iterrows():
            orig_sku = str(row.get('sku', row.get(sku_col)))
            canon_sku = str(row.get(sku_col, orig_sku))
            prod_name = str(row.get('product_name', orig_sku))
            t0 = str(row.get('t0', row.get('decision_date', datetime.now().strftime('%Y-%m-%d'))))

            # Raw M2-04 Features
            adi = float(row.get('adi', 1.0))
            cv2 = float(row.get('cv2', 0.0))
            z_rate_90d = float(row.get('zero_rate_90d', row.get('zero_rate_30d', 0.0)))
            pattern = str(row.get('demand_pattern', 'SMOOTH'))

            vel_30d = float(row.get('sales_velocity_30d', 0.0))
            vel_90d = float(row.get('sales_velocity_90d', vel_30d))
            vel_full = float(row.get('sales_velocity_full', vel_90d))
            sales_30d = float(row.get('sales_last_30d', 0.0))
            past_total_sold = float(row.get('past_total_sold', sales_30d))

            dsls = int(row.get('dsls', 0))

            fc_7d = float(row.get('forecast_7d', 0.0))
            fc_14d = float(row.get('forecast_14d', 0.0))
            fc_30d = float(row.get('forecast_30d', 0.0))
            fc_trend = float(row.get('forecast_trend', 1.0))
            demand_prob = float(row.get('demand_probability', 0.5))
            exp_demand_daily = float(row.get('expected_demand_daily', 0.0))

            # Diagnostic Flags
            low_velocity_flag = 1 if vel_30d < v_low_t else 0
            high_zero_rate_flag = 1 if z_rate_90d > zero_high_t else 0
            stale_sales_flag = 1 if dsls > dsls_stale_t else 0
            low_demand_prob_flag = 1 if demand_prob < prob_low_t else 0

            # Signal Labels Extraction
            diagnostic_signals = []
            if dsls > dsls_high_t:
                diagnostic_signals.append("HIGH_RECENCY_RISK")
            elif dsls > dsls_stale_t:
                diagnostic_signals.append("STALE_SALES_ACTIVITY")

            if vel_30d < v_vlow_t:
                diagnostic_signals.append("VERY_LOW_VELOCITY")
            elif vel_30d < v_low_t:
                diagnostic_signals.append("LOW_VELOCITY")

            if z_rate_90d > zero_high_t:
                diagnostic_signals.append("HIGH_ZERO_RATE")

            if demand_prob < prob_low_t:
                diagnostic_signals.append("VERY_LOW_DEMAND_PROBABILITY")

            if fc_trend < 0.90:
                diagnostic_signals.append("DECLINING_FORECAST")

            if fc_30d < 1.0:
                diagnostic_signals.append("LOW_EXPECTED_DEMAND")

            # Deterministic Composite Sub-Scores (0.0 -> 1.0)
            s_recency = min(1.0, dsls / 180.0)
            s_velocity = 1.0 - min(1.0, vel_30d / 0.50)
            s_zero_rate = min(1.0, z_rate_90d)
            s_intermit = min(1.0, max(0.0, (adi - 1.0) / 4.0))
            s_forecast = 1.0 - max(0.0, min(1.0, demand_prob))

            composite_score = round(
                weights['recency'] * s_recency +
                weights['velocity'] * s_velocity +
                weights['zero_rate'] * s_zero_rate +
                weights['intermittency'] * s_intermit +
                weights['forecast'] * s_forecast,
                4
            )

            if composite_score >= 0.70:
                score_level = 'HIGH'
            elif composite_score >= 0.40:
                score_level = 'MEDIUM'
            else:
                score_level = 'LOW'

            rec = {
                'sku': orig_sku,
                'canonical_sku_id': canon_sku,
                'product_name': prod_name,
                'observation_date': t0,
                # Group 1: Demand Intermittency
                'adi': adi,
                'cv2': cv2,
                'zero_rate': z_rate_90d,
                'demand_pattern': pattern,
                'demand_probability': demand_prob,
                # Group 2: Sales Velocity
                'sales_velocity_30d': vel_30d,
                'sales_velocity_90d': vel_90d,
                'sales_velocity_full': vel_full,
                'sales_last_30d': sales_30d,
                'past_total_sold': past_total_sold,
                # Group 3: Sales Recency
                'dsls': dsls,
                # Group 4: Forecast Evidence
                'forecast_7d': fc_7d,
                'forecast_14d': fc_14d,
                'forecast_30d': fc_30d,
                'forecast_trend': fc_trend,
                'expected_demand_daily': exp_demand_daily,
                # Group 5: Diagnostic Flags
                'low_velocity_flag': low_velocity_flag,
                'high_zero_rate_flag': high_zero_rate_flag,
                'stale_sales_flag': stale_sales_flag,
                'low_demand_probability_flag': low_demand_prob_flag,
                'diagnostic_signals': diagnostic_signals,
                # Group 6: Composite Risk Score
                'slow_moving_signal_score': composite_score,
                'slow_moving_score_level': score_level,
            }
            records.append(rec)

        scores_df = pd.DataFrame(records)

        # 2. Save Threshold Configuration
        config_json_path = os.path.join(output_dir, 'risk_scoring_config.json')
        with open(config_json_path, 'w', encoding='utf-8') as f:
            json.dump(thresholds, f, indent=2, ensure_ascii=False)

        # 3. Quality & Distribution Summary
        quality_report = self._inspect_scoring_quality(scores_df)

        dist_series = scores_df['slow_moving_score_level'].value_counts()
        dist_summary = {
            'HIGH': int(dist_series.get('HIGH', 0)),
            'MEDIUM': int(dist_series.get('MEDIUM', 0)),
            'LOW': int(dist_series.get('LOW', 0)),
            'averageScore': round(float(scores_df['slow_moving_signal_score'].mean()), 4),
            'highRiskRatio': round(float((scores_df['slow_moving_signal_score'] >= 0.70).mean()), 4)
        }

        dist_csv_path = os.path.join(output_dir, 'risk_scoring_distribution.csv')
        scores_df.describe().to_csv(dist_csv_path)

        qual_json_path = os.path.join(output_dir, 'risk_scoring_quality.json')
        with open(qual_json_path, 'w', encoding='utf-8') as f:
            json.dump(quality_report, f, indent=2, ensure_ascii=False)

        summary_payload = {
            'sessionId': sess_id,
            'computedAt': datetime.now().isoformat(),
            'totalSkusScored': len(scores_df),
            'leakageCheckStatus': 'PASSED',
            'academicNotice': self.ACADEMIC_DISCLAIMER,
            'distributionSummary': dist_summary,
            'qualityReport': quality_report,
            'thresholdsUsed': thresholds,
        }

        summary_json_path = os.path.join(output_dir, 'risk_scoring_summary.json')
        with open(summary_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # Save Processed Parquet (with CSV fallback)
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_scores.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_scores.csv')

        # Drop list column for parquet compatibility if needed, or serialize to JSON string
        scores_df_parquet = scores_df.copy()
        scores_df_parquet['diagnostic_signals'] = scores_df_parquet['diagnostic_signals'].apply(json.dumps)

        scores_df.to_csv(csv_path, index=False)
        try:
            scores_df_parquet.to_parquet(parquet_path, index=False)
        except Exception:
            parquet_path = csv_path

        return {
            'sessionId': sess_id,
            'totalSkus': len(scores_df),
            'summary': summary_payload,
            'thresholdsConfig': thresholds,
            'riskScoreRecords': records,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'config_json': config_json_path,
                'summary_json': summary_json_path,
                'distribution_csv': dist_csv_path,
                'quality_json': qual_json_path,
            }
        }

    # ── Helper: Automated Feature Leakage Inspector ──────────────────

    def _inspect_feature_leakage(self, df: pd.DataFrame) -> None:
        """Scan DataFrame for forbidden future-derived feature names."""
        cols = {c.lower() for c in df.columns}
        detected = cols.intersection(self.FORBIDDEN_COLUMNS)
        if detected:
            raise FeatureLeakageError(
                f"Automated Feature Leakage Check Failed! Forbidden columns detected: {list(detected)}. "
                f"No future-derived features (fut_qty_60d, DRR, risk_label) allowed in M2-05 feature scoring."
            )

    # ── Helper: Scoring Quality Inspector ────────────────────────────

    def _inspect_scoring_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate feature score dataset against nulls and range bounds."""
        null_count = int(df.isna().sum().sum())
        inf_count = int(np.isinf(df.select_dtypes(include=[np.number])).sum().sum())
        invalid_score = int(((df['slow_moving_signal_score'] < 0.0) | (df['slow_moving_signal_score'] > 1.0)).sum())

        passed = (null_count == 0 and inf_count == 0 and invalid_score == 0)

        return {
            'status': 'PASSED' if passed else 'FAILED',
            'totalSkus': len(df),
            'nullValuesCount': null_count,
            'infiniteValuesCount': inf_count,
            'invalidScoreCount': invalid_score,
            'passedAllQualityRules': passed,
        }
