"""
Syntetos-Boylan Demand Pattern Classifier Engine — Module 02 Analytics (M2-02)
================================================================================
Classifies SKU demand behavior into 4 Syntetos-Boylan demand patterns (SMOOTH, ERRATIC,
INTERMITTENT, LUMPY) based on ADI (threshold = 1.32) and CV² (threshold = 0.49).

Academic Boundary & Scope Guardrails:
  1. Demand Pattern != Slow-Moving Risk: LUMPY != CRITICAL_RISK. Patterns represent
     descriptive demand behavior evidence only. Risk scoring is evaluated downstream.
  2. Zero-Demand Handling: Zero-sales days are strictly preserved in ADI/CV² calculation.
  3. Deterministic Non-ML/LLM Rules: 100% Python/Pandas logic.

Outputs standard reports to:
  - data/processed/demand_pattern_features.parquet
  - reports/demand_pattern_summary.json
  - reports/demand_pattern_distribution.csv
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class DemandPatternClassifier:
    """Syntetos-Boylan Demand Pattern Classifier (M2-02)."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def classify_demand_patterns(
        self,
        features_df: pd.DataFrame,
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Classify SKUs into Syntetos-Boylan demand patterns (SMOOTH, ERRATIC, INTERMITTENT, LUMPY)."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if features_df is None or features_df.empty:
            raise ValueError("Input features DataFrame is empty or None.")

        df = features_df.copy()

        # 1. Syntetos-Boylan Classification Matrix (ADI threshold = 1.32, CV² threshold = 0.49)
        patterns = []
        signals_list = []
        descriptions = []

        for _, row in df.iterrows():
            adi = float(row.get('adi', 0.0))
            cv2 = float(row.get('cv2', 0.0))

            pat, sigs, desc = self._classify_single_sku(adi, cv2)
            patterns.append(pat)
            signals_list.append(sigs)
            descriptions.append(desc)

        df['demand_pattern'] = patterns
        df['demand_signals'] = signals_list
        df['pattern_description'] = descriptions
        df['demand_pattern_confidence'] = None  # Academic rule: Do not invent fake probabilities

        # 2. Build Summary & Per-Pattern Distribution Statistics
        pattern_counts = df['demand_pattern'].value_counts().to_dict()
        total_skus = len(df)

        pattern_summary_stats = []
        distribution_rows = []

        for p in ['Smooth', 'Erratic', 'Intermittent', 'Lumpy']:
            p_df = df[df['demand_pattern'].astype(str).str.upper() == p.upper()]
            count = int(len(p_df))
            pct = round((count / float(total_skus) * 100.0), 2) if total_skus > 0 else 0.0

            stat_item = {
                'pattern': p,
                'skuCount': count,
                'percentage': pct,
                'meanAdi': round(float(p_df['adi'].mean()), 4) if count > 0 and 'adi' in p_df else 0.0,
                'medianAdi': round(float(p_df['adi'].median()), 4) if count > 0 and 'adi' in p_df else 0.0,
                'meanCv2': round(float(p_df['cv2'].mean()), 4) if count > 0 and 'cv2' in p_df else 0.0,
                'medianCv2': round(float(p_df['cv2'].median()), 4) if count > 0 and 'cv2' in p_df else 0.0,
                'meanZeroRate': round(float(p_df['zero_rate_90d'].mean() if 'zero_rate_90d' in p_df else p_df.get('zero_rate_30d', pd.Series([0])).mean()), 4) if count > 0 else 0.0,
                'meanSalesVelocity': round(float(p_df['sales_velocity_90d'].mean() if 'sales_velocity_90d' in p_df else p_df.get('sales_velocity_30d', pd.Series([0])).mean()), 4) if count > 0 else 0.0,
            }
            pattern_summary_stats.append(stat_item)

            distribution_rows.append({
                'Pattern': p,
                'SKU_Count': count,
                'Percentage': f"{pct}%",
                'Mean_ADI': stat_item['meanAdi'],
                'Median_ADI': stat_item['medianAdi'],
                'Mean_CV2': stat_item['meanCv2'],
                'Median_CV2': stat_item['medianCv2'],
                'Mean_Zero_Rate': stat_item['meanZeroRate'],
                'Mean_Sales_Velocity': stat_item['meanSalesVelocity'],
            })

        dist_df = pd.DataFrame(distribution_rows)
        dist_csv_path = os.path.join(output_dir, 'demand_pattern_distribution.csv')
        dist_df.to_csv(dist_csv_path, index=False)

        # Academic Boundary Notice (DEM-001 Requirement)
        academic_notice = (
            "Quan trọng: Đây là demand-pattern classification (phân loại hình thái nhu cầu: Smooth, Erratic, Intermittent, Lumpy), "
            "không phải ground truth slow-moving risk."
        )

        summary_payload = {
            'sessionId': sess_id,
            'classifiedAt': datetime.now().isoformat(),
            'totalSkusClassified': total_skus,
            'classificationType': 'DEMAND_PATTERN_CLASSIFICATION',
            'isGroundTruthSlowMovingRisk': False,
            'thresholds': {
                'adiThreshold': 1.32,
                'cv2Threshold': 0.49,
            },
            'patternBreakdown': pattern_counts,
            'patternStatistics': pattern_summary_stats,
            'academicNotice': academic_notice,
        }

        summary_json_path = os.path.join(output_dir, 'demand_pattern_summary.json')
        with open(summary_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # 3. Save Processed Parquet (with CSV fallback)
        parquet_path = os.path.join(data_dir, 'demand_pattern_features.parquet')
        csv_fallback_path = os.path.join(data_dir, 'demand_pattern_features.csv')

        try:
            df.to_parquet(parquet_path, index=False)
        except Exception:
            df.to_csv(csv_fallback_path, index=False)
            parquet_path = csv_fallback_path

        # 4. Prepare Result Payload for API
        records = df.to_dict(orient='records')

        return {
            'sessionId': sess_id,
            'totalSkus': total_skus,
            'summary': summary_payload,
            'demandPatternRecords': records,
            'artifacts': {
                'parquet': parquet_path,
                'pattern_summary': summary_json_path,
                'pattern_distribution_csv': dist_csv_path,
            }
        }

    # ── Helper: Single SKU Syntetos-Boylan Classifier ────────────────

    @staticmethod
    def _classify_single_sku(adi: float, cv2: float) -> Tuple[str, List[str], str]:
        """Classify single SKU based on ADI (1.32) and CV² (0.49)."""
        if adi <= 1.32 and cv2 <= 0.49:
            return (
                'Smooth',
                ['SMOOTH_DEMAND'],
                'Nhu cầu xuất hiện tương đối thường xuyên và ổn định.'
            )
        elif adi <= 1.32 and cv2 > 0.49:
            return (
                'Erratic',
                ['ERRATIC_DEMAND'],
                'Nhu cầu xuất hiện thường xuyên nhưng biến động mạnh về số lượng.'
            )
        elif adi > 1.32 and cv2 <= 0.49:
            return (
                'Intermittent',
                ['INTERMITTENT_DEMAND'],
                'Nhu cầu không xuất hiện liên tục nhưng mức cầu khi phát sinh tương đối ổn định.'
            )
        else:
            return (
                'Lumpy',
                ['LUMPY_DEMAND'],
                'Nhu cầu xuất hiện không thường xuyên và có mức biến động cao.'
            )
