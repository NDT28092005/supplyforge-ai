"""
SupplyForge AI — Django Backend DSS Service Layer
Integrates production DSSPipeline into Django web application.
"""
import os
import sys
import pandas as pd
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.ingestion.validator import validate_input_data

if TYPE_CHECKING:
    from src.pipeline.dss_pipeline import DSSPipeline

class MerchantDSSWebService:
    _pipeline_instance = None

    @classmethod
    def get_pipeline(cls) -> 'DSSPipeline':
        """Lazy load and singleton cache DSSPipeline."""
        if cls._pipeline_instance is None:
            # The pipeline imports optional ML libraries; only load it for a
            # DSS endpoint rather than while Django registers every URL.
            from src.pipeline.dss_pipeline import DSSPipeline

            cls._pipeline_instance = DSSPipeline(PROJECT_ROOT)
        return cls._pipeline_instance

    @classmethod
    def process_merchant_upload(cls, df_gt: pd.DataFrame, df_fc: pd.DataFrame = None, cutoff_date: str = "2025-10-16") -> Tuple[List[Dict], Dict]:
        """Validate input data, run production DSSPipeline, and return payloads + catalog summary."""
        passed, errs = validate_input_data(df_gt)
        if not passed:
            raise ValueError(f"Input validation error: {errs}")

        if df_fc is None:
            # Fallback to forecast_features.parquet if not provided
            fc_path = PROJECT_ROOT / "data" / "processed" / "forecast_features.parquet"
            if fc_path.exists():
                df_fc = pd.read_parquet(fc_path)
            else:
                df_fc = pd.DataFrame({"itemId": df_gt["itemId"]})

        pipeline = cls.get_pipeline()
        payloads, reports = pipeline.run(df_gt, df_fc, cutoff_date=cutoff_date)

        # Aggregate catalog risk overview
        df_res = pd.DataFrame(payloads)
        summary = {
            "total_skus": len(df_res),
            "priority_tier_counts": df_res["priority_tier"].value_counts().to_dict(),
            "tier_display_counts": df_res["tier_display"].value_counts().to_dict(),
            "risk_level_counts": df_res["risk_level"].value_counts().to_dict(),
            "mean_calibrated_prob": round(float(df_res["calibrated_risk_prob"].mean()), 4),
            "critical_skus_count": int((df_res["priority_tier"] == "CRITICAL_ATTENTION").sum()),
            "actionable_skus_count": int((df_res["priority_tier"].isin(["CRITICAL_ATTENTION", "HIGH_ATTENTION"])).sum())
        }

        return payloads, summary

    @classmethod
    def get_sku_decision_card(cls, payloads: List[Dict], sku_id: str) -> Dict:
        """Find decision card for a given SKU ID."""
        for p in payloads:
            if str(p["itemId"]) == str(sku_id):
                return p
        return None
