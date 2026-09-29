"""
Demand Service — DEM-001 (Demand Pattern Classification) & DEM-002 (Velocity)
==============================================================================
Services for classifying SKU demand patterns according to Syntetos-Boylan (1995/2005)
matrix (Smooth, Erratic, Intermittent, Lumpy) and calculating sales velocity across 7d, 30d, 90d windows.

Academic Guardrail (DEM-001):
  - Demand Pattern Classification is descriptive demand behavior evidence based on ADI, CV², and zero-rate.
  - IT IS NOT ground truth slow-moving risk (which depends on physical stock, DSLS, and downstream risk models).

Velocity Metrics (DEM-002):
  - sales_velocity_7d  = sum(units sold in last 7d) / 7.0
  - sales_velocity_30d = sum(units sold in last 30d) / 30.0
  - sales_velocity_90d = sum(units sold in last 90d) / 90.0
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer

logger = logging.getLogger(__name__)


class DemandService:
    """Service layer for DEM-001 Demand Pattern Classification and DEM-002 Velocity calculations."""

    @staticmethod
    def calculate_velocity(
        df: pd.DataFrame,
        decision_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        DEM-002: Calculate sales_velocity_7d, sales_velocity_30d, and sales_velocity_90d for each SKU.

        :param df: DataFrame containing columns ['date'/'trans_date', 'sku'/'canonical_sku_id', 'quantity'/'qty']
        :param decision_date: Optional cutoff date t0 (defaults to max date in df)
        :return: List of SKU velocity dicts with fields:
                 ['sku', 'canonical_sku_id', 'product_name', 'sales_velocity_7d', 'sales_velocity_30d', 'sales_velocity_90d']
        """
        if df is None or df.empty:
            return []

        engineer = SlowMovingFeatureEngineer(session_id="demand_service")
        result = engineer.compute_sku_features(df=df, decision_date=decision_date)
        feature_matrix = result.get("featureMatrix", [])

        velocity_records = []
        for row in feature_matrix:
            velocity_records.append({
                "sku": row.get("sku"),
                "canonical_sku_id": row.get("canonical_sku_id"),
                "product_name": row.get("product_name"),
                "decision_date": row.get("decision_date"),
                "sales_velocity_7d": float(row.get("sales_velocity_7d", 0.0)),
                "sales_velocity_30d": float(row.get("sales_velocity_30d", 0.0)),
                "sales_velocity_90d": float(row.get("sales_velocity_90d", 0.0)),
            })

        return velocity_records

    @staticmethod
    def classify_demand_patterns(
        df: pd.DataFrame,
        decision_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        DEM-001: Classify SKUs into Syntetos-Boylan demand patterns: Smooth, Erratic, Intermittent, Lumpy.

        Evaluated using:
          - ADI (Average Demand Interval): threshold = 1.32
          - CV² (Coefficient of Variation squared): threshold = 0.49
          - zero_rate (ratio of zero-demand days in 30d/90d)

        :param df: Input DataFrame of transactions or precomputed feature matrix
        :param decision_date: Optional cutoff date t0
        :return: Result dictionary containing summary, pattern records, and academic notice.
        """
        if df is None or df.empty:
            return {
                "totalSkus": 0,
                "summary": {},
                "records": [],
                "academicNotice": "Quan trọng: đây là demand-pattern classification, không phải ground truth slow-moving risk."
            }

        # If df is raw transactions, first run SlowMovingFeatureEngineer to get ADI, CV2, zero_rate
        if "adi" not in df.columns or "cv2" not in df.columns:
            engineer = SlowMovingFeatureEngineer(session_id="demand_service")
            feature_res = engineer.compute_sku_features(df=df, decision_date=decision_date)
            features_df = pd.DataFrame(feature_res.get("featureMatrix", []))
        else:
            features_df = df.copy()

        classifier = DemandPatternClassifier(session_id="demand_service")
        classification_res = classifier.classify_demand_patterns(features_df=features_df)

        # Explicitly attach DEM-001 academic metadata to each record
        records = classification_res.get("demandPatternRecords", [])
        for rec in records:
            rec["classification_type"] = "DEMAND_PATTERN_CLASSIFICATION"
            rec["is_ground_truth_slow_moving_risk"] = False

        return {
            "totalSkus": len(records),
            "summary": classification_res.get("summary", {}),
            "records": records,
            "academicNotice": "Quan trọng: đây là demand-pattern classification, không phải ground truth slow-moving risk."
        }
