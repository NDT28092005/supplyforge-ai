"""
Slow-Moving Risk Feature Assembly Engine — Module 02 Analytics (M2-03)
========================================================================
Merges demand features from M2-01, demand-pattern signals from M2-02, and
business activity signals as of decision cutoff t0 into a canonical, leakage-safe
Slow-Moving Risk Feature Matrix.

Academic Boundary & Leakage Protection:
  1. Feature observed at t0 -> Predict future Slow-Moving Risk (Data <= t0 ONLY).
  2. Automated Leakage Inspector: Strictly raises FeatureLeakageError if forbidden
     columns (fut_qty_60d, DRR, risk_label, ground_truth_label) are detected.
  3. Feature Construction Layer Only: Does NOT generate risk labels (CRITICAL/HIGH_RISK).
     Label generation belongs exclusively to downstream M2-04/M2-05 models.

Outputs artifacts to:
  - data/processed/slow_moving_risk_features.parquet
  - reports/risk_feature_registry.json
  - reports/risk_feature_quality.json
  - reports/risk_feature_summary.csv
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


class RiskFeatureAssembler:
    """Canonical Risk Feature Assembly Engine for Slow-Moving Product Risk (M2-03)."""

    FORBIDDEN_COLUMNS = {
        'fut_qty_60d', 'fut_velocity_60d', 'drr', 'drr_ratio',
        'slow_moving_label', 'risk_label', 'future_sales', 'future_quantity',
        'ground_truth_label', 'future_demand', 'label'
    }

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def assemble_risk_features(
        self,
        features_m201_df: pd.DataFrame,
        patterns_m202_df: pd.DataFrame,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Assemble M2-01 and M2-02 outputs into a unified, leakage-protected Risk Feature Matrix."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if features_m201_df is None or features_m201_df.empty:
            raise ValueError("M2-01 features DataFrame is empty or None.")

        # 1. Automated Feature Leakage Inspection (FAIL-SAFE)
        self._inspect_feature_leakage(features_m201_df)
        if patterns_m202_df is not None and not patterns_m202_df.empty:
            self._inspect_feature_leakage(patterns_m202_df)

        df1 = features_m201_df.copy()
        df2 = patterns_m202_df.copy() if patterns_m202_df is not None and not patterns_m202_df.empty else pd.DataFrame()

        # 2. Merge M2-01 and M2-02 on SKU ID
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df1.columns else 'sku'

        if not df2.empty and sku_col in df2.columns:
            # Drop overlapping columns except key
            overlap_cols = [c for c in df2.columns if c in df1.columns and c != sku_col]
            df2_clean = df2.drop(columns=overlap_cols)
            merged_df = pd.merge(df1, df2_clean, on=sku_col, how='left')
        else:
            merged_df = df1

        # 3. Construct 5 Core Feature Categories
        assembled_records = []

        for _, row in merged_df.iterrows():
            orig_sku = str(row.get('sku', row.get(sku_col)))
            canon_sku = str(row.get(sku_col, orig_sku))
            prod_name = str(row.get('product_name', orig_sku))
            t0 = str(row.get('decision_date', datetime.now().strftime('%Y-%m-%d')))

            # Category 1: Sales Velocity Features
            vel_30d = float(row.get('sales_velocity_30d', 0.0))
            vel_90d = float(row.get('sales_velocity_90d', 0.0))
            vel_full = float(row.get('sales_velocity_full', 0.0))
            sales_30d = float(row.get('sales_last_30d', 0.0))
            sales_90d = float(row.get('sales_last_90d', 0.0))
            past_total_sold = float(row.get('sales_last_90d', sales_90d))

            # Category 2: Sales Recency Feature
            dsls = int(row.get('dsls', 0))

            # Category 3: Zero-Sales Rate Features
            z_rate_30d = float(row.get('zero_rate_30d', 0.0))
            z_rate_90d = float(row.get('zero_rate_90d', 0.0))
            z_rate_full = float(row.get('zero_rate_full', 0.0))

            # Category 4: Demand Pattern & One-Hot Encoded Signals
            adi = float(row.get('adi', 1.0))
            cv2 = float(row.get('cv2', 0.0))
            pattern = str(row.get('demand_pattern', row.get('demand_pattern_candidate', 'SMOOTH')))

            is_smooth = 1 if pattern == 'SMOOTH' else 0
            is_erratic = 1 if pattern == 'ERRATIC' else 0
            is_intermittent = 1 if pattern == 'INTERMITTENT' else 0
            is_lumpy = 1 if pattern == 'LUMPY' else 0

            signals = [f"{pattern}_DEMAND"]

            # Category 5: Forecast & Business Activity Signals
            fc_7d = float(row.get('forecast_7d', 0.0))
            fc_14d = float(row.get('forecast_14d', 0.0))
            fc_30d = float(row.get('forecast_30d', 0.0))
            fc_trend = float(row.get('forecast_trend', 1.0))
            demand_prob = float(row.get('demand_probability', 0.5))
            exp_demand_daily = float(row.get('expected_demand_daily', 0.0))

            sales_last_7d = float(row.get('sales_last_7d', 0.0))
            active_7d = 1 if sales_last_7d > 0 else 0
            active_30d = 1 if sales_30d > 0 else 0
            recent_sales_ratio = round(sales_30d / max(1.0, sales_90d), 4)

            record = {
                'sku': orig_sku,
                'canonical_sku_id': canon_sku,
                'product_name': prod_name,
                't0': t0,
                # Cat 1: Velocity
                'sales_velocity_30d': vel_30d,
                'sales_velocity_90d': vel_90d,
                'sales_velocity_full': vel_full,
                'sales_last_30d': sales_30d,
                'sales_last_90d': sales_90d,
                'past_total_sold': past_total_sold,
                # Cat 2: Recency
                'dsls': dsls,
                # Cat 3: Zero Rate
                'zero_rate_30d': z_rate_30d,
                'zero_rate_90d': z_rate_90d,
                'zero_rate_full': z_rate_full,
                # Cat 4: Demand Pattern & One-Hot
                'adi': adi,
                'cv2': cv2,
                'demand_pattern': pattern,
                'is_smooth': is_smooth,
                'is_erratic': is_erratic,
                'is_intermittent': is_intermittent,
                'is_lumpy': is_lumpy,
                'demand_signals': signals,
                # Cat 5: Forecast & Activity
                'forecast_7d': fc_7d,
                'forecast_14d': fc_14d,
                'forecast_30d': fc_30d,
                'forecast_trend': fc_trend,
                'demand_probability': demand_prob,
                'expected_demand_daily': exp_demand_daily,
                'active_7d': active_7d,
                'active_30d': active_30d,
                'recent_sales_ratio': recent_sales_ratio,
            }
            assembled_records.append(record)

        risk_features_df = pd.DataFrame(assembled_records)

        # 4. Feature Quality & Outlier Check
        quality_report = self._inspect_feature_quality(risk_features_df)

        # 5. Generate Official Feature Registry
        registry_schema = self._build_feature_registry_schema()
        registry_json_path = os.path.join(output_dir, 'risk_feature_registry.json')
        with open(registry_json_path, 'w', encoding='utf-8') as f:
            json.dump(registry_schema, f, indent=2, ensure_ascii=False)

        qual_json_path = os.path.join(output_dir, 'risk_feature_quality.json')
        with open(qual_json_path, 'w', encoding='utf-8') as f:
            json.dump(quality_report, f, indent=2, ensure_ascii=False)

        csv_summary_path = os.path.join(output_dir, 'risk_feature_summary.csv')
        risk_features_df.describe().to_csv(csv_summary_path)

        # 6. Save Processed Parquet (with CSV fallback)
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_features.parquet')
        csv_fallback_path = os.path.join(data_dir, 'slow_moving_risk_features.csv')

        try:
            risk_features_df.to_parquet(parquet_path, index=False)
        except Exception:
            risk_features_df.to_csv(csv_fallback_path, index=False)
            parquet_path = csv_fallback_path

        summary_payload = {
            'sessionId': sess_id,
            'assembledAt': datetime.now().isoformat(),
            'totalSkusAssembled': len(risk_features_df),
            'totalFeaturesAssembled': len(risk_features_df.columns),
            'leakageCheckStatus': 'PASSED',
            'forbiddenFeaturesDetected': 0,
            'qualityReport': quality_report,
            'featureCategoriesCount': 5,
        }

        return {
            'sessionId': sess_id,
            'totalSkus': len(risk_features_df),
            'summary': summary_payload,
            'featureRegistry': registry_schema,
            'riskFeatureRecords': assembled_records,
            'artifacts': {
                'parquet': parquet_path,
                'registry_json': registry_json_path,
                'quality_json': qual_json_path,
                'summary_csv': csv_summary_path,
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
                f"No future-derived features (fut_qty_60d, DRR, risk_label) allowed in M2-03 feature matrix."
            )

    # ── Helper: Feature Quality Inspector ─────────────────────────────

    def _inspect_feature_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate feature matrix against missingness and outlier bounds."""
        null_count = int(df.isna().sum().sum())
        inf_count = int(np.isinf(df.select_dtypes(include=[np.number])).sum().sum())
        neg_vel_count = int((df['sales_velocity_30d'] < 0).sum())
        invalid_adi = int((df['adi'] < 1.0).sum())
        invalid_cv2 = int((df['cv2'] < 0.0).sum())
        invalid_dsls = int((df['dsls'] < 0).sum())

        passed = (null_count == 0 and inf_count == 0 and neg_vel_count == 0 and
                  invalid_adi == 0 and invalid_cv2 == 0 and invalid_dsls == 0)

        return {
            'status': 'PASSED' if passed else 'FAILED',
            'totalSkus': len(df),
            'totalFeatures': len(df.columns),
            'nullValuesCount': null_count,
            'infiniteValuesCount': inf_count,
            'negativeVelocityCount': neg_vel_count,
            'invalidAdiCount': invalid_adi,
            'invalidCv2Count': invalid_cv2,
            'invalidDslsCount': invalid_dsls,
            'passedAllQualityRules': passed,
        }

    # ── Helper: Build Feature Registry Schema ─────────────────────────

    def _build_feature_registry_schema(self) -> List[Dict[str, Any]]:
        """Return official JSON registry schema describing assembled risk features."""
        return [
            {
                "feature_name": "sales_velocity_30d",
                "category": "Sales Velocity",
                "definition": "Average units sold per day over previous 30-day window",
                "source_window": "t0-29d -> t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "sales_velocity_90d",
                "category": "Sales Velocity",
                "definition": "Average units sold per day over previous 90-day window",
                "source_window": "t0-89d -> t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "dsls",
                "category": "Sales Recency",
                "definition": "Days Since Last Sale (t0 - date_last_sale)",
                "source_window": "t0 - date_last_sale",
                "future_data_allowed": False,
                "data_type": "int"
            },
            {
                "feature_name": "zero_rate_90d",
                "category": "Zero-Sales Rate",
                "definition": "Ratio of days with zero sales in previous 90-day window",
                "source_window": "t0-89d -> t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "adi",
                "category": "Demand Pattern",
                "definition": "Average Demand Interval (Syntetos-Boylan intermittency metric)",
                "source_window": "t0-89d -> t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "cv2",
                "category": "Demand Pattern",
                "definition": "Squared Coefficient of Variation for non-zero demand size",
                "source_window": "t0-89d -> t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "is_lumpy",
                "category": "Demand Pattern One-Hot",
                "definition": "Binary indicator for Lumpy demand pattern (ADI > 1.32 & CV2 > 0.49)",
                "source_window": "t0-89d -> t0",
                "future_data_allowed": False,
                "data_type": "int"
            },
            {
                "feature_name": "demand_probability",
                "category": "Forecast Evidence",
                "definition": "Daily demand occurrence probability solved via TSB solver",
                "source_window": "Historical transaction series <= t0",
                "future_data_allowed": False,
                "data_type": "float"
            },
            {
                "feature_name": "recent_sales_ratio",
                "category": "Business Activity",
                "definition": "Ratio of recent 30-day sales to 90-day sales momentum",
                "source_window": "t0-29d / t0-89d",
                "future_data_allowed": False,
                "data_type": "float"
            }
        ]
