"""
Task M4-04 — Local Risk Explanation
Module 04: Slow-Moving Risk Explainability (XAI)

Generates structured, UI-ready, non-causal Local Risk Explanations for individual SKUs
based on SHAP values from M4-02 and Feature Contribution Evidence from M4-03.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from src.analytics.explainability_architecture import (
    ExplainabilityOrchestrator,
    ExplainabilityGuardrailError,
    PROJECT_ROOT
)
from src.analytics.shap_explanation_engine import SHAPExplanationEngine
from src.analytics.feature_contribution_analyzer import FeatureContributionAnalyzer

logger = logging.getLogger(__name__)

STANDARD_DISCLAIMER = (
    "Các yếu tố trên thể hiện mức độ đóng góp vào dự báo rủi ro của mô hình tại t0, "
    "không phải quan hệ nhân quả hay kết luận tồn kho vật lý."
)


class LocalRiskExplainerError(Exception):
    """Raised when Local Risk Explanation generation or validation fails."""
    pass


class LocalRiskExplainer:
    """
    Production Local Risk Explainer for Task M4-04.
    
    Generates local (SKU-level) explanations:
    - Top-N local risk contributors (default N=4).
    - Actual feature value + unit + SHAP contribution + contribution direction.
    - Non-causal business bullet points for Merchant UI.
    - Visual bar width percentages for UI card presentation.
    - Standard non-causal disclaimer.
    - Deterministic Python computation (Zero LLM math dependency).
    """

    def __init__(self, model_path: Optional[str] = None, config_path: Optional[str] = None):
        self.orchestrator = ExplainabilityOrchestrator(config_path=config_path) if config_path else ExplainabilityOrchestrator()
        self.shap_engine = SHAPExplanationEngine(model_path=model_path)
        self.contribution_analyzer = FeatureContributionAnalyzer(config_path=config_path)

    def explain_sku(
        self,
        sku: str,
        feature_dict: Dict[str, Any],
        risk_class: str,
        risk_probability: float,
        risk_score: float,
        canonical_sku_id: Optional[str] = None,
        product_name: Optional[str] = None,
        diagnostics: Optional[List[str]] = None,
        top_n: int = 4
    ) -> Dict[str, Any]:
        """
        Generates structured Local Risk Explanation for a single SKU.
        """
        if risk_class not in ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]:
            raise LocalRiskExplainerError(f"Invalid risk_class '{risk_class}'. Must be one of CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK.")

        # 1. Generate M4-02 SHAP payload
        shap_payload = self.shap_engine.explain_sku(
            sku=sku,
            canonical_sku_id=canonical_sku_id,
            product_name=product_name,
            feature_dict=feature_dict,
            risk_class=risk_class,
            risk_probability=risk_probability,
            risk_score=risk_score,
            diagnostics=diagnostics
        )

        # 2. Analyze feature contributions via M4-03
        evidence = self.contribution_analyzer.analyze_sku_contribution(shap_payload, top_n=top_n)

        # 3. Format UI-oriented Local Contributions
        all_top = evidence.get("top_contributions", [])
        max_abs_shap = max([abs(f["shap_value"]) for f in all_top], default=1.0)
        if max_abs_shap == 0:
            max_abs_shap = 1.0

        ui_contributions = []
        bullet_interpretations = []

        for feat in all_top:
            f_name = feat.get("feature_name", "")
            disp_name = feat.get("display_name", f_name)
            val = feat.get("feature_value")
            unit = feat.get("unit", "")
            s_val = float(feat.get("shap_value", 0.0))
            direction_key = "risk_increasing" if s_val > 0 else ("risk_reducing" if s_val < 0 else "neutral")
            
            # Bar width percentage for UI visualization (0-100%)
            bar_pct = min(100, max(10, int((abs(s_val) / max_abs_shap) * 100)))

            ui_contributions.append({
                "rank": feat.get("rank", 1),
                "feature": f_name,
                "display_name": disp_name,
                "value": val,
                "unit": unit,
                "shap_value": round(s_val, 4),
                "absolute_shap": round(abs(s_val), 4),
                "direction": direction_key,
                "bar_width_pct": bar_pct,
                "category": feat.get("category", "OTHER_SIGNALS")
            })

            # Format bullet point for merchant presentation
            bullet = self._generate_bullet_point(disp_name, val, unit, direction_key, f_name)
            self.orchestrator.validate_non_causal_text(bullet)
            bullet_interpretations.append(bullet)

        # 4. Construct Canonical Local Risk Explanation Payload
        local_payload = {
            "sku": sku,
            "canonical_sku_id": canonical_sku_id or f"CSKU_{sku}",
            "product_name": product_name or f"Product {sku}",
            "risk_class": risk_class,
            "risk_probability": round(float(risk_probability), 4),
            "risk_score": round(float(risk_score), 2),
            "explanation_type": "LOCAL",
            "explanation_version": "1.0",
            "top_contributions": ui_contributions,
            "interpretation": bullet_interpretations,
            "diagnostics": diagnostics or [],
            "disclaimer": STANDARD_DISCLAIMER,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        return local_payload

    def _generate_bullet_point(
        self,
        display_name: str,
        value: Any,
        unit: str,
        direction_key: str,
        feature_name: str
    ) -> str:
        """
        Generates readable merchant bullet points adhering strictly to non-causal rules.
        """
        val_str = f"{value}" if value is not None else "N/A"
        unit_str = f" {unit}" if unit else ""

        if direction_key == "risk_increasing":
            if feature_name == "dsls":
                return f"Số ngày từ lần bán gần nhất hiện ở mức {val_str}{unit_str}, đóng góp tăng dự báo rủi ro bán chậm."
            elif feature_name == "adi":
                return f"Khoảng cách giữa các lần bán (ADI = {val_str}{unit_str}) thưa thớt, đóng góp tích cực vào dự báo rủi ro."
            elif feature_name == "zero_rate_90d":
                return f"Tỷ lệ ngày không phát sinh đơn hàng (90 ngày qua) đứng ở mức {val_str}{unit_str}, làm tăng dự báo rủi ro."
            elif feature_name == "cv2":
                return f"Nhu cầu sản lượng biến động (CV² = {val_str}{unit_str}), làm gia tăng mức độ rủi ro khó dự báo."
            elif feature_name == "forecast_7d":
                return f"Dự báo sản lượng 7 ngày tới ở mức thấp ({val_str}{unit_str}), làm tăng trọng số dự báo rủi ro."
            else:
                return f"{display_name} ({val_str}{unit_str}) đang đóng góp theo hướng làm tăng dự báo rủi ro của mô hình tại t0."
        elif direction_key == "risk_reducing":
            return f"{display_name} ({val_str}{unit_str}) đang đóng góp theo hướng làm giảm dự báo rủi ro của mô hình."
        else:
            return f"{display_name} ({val_str}{unit_str}) giữ vai trò trung tính trong dự báo rủi ro."

    def save_local_explanation_artifacts(
        self,
        local_payload: Dict[str, Any],
        batch_payloads: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves Local Risk Explanation artifacts into reports directory.
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports')
        os.makedirs(out_dir, exist_ok=True)

        sample_path = os.path.join(out_dir, 'local_risk_explanation_sample.json')
        summary_path = os.path.join(out_dir, 'local_risk_explanation_summary.json')

        with open(sample_path, 'w', encoding='utf-8') as f:
            json.dump(local_payload, f, indent=2, ensure_ascii=False)

        batch = batch_payloads or [local_payload]
        summary_data = {
            "task": "M4-04",
            "task_name": "Local Risk Explanation",
            "explanation_type": "LOCAL",
            "total_explained_skus": len(batch),
            "sample_sku": local_payload.get("sku"),
            "sample_risk_class": local_payload.get("risk_class"),
            "disclaimer": STANDARD_DISCLAIMER,
            "status": "COMPLETE",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        return {
            "sample_path": sample_path,
            "summary_path": summary_path
        }
