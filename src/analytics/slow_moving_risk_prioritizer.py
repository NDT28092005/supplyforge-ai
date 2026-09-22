"""
Slow-Moving Risk Ranking & Prioritization Engine — Module 02 Analytics (M2-07)
================================================================================
Converts M2-06 risk classification & probability matrix into a deterministic,
hierarchically sorted Prioritized SKU Risk Queue for merchants.

Ranking Hierarchy:
  1. Primary: Risk Level (CRITICAL > HIGH_RISK > MEDIUM_RISK > LOW_RISK).
  2. Secondary: Model Risk Probability (p_predicted).
  3. Tertiary: Slow-Moving Signal Score.
  4. Tie-Breaking: Recency (DSLS) & Low Sales Velocity.

Operational Priority Segments:
  - P1 — Immediate Attention: CRITICAL
  - P2 — High Attention: HIGH_RISK
  - P3 — Monitor: MEDIUM_RISK
  - P4 — Normal Monitoring: LOW_RISK

Guardrails:
  - 100% Deterministic (No LLM used in calculation or ranking).
  - Uses guarded terminology ("Ưu tiên kiểm tra SKU có tín hiệu bán chậm cao", NOT "Tồn kho thừa").
  - Preserves frozen EXP-02 Ground Truth & M2-06 Risk Classifications.

Outputs artifacts to:
  - data/processed/slow_moving_risk_prioritized_queue.parquet & .csv
  - reports/risk_prioritization_config.json
  - reports/risk_prioritization_summary.json
  - reports/risk_prioritization_distribution.csv
  - reports/risk_prioritization_quality.json
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class FeatureLeakageError(Exception):
    """Raised when forbidden future-derived features are detected at prioritization time."""
    pass


class SlowMovingRiskPrioritizer:
    """Canonical Slow-Moving Risk Ranking & Prioritization Engine (M2-07)."""

    FORBIDDEN_COLUMNS = {
        'fut_qty_60d', 'fut_velocity', 'fut_velocity_60d', 'future_velocity',
        'drr', 'drr_ratio', 'slow_moving_label', 'risk_label', 'future_sales',
        'future_quantity', 'ground_truth_label', 'future_demand', 'label'
    }

    DEFAULT_PRIORITY_WEIGHTS = {
        'CRITICAL': 4.0,
        'HIGH_RISK': 3.0,
        'MEDIUM_RISK': 2.0,
        'LOW_RISK': 1.0,
    }

    SEGMENT_MAPPING = {
        'CRITICAL': 'P1 — Immediate Attention',
        'HIGH_RISK': 'P2 — High Attention',
        'MEDIUM_RISK': 'P3 — Monitor',
        'LOW_RISK': 'P4 — Normal Monitoring',
    }

    ACADEMIC_NOTICE = (
        "Academic Boundary & Operational Notice (G2/G3/M2-07): "
        "Priority Score and Priority Ranks represent merchant attention ordering for products exhibiting slow-moving risk signals. "
        "They do NOT constitute stock-on-hand inventory valuation or business action recommendations."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def prioritize_slow_moving_risk(
        self,
        risk_classifications_m206_df: pd.DataFrame,
        custom_weights: Optional[Dict[str, float]] = None,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Perform hierarchical sorting and compute deterministic Priority Score and Priority Rank."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if risk_classifications_m206_df is None or risk_classifications_m206_df.empty:
            raise ValueError("Input M2-06 Risk Classifications DataFrame is empty or None.")

        # 1. Feature Leakage Inspection
        self._inspect_prioritization_leakage(risk_classifications_m206_df)

        weights = self.DEFAULT_PRIORITY_WEIGHTS.copy()
        if custom_weights:
            weights.update(custom_weights)

        df = risk_classifications_m206_df.copy()
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'

        records = []
        for _, row in df.iterrows():
            orig_sku = str(row.get('sku', row.get(sku_col)))
            canon_sku = str(row.get(sku_col, orig_sku))
            prod_name = str(row.get('product_name', orig_sku))
            t0 = str(row.get('observation_date', row.get('t0', datetime.now().strftime('%Y-%m-%d'))))

            risk_level = str(row.get('risk_level', 'LOW_RISK'))
            risk_prob = float(row.get('risk_probability', 0.5))
            confidence = str(row.get('risk_confidence', 'MEDIUM'))
            sig_score = float(row.get('slow_moving_signal_score', 0.5))
            dsls = int(row.get('dsls', 0))

            w_level = float(weights.get(risk_level, 1.0))
            priority_score = round(w_level + risk_prob + 0.10 * sig_score + 0.05 * min(1.0, dsls / 365.0), 4)

            segment = self.SEGMENT_MAPPING.get(risk_level, 'P4 — Normal Monitoring')

            diag_signals = row.get('diagnostic_signals', [])
            if isinstance(diag_signals, str):
                try:
                    diag_signals = json.loads(diag_signals)
                except Exception:
                    diag_signals = []
            elif not isinstance(diag_signals, (list, tuple)):
                diag_signals = []

            # Priority reasons extraction
            reasons = list(diag_signals)
            if not reasons:
                if dsls > 60:
                    reasons.append("STALE_SALES_ACTIVITY")
                if sig_score > 0.70:
                    reasons.append("HIGH_SLOW_MOVING_SIGNAL")

            rec = {
                'sku': orig_sku,
                'canonical_sku_id': canon_sku,
                'product_name': prod_name,
                'observation_date': t0,
                'risk_level': risk_level,
                'risk_probability': risk_prob,
                'risk_confidence': confidence,
                'slow_moving_signal_score': sig_score,
                'priority_score': priority_score,
                'priority_segment': segment,
                'priority_weight': w_level,
                'dsls': dsls,
                'sales_velocity_30d': float(row.get('sales_velocity_30d', 0.0)),
                'priority_reasons': reasons,
            }
            records.append(rec)

        temp_df = pd.DataFrame(records)

        # 2. Hierarchical Sorting Execution
        temp_df = temp_df.sort_values(
            by=['priority_weight', 'risk_probability', 'slow_moving_signal_score', 'dsls', 'sales_velocity_30d'],
            ascending=[False, False, False, False, True]
        ).reset_index(drop=True)

        temp_df['priority_rank'] = temp_df.index + 1
        sorted_records = temp_df.to_dict(orient='records')

        # 3. Save Config & Quality Summary
        config_json_path = os.path.join(output_dir, 'risk_prioritization_config.json')
        with open(config_json_path, 'w', encoding='utf-8') as f:
            json.dump({'risk_priority_weights': weights, 'segment_mapping': self.SEGMENT_MAPPING}, f, indent=2, ensure_ascii=False)

        quality_report = self._inspect_prioritization_quality(temp_df)

        seg_counts = temp_df['priority_segment'].value_counts()
        dist_summary = {
            'P1_Immediate': int(seg_counts.get('P1 — Immediate Attention', 0)),
            'P2_High': int(seg_counts.get('P2 — High Attention', 0)),
            'P3_Monitor': int(seg_counts.get('P3 — Monitor', 0)),
            'P4_Normal': int(seg_counts.get('P4 — Normal Monitoring', 0)),
            'topPrioritySku': sorted_records[0]['canonical_sku_id'] if sorted_records else None,
            'topPriorityScore': sorted_records[0]['priority_score'] if sorted_records else 0.0,
        }

        dist_csv_path = os.path.join(output_dir, 'risk_prioritization_distribution.csv')
        temp_df.describe().to_csv(dist_csv_path)

        qual_json_path = os.path.join(output_dir, 'risk_prioritization_quality.json')
        with open(qual_json_path, 'w', encoding='utf-8') as f:
            json.dump(quality_report, f, indent=2, ensure_ascii=False)

        summary_payload = {
            'sessionId': sess_id,
            'prioritizedAt': datetime.now().isoformat(),
            'totalSkusPrioritized': len(temp_df),
            'leakageCheckStatus': 'PASSED',
            'academicNotice': self.ACADEMIC_NOTICE,
            'distributionSummary': dist_summary,
            'qualityReport': quality_report,
            'priorityWeights': weights,
        }

        summary_json_path = os.path.join(output_dir, 'risk_prioritization_summary.json')
        with open(summary_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # Save Processed Parquet (with CSV fallback)
        parquet_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.csv')

        temp_df_parquet = temp_df.copy()
        temp_df_parquet['priority_reasons'] = temp_df_parquet['priority_reasons'].apply(json.dumps)

        temp_df.to_csv(csv_path, index=False)
        try:
            temp_df_parquet.to_parquet(parquet_path, index=False)
        except Exception:
            parquet_path = csv_path

        return {
            'sessionId': sess_id,
            'totalSkus': len(temp_df),
            'summary': summary_payload,
            'priorityConfig': weights,
            'prioritizedQueueRecords': sorted_records,
            'artifacts': {
                'parquet': parquet_path,
                'csv': csv_path,
                'config_json': config_json_path,
                'summary_json': summary_json_path,
                'distribution_csv': dist_csv_path,
                'quality_json': qual_json_path,
            }
        }

    # ── Helper: Leakage Inspector ─────────────────────────────────────

    def _inspect_prioritization_leakage(self, df: pd.DataFrame) -> None:
        """Scan DataFrame for forbidden future-derived feature names."""
        cols = {c.lower() for c in df.columns}
        detected = cols.intersection(self.FORBIDDEN_COLUMNS)
        if detected:
            raise FeatureLeakageError(
                f"Prioritization Feature Leakage Intercepted! Forbidden columns detected: {list(detected)}. "
                f"No future-derived features (fut_qty_60d, DRR, risk_label) allowed at prioritization step."
            )

    # ── Helper: Quality Inspector ────────────────────────────────────

    def _inspect_prioritization_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Validate prioritized dataset ranking integrity."""
        null_count = int(df.isna().sum().sum())
        rank_unique = bool(df['priority_rank'].nunique() == len(df))
        rank_monotonic = bool((df['priority_rank'].diff().iloc[1:] == 1).all()) if len(df) > 1 else True

        passed = bool(null_count == 0 and rank_unique and rank_monotonic)

        return {
            'status': 'PASSED' if passed else 'FAILED',
            'totalSkus': len(df),
            'nullValuesCount': null_count,
            'rankUnique': rank_unique,
            'rankMonotonic': rank_monotonic,
            'passedAllQualityRules': passed,
        }
