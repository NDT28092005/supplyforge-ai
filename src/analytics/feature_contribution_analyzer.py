"""
Task M4-03 — Feature Contribution Analysis
Module 04: Slow-Moving Risk Explainability (XAI)

Converts raw SHAP values from M4-02 into structured, category-grouped,
pattern-aware, and merchant-interpretable Feature Contribution Evidence.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.analytics.explainability_architecture import (
    ExplainabilityOrchestrator,
    ExplainabilityGuardrailError,
    PROJECT_ROOT
)

logger = logging.getLogger(__name__)


class FeatureContributionAnalyzerError(Exception):
    """Raised when contribution analysis or consistency validation fails."""
    pass


class FeatureContributionAnalyzer:
    """
    Production Feature Contribution Analyzer for Task M4-03.
    
    Transforms raw SHAP values into structured evidence:
    - Feature Ranking by |SHAP| magnitude.
    - Direction Analysis (INCREASES_RISK vs DECREASES_RISK).
    - Business Taxonomy Categorization (DEMAND_FORECAST, SALES_VELOCITY, DEMAND_INTERMITTENCY, RECENCY_SIGNAL).
    - Dominant Category Identification & Evidence Pattern Detection.
    - Non-Causal Merchant Interpretation generation.
    - Global Contribution Statistics across SKU datasets.
    """

    FEATURE_TAXONOMY = {
        'forecast_7d': 'DEMAND_FORECAST',
        'forecast_14d': 'DEMAND_FORECAST',
        'forecast_30d': 'DEMAND_FORECAST',
        'forecast_trend': 'DEMAND_FORECAST',
        'expected_demand_daily': 'DEMAND_FORECAST',
        'demand_probability': 'DEMAND_FORECAST',
        'sales_velocity_30d': 'SALES_VELOCITY',
        'sales_velocity_90d': 'SALES_VELOCITY',
        'sales_velocity_full': 'SALES_VELOCITY',
        'sales_last_30d': 'SALES_VELOCITY',
        'past_total_sold': 'SALES_VELOCITY',
        'past_total_sales': 'SALES_VELOCITY',
        'adi': 'DEMAND_INTERMITTENCY',
        'cv2': 'DEMAND_INTERMITTENCY',
        'zero_rate_90d': 'DEMAND_INTERMITTENCY',
        'zero_rate_full': 'DEMAND_INTERMITTENCY',
        'dsls': 'RECENCY_SIGNAL'
    }

    CATEGORY_DISPLAY_NAMES = {
        'DEMAND_FORECAST': 'Dự Báo Nhu Cầu Nguồn Cầu Ngắn Hạn',
        'SALES_VELOCITY': 'Tốc Độ Tiêu Thụ Hàng Hóa',
        'DEMAND_INTERMITTENCY': 'Tính Gián Đoạn & Biến Động Nhu Cầu',
        'RECENCY_SIGNAL': 'Tín Hiệu Thời Gian Giao Dịch Gần Nhất'
    }

    def __init__(self, config_path: Optional[str] = None):
        self.orchestrator = ExplainabilityOrchestrator(config_path=config_path) if config_path else ExplainabilityOrchestrator()

    def categorize_feature(self, feature_name: str) -> str:
        """Categorizes feature into business taxonomy."""
        return self.FEATURE_TAXONOMY.get(feature_name, 'OTHER_SIGNALS')

    def analyze_sku_contribution(
        self,
        shap_payload: Dict[str, Any],
        top_n: Optional[int] = 4
    ) -> Dict[str, Any]:
        """
        Analyzes raw SHAP payload for a single SKU to produce structured Feature Contribution Evidence.
        """
        # Validate schema structure and prediction consistency
        self.orchestrator.validate_payload_structure(shap_payload)

        sku = shap_payload.get("sku", "")
        risk_class = shap_payload.get("risk_class", "")
        risk_prob = shap_payload.get("risk_probability", 0.0)
        risk_score = shap_payload.get("risk_score", 0.0)

        explanation = shap_payload.get("explanation", {})
        features_list = explanation.get("features", [])

        if not features_list:
            raise FeatureContributionAnalyzerError(f"No feature contributions found in payload for SKU {sku}")

        # Validate temporal safety for all features
        feature_names = [f.get("feature_name", "") for f in features_list]
        self.orchestrator.validate_temporal_safety(feature_names)

        # Process & rank contributions by absolute SHAP value
        analyzed_features = []
        category_abs_sum: Dict[str, float] = {
            'DEMAND_FORECAST': 0.0,
            'SALES_VELOCITY': 0.0,
            'DEMAND_INTERMITTENCY': 0.0,
            'RECENCY_SIGNAL': 0.0,
            'OTHER_SIGNALS': 0.0
        }

        risk_increasing_count = 0
        risk_decreasing_count = 0

        for f_item in features_list:
            f_name = f_item.get("feature_name", "")
            f_val = f_item.get("feature_value")
            s_val = float(f_item.get("shap_value", 0.0))
            abs_shap = abs(s_val)
            direction = "INCREASES_RISK" if s_val > 0 else ("DECREASES_RISK" if s_val < 0 else "NEUTRAL")

            if direction == "INCREASES_RISK":
                risk_increasing_count += 1
            elif direction == "DECREASES_RISK":
                risk_decreasing_count += 1

            cat = self.categorize_feature(f_name)
            category_abs_sum[cat] = category_abs_sum.get(cat, 0.0) + abs_shap

            reg_info = self.orchestrator.registry.get("features", {}).get(f_name, {})
            display_name = f_item.get("display_name") or reg_info.get("display_name", f_name)
            unit = f_item.get("unit") or reg_info.get("unit", "")
            
            # Non-causal business interpretation
            interp = self._build_non_causal_interpretation(f_name, display_name, f_val, unit, direction)
            self.orchestrator.validate_non_causal_text(interp)

            analyzed_features.append({
                "feature_name": f_name,
                "display_name": display_name,
                "feature_value": f_val,
                "shap_value": round(s_val, 4),
                "absolute_shap": round(abs_shap, 4),
                "direction": direction,
                "category": cat,
                "unit": unit,
                "interpretation": interp
            })

        # Sort descending by absolute SHAP value
        analyzed_features.sort(key=lambda x: x["absolute_shap"], reverse=True)
        for rank, feat in enumerate(analyzed_features, start=1):
            feat["rank"] = rank

        # Identify dominant category
        dominant_category = max(category_abs_sum.items(), key=lambda x: x[1])[0]

        # Detect contribution pattern
        detected_patterns = self._detect_contribution_patterns(analyzed_features)

        # Slice Top-N if specified
        top_contributions = analyzed_features[:top_n] if (top_n and top_n > 0) else analyzed_features

        summary_evidence = {
            "sku": sku,
            "canonical_sku_id": shap_payload.get("canonical_sku_id", f"CSKU_{sku}"),
            "product_name": shap_payload.get("product_name", f"Product {sku}"),
            "risk_class": risk_class,
            "risk_probability": risk_prob,
            "risk_score": risk_score,
            "contribution_summary": {
                "dominant_category": dominant_category,
                "dominant_category_display": self.CATEGORY_DISPLAY_NAMES.get(dominant_category, dominant_category),
                "risk_increasing_features_count": risk_increasing_count,
                "risk_decreasing_features_count": risk_decreasing_count,
                "detected_evidence_patterns": detected_patterns,
                "total_features_analyzed": len(analyzed_features)
            },
            "top_contributions": top_contributions,
            "all_contributions": analyzed_features,
            "explanation_version": "1.0",
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }

        return summary_evidence

    def _build_non_causal_interpretation(
        self,
        feature_name: str,
        display_name: str,
        feature_value: Any,
        unit: str,
        direction: str
    ) -> str:
        """
        Builds strict non-causal merchant interpretation text.
        Format: "<Display Name> ở mức <Value> <Unit> đang đóng góp theo hướng <tăng/giảm> dự báo rủi ro."
        """
        val_str = f"{feature_value}" if feature_value is not None else "N/A"
        unit_str = f" {unit}" if unit else ""

        if direction == "INCREASES_RISK":
            dir_str = "làm tăng xác suất dự báo rủi ro bán chậm của mô hình"
        elif direction == "DECREASES_RISK":
            dir_str = "làm giảm xác suất dự báo rủi ro bán chậm của mô hình"
        else:
            dir_str = "duy trì mức độ trung tính trong dự báo của mô hình"

        return f"{display_name} hiện ở mức {val_str}{unit_str} đang đóng góp theo hướng {dir_str} tại t0."

    def _detect_contribution_patterns(self, features: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Detects non-causal evidence patterns based on top feature contribution combinations.
        """
        feat_map = {f["feature_name"]: f for f in features[:6]}
        patterns = []

        # Pattern A — Extremely Low Sales Velocity
        if "zero_rate_90d" in feat_map and "sales_velocity_90d" in feat_map:
            zr = feat_map["zero_rate_90d"]
            sv = feat_map["sales_velocity_90d"]
            if zr["direction"] == "INCREASES_RISK" and sv["direction"] == "INCREASES_RISK":
                patterns.append({
                    "pattern_id": "EXTREMELY_LOW_DEMAND",
                    "label": "Mẫu Bằng Chứng Tốc Độ Bán Rất Thấp",
                    "description": "Tỷ lệ ngày đứng hàng cao kết hợp tốc độ bán thấp đồng thời gia tăng dự báo rủi ro."
                })

        # Pattern B — Intermittent / Lumpy Demand
        if "adi" in feat_map and "cv2" in feat_map:
            adi = feat_map["adi"]
            cv2 = feat_map["cv2"]
            if adi["direction"] == "INCREASES_RISK" or cv2["direction"] == "INCREASES_RISK":
                patterns.append({
                    "pattern_id": "INTERMITTENT_DEMAND",
                    "label": "Mẫu Bằng Chứng Nhu Cầu Thất Thường / Gián Đoạn",
                    "description": "Khoảng cách chu kỳ bán thưa thớt (ADI) hoặc sản lượng biến động (CV²) tăng mức độ rủi ro."
                })

        # Pattern C — Weak Short-term Forecast Signals
        if "forecast_7d" in feat_map or "demand_probability" in feat_map:
            f7 = feat_map.get("forecast_7d", {})
            dp = feat_map.get("demand_probability", {})
            if f7.get("direction") == "INCREASES_RISK" or dp.get("direction") == "INCREASES_RISK":
                patterns.append({
                    "pattern_id": "WEAK_FORECAST_SIGNALS",
                    "label": "Mẫu Bằng Chứng Dự Báo Cầu Suy Yếu",
                    "description": "Dự báo sản lượng hoặc xác suất phát sinh nhu cầu ngắn hạn thấp đóng góp tăng rủi ro."
                })

        # Pattern D — Recency Stagnation
        if "dsls" in feat_map and feat_map["dsls"].get("direction") == "INCREASES_RISK":
            patterns.append({
                "pattern_id": "RECENCY_STAGNATION",
                "label": "Mẫu Bằng Chứng Trệ Hàng Kéo Dài",
                "description": "Thời gian trôi qua từ lần phát sinh đơn gần nhất (DSLS) đứng cao tăng dự báo rủi ro."
            })

        return patterns

    def analyze_global_dataset_contributions(
        self,
        batch_payloads: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Computes Global Contribution Statistics across a dataset of SKU SHAP payloads.
        Useful for model-level auditing and research validation against Module 03.
        """
        if not batch_payloads:
            return {"total_skus": 0, "global_feature_statistics": []}

        total_skus = len(batch_payloads)
        feat_stats: Dict[str, Dict[str, Any]] = {}

        for p in batch_payloads:
            features = p.get("explanation", {}).get("features", [])
            for f in features:
                fname = f.get("feature_name", "")
                shap_val = float(f.get("shap_value", 0.0))
                abs_val = float(f.get("absolute_shap", abs(shap_val)))
                rank = int(f.get("rank", 99))
                direction = f.get("direction", "NEUTRAL")

                if fname not in feat_stats:
                    feat_stats[fname] = {
                        "feature_name": fname,
                        "display_name": f.get("display_name", fname),
                        "category": self.categorize_feature(fname),
                        "abs_shap_list": [],
                        "shap_list": [],
                        "ranks": [],
                        "positive_count": 0,
                        "negative_count": 0
                    }

                feat_stats[fname]["abs_shap_list"].append(abs_val)
                feat_stats[fname]["shap_list"].append(shap_val)
                feat_stats[fname]["ranks"].append(rank)
                if direction == "INCREASES_RISK":
                    feat_stats[fname]["positive_count"] += 1
                elif direction == "DECREASES_RISK":
                    feat_stats[fname]["negative_count"] += 1

        summary_list = []
        for fname, stat in feat_stats.items():
            abs_arr = np.array(stat["abs_shap_list"])
            ranks_arr = np.array(stat["ranks"])
            mean_abs = float(np.mean(abs_arr))
            median_abs = float(np.median(abs_arr))
            avg_rank = float(np.mean(ranks_arr))
            pos_rate = float(stat["positive_count"] / total_skus)

            summary_list.append({
                "feature_name": fname,
                "display_name": stat["display_name"],
                "category": stat["category"],
                "mean_abs_shap": round(mean_abs, 4),
                "median_abs_shap": round(median_abs, 4),
                "avg_rank": round(avg_rank, 2),
                "risk_increasing_rate": round(pos_rate, 4),
                "risk_decreasing_rate": round(float(stat["negative_count"] / total_skus), 4)
            })

        summary_list.sort(key=lambda x: x["mean_abs_shap"], reverse=True)

        return {
            "total_skus_analyzed": total_skus,
            "global_feature_statistics": summary_list,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    def save_analysis_artifacts(
        self,
        summary_evidence: Dict[str, Any],
        global_stats: Optional[Dict[str, Any]] = None,
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves Feature Contribution Analysis artifacts into reports directory.
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports')
        os.makedirs(out_dir, exist_ok=True)

        sample_path = os.path.join(out_dir, 'feature_contribution_sample.json')
        summary_path = os.path.join(out_dir, 'feature_contribution_summary.json')

        with open(sample_path, 'w', encoding='utf-8') as f:
            json.dump(summary_evidence, f, indent=2, ensure_ascii=False)

        summary_data = {
            "task": "M4-03",
            "task_name": "Feature Contribution Analysis",
            "dominant_category": summary_evidence.get("contribution_summary", {}).get("dominant_category"),
            "top_4_features": [f["feature_name"] for f in summary_evidence.get("top_contributions", [])[:4]],
            "global_statistics": global_stats or {},
            "status": "COMPLETE",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        return {
            "sample_path": sample_path,
            "summary_path": summary_path
        }
