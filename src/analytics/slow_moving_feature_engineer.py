"""
Slow-Moving Risk Feature Engineering Engine — Module 02 Analytics (M2-01)
==========================================================================
Deterministic feature engineering layer that converts canonical transaction data
into SKU-level demand features as of decision cutoff t0.

Strict Leakage & Scope Guardrails:
  1. No Future Data: Only transactions with date <= t0 are evaluated.
  2. No Ground Truth Leakage: Never uses fut_qty_60d, DRR, or slow_moving_label.
  3. Deterministic Calculation: 100% Python/NumPy/Pandas. Zero LLM computation.
  4. Scope Boundary: Evaluates Slow-Moving Product Risk (Demand side), NOT Physical Stock.

Exports artifacts to:
  - data/processed/slow_moving_features.parquet
  - reports/feature_engineering_summary.json
  - reports/feature_quality_report.json
  - reports/feature_statistics.csv
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.data_readiness_gate import DataReadinessGate, DataReadinessError, enforce_readiness_gate


class SlowMovingFeatureEngineer:
    """Deterministic Feature Engineering Engine for Slow-Moving Product Risk (M2-01)."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    @enforce_readiness_gate
    def compute_sku_features(
        self,
        df: pd.DataFrame,
        decision_date: Optional[str] = None,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Calculate leakage-safe, reproducible SKU demand features as of decision cutoff t0."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if df is None or df.empty:
            raise ValueError("Input DataFrame is empty or None.")

        # 1. Prepare Date & Filter Cutoff t0
        df = df.copy()
        date_col = 'date' if 'date' in df.columns else ('trans_date' if 'trans_date' in df.columns else 'order_date')
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else ('sku' if 'sku' in df.columns else 'sku_code')
        qty_col = 'quantity' if 'quantity' in df.columns else ('qty' if 'qty' in df.columns else 'amount')

        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col])

        if decision_date:
            t0 = pd.to_datetime(decision_date)
        else:
            t0 = df[date_col].max()

        # Rule 01: Leakage Guard — Only use transactions <= t0
        df_history = df[df[date_col] <= t0].copy()
        if df_history.empty:
            raise ValueError(f"No transaction records found on or before decision cutoff date t0={t0.strftime('%Y-%m-%d')}.")

        # 2. Compute Features per SKU
        sku_features_list = []
        unique_skus = df_history[sku_col].unique()

        for sku in unique_skus:
            sku_df = df_history[df_history[sku_col] == sku].sort_values(date_col)
            prod_name = str(sku_df['product_name'].iloc[0]) if 'product_name' in sku_df.columns else str(sku)
            orig_sku = str(sku_df['sku'].iloc[0]) if 'sku' in sku_df.columns else str(sku)

            # Dates
            min_date = sku_df[date_col].min()
            max_date = sku_df[date_col].max()
            obs_days = max(1, (t0 - min_date).days + 1)

            # Filter non-zero demand days
            nonzero_df = sku_df[sku_df[qty_col] > 0]
            last_sale_date = nonzero_df[date_col].max() if not nonzero_df.empty else None

            # 5.1 Sales Velocity (Exact N-day inclusive windows ending at t0)
            sum_7d = sku_df[sku_df[date_col] >= (t0 - timedelta(days=6))][qty_col].sum()
            sum_30d = sku_df[sku_df[date_col] >= (t0 - timedelta(days=29))][qty_col].sum()
            sum_60d = sku_df[sku_df[date_col] >= (t0 - timedelta(days=59))][qty_col].sum()
            sum_90d = sku_df[sku_df[date_col] >= (t0 - timedelta(days=89))][qty_col].sum()
            sum_full = sku_df[qty_col].sum()

            vel_7d = round(float(sum_7d) / 7.0, 4)
            vel_30d = round(float(sum_30d) / 30.0, 4)
            vel_90d = round(float(sum_90d) / 90.0, 4)
            vel_full = round(float(sum_full) / float(obs_days), 4)

            # 5.2 Zero-Sales Rate
            n_zero_30d = 30 - len(sku_df[(sku_df[date_col] >= (t0 - timedelta(days=30))) & (sku_df[qty_col] > 0)][date_col].unique())
            n_zero_90d = 90 - len(sku_df[(sku_df[date_col] >= (t0 - timedelta(days=90))) & (sku_df[qty_col] > 0)][date_col].unique())
            n_zero_full = obs_days - len(nonzero_df[date_col].unique())

            zero_rate_30d = round(max(0.0, min(1.0, float(n_zero_30d) / 30.0)), 4)
            zero_rate_90d = round(max(0.0, min(1.0, float(n_zero_90d) / 90.0)), 4)
            zero_rate_full = round(max(0.0, min(1.0, float(n_zero_full) / float(obs_days))), 4)

            # 5.3 DSLS (Days Since Last Sale)
            if last_sale_date is not None:
                dsls = max(0, (t0 - last_sale_date).days)
            else:
                dsls = obs_days

            # 5.4 Syntetos-Boylan Intermittency (ADI & CV²)
            n_period = min(obs_days, 90)
            nonzero_90d = sku_df[(sku_df[date_col] >= (t0 - timedelta(days=90))) & (sku_df[qty_col] > 0)]
            n_nonzero_90d = len(nonzero_90d[date_col].unique())

            adi = round(float(n_period) / float(max(1, n_nonzero_90d)), 4)

            nonzero_vals = nonzero_90d[qty_col].values
            if len(nonzero_vals) >= 2 and np.mean(nonzero_vals) > 0:
                cv2 = round(float((np.std(nonzero_vals, ddof=1) / np.mean(nonzero_vals)) ** 2), 4)
            else:
                cv2 = 0.0

            # Demand Pattern Signal Candidate
            if adi <= 1.32 and cv2 <= 0.49:
                demand_pattern = 'Smooth'
            elif adi <= 1.32 and cv2 > 0.49:
                demand_pattern = 'Erratic'
            elif adi > 1.32 and cv2 <= 0.49:
                demand_pattern = 'Intermittent'
            else:
                demand_pattern = 'Lumpy'

            # 5.5 Teunter-Syntetos-Babai (TSB) Solver Forecast Signals
            p_t, z_t = self._solve_tsb_forecast(sku_df, qty_col, date_col, t0)
            expected_demand_daily = round(p_t * z_t, 4)
            forecast_7d = round(expected_demand_daily * 7.0, 2)
            forecast_14d = round(expected_demand_daily * 14.0, 2)
            forecast_30d = round(expected_demand_daily * 30.0, 2)
            forecast_trend = round(expected_demand_daily / max(0.0001, vel_90d), 4)

            # Feature Row Payload
            sku_features_list.append({
                'sku': orig_sku,
                'canonical_sku_id': str(sku),
                'product_name': prod_name,
                'decision_date': t0.strftime('%Y-%m-%d'),
                'observation_period_days': obs_days,
                'sales_velocity_7d': vel_7d,
                'sales_velocity_30d': vel_30d,
                'sales_velocity_90d': vel_90d,
                'sales_velocity_full': vel_full,
                'sales_last_7d': float(sum_7d),
                'sales_last_30d': float(sum_30d),
                'sales_last_60d': float(sum_60d),
                'sales_last_90d': float(sum_90d),
                'zero_rate_30d': zero_rate_30d,
                'zero_rate_90d': zero_rate_90d,
                'zero_rate_full': zero_rate_full,
                'dsls': int(dsls),
                'adi': float(adi),
                'cv2': float(cv2),
                'demand_pattern_candidate': demand_pattern,
                'forecast_7d': float(forecast_7d),
                'forecast_14d': float(forecast_14d),
                'forecast_30d': float(forecast_30d),
                'forecast_trend': float(forecast_trend),
                'demand_probability': round(float(p_t), 4),
                'expected_demand_daily': float(expected_demand_daily),
                'no_observed_sales_history': bool(sum_full == 0),
            })

        feature_df = pd.DataFrame(sku_features_list)

        # 3. Perform Feature Quality Validation
        quality_report = self._validate_feature_quality(feature_df)

        # 4. Save Parquet (with CSV fallback) & Reports
        parquet_path = os.path.join(data_dir, 'slow_moving_features.parquet')
        csv_fallback_path = os.path.join(data_dir, 'slow_moving_features.csv')

        try:
            feature_df.to_parquet(parquet_path, index=False)
        except Exception:
            feature_df.to_csv(csv_fallback_path, index=False)
            parquet_path = csv_fallback_path

        csv_stat_path = os.path.join(output_dir, 'feature_statistics.csv')
        feature_df.describe().to_csv(csv_stat_path)

        summary_path = os.path.join(output_dir, 'feature_engineering_summary.json')
        summary_payload = {
            'sessionId': sess_id,
            'decisionDate': t0.strftime('%Y-%m-%d'),
            'totalSkusProcessed': len(feature_df),
            'totalFeaturesComputed': len(feature_df.columns),
            'demandPatternBreakdown': feature_df['demand_pattern_candidate'].value_counts().to_dict(),
            'generatedAt': datetime.now().isoformat(),
        }
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        qual_path = os.path.join(output_dir, 'feature_quality_report.json')
        with open(qual_path, 'w', encoding='utf-8') as f:
            json.dump(quality_report, f, indent=2, ensure_ascii=False)

        return {
            'sessionId': sess_id,
            'decisionDate': t0.strftime('%Y-%m-%d'),
            'totalSkus': len(feature_df),
            'featureMatrix': feature_df.to_dict(orient='records'),
            'summary': summary_payload,
            'qualityReport': quality_report,
            'artifacts': {
                'parquet': parquet_path,
                'feature_summary': summary_path,
                'feature_quality': qual_path,
                'feature_stats_csv': csv_stat_path,
            }
        }

    # ── TSB Solver Helper ─────────────────────────────────────────────

    def _solve_tsb_forecast(
        self, sku_df: pd.DataFrame, qty_col: str, date_col: str, t0: pd.Timestamp
    ) -> Tuple[float, float]:
        """Teunter-Syntetos-Babai (TSB) solver for intermittent demand probability & size."""
        alpha = 0.15
        beta = 0.15

        p_t = 0.5  # Demand probability
        z_t = 1.0  # Demand size

        if sku_df.empty:
            return 0.1, 1.0

        daily_series = sku_df.groupby(date_col)[qty_col].sum()
        for qty in daily_series:
            x_t = 1.0 if qty > 0 else 0.0
            p_t = p_t + alpha * (x_t - p_t)
            if qty > 0:
                z_t = z_t + beta * (float(qty) - z_t)

        return max(0.01, min(1.0, p_t)), max(0.1, z_t)

    # ── Feature Quality Validator ─────────────────────────────────────

    def _validate_feature_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate feature matrix against integrity rules."""
        null_count = int(df.isna().sum().sum())
        inf_count = int(np.isinf(df.select_dtypes(include=[np.number])).sum().sum())
        neg_vel_count = int((df['sales_velocity_30d'] < 0).sum())
        invalid_adi_count = int((df['adi'] <= 0).sum())
        invalid_cv2_count = int((df['cv2'] < 0).sum())
        invalid_dsls_count = int((df['dsls'] < 0).sum())

        passed = (null_count == 0 and inf_count == 0 and neg_vel_count == 0 and
                  invalid_adi_count == 0 and invalid_cv2_count == 0 and invalid_dsls_count == 0)

        return {
            'status': 'PASSED' if passed else 'FAILED',
            'totalSkus': len(df),
            'featureCount': len(df.columns),
            'nullValuesCount': null_count,
            'infiniteValuesCount': inf_count,
            'negativeVelocityCount': neg_vel_count,
            'invalidAdiCount': invalid_adi_count,
            'invalidCv2Count': invalid_cv2_count,
            'invalidDslsCount': invalid_dsls_count,
            'passedAllQualityRules': passed,
        }
