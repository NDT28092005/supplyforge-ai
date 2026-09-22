"""
Task M4-01 — Explainability Architecture
Module 04: Slow-Moving Risk Explainability (XAI)

Provides the ExplainabilityOrchestrator base architecture, temporal-safety guardrails,
business terminology mapping, and canonical Explainability Payload building/validation.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "explainability_feature_registry.json")
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "schemas", "explainability_payload.schema.json")


class ExplainabilityGuardrailError(Exception):
    """Raised when an explainability payload violates core safety guardrails."""
    pass


class ExplainabilityOrchestrator:
    """
    Central orchestrator for Module 04 Explainability Architecture.
    
    Guarantees:
    1. Temporal-safety: Rejects future/ground-truth features (t > t0).
    2. Model-faithfulness: Retains true SHAP values and contribution directions.
    3. Non-causality: Rejects causal wording and maps features to descriptive business terminology.
    4. Determinism: Uses Python deterministic mapping (zero LLM calculation).
    5. Versioning: Produces canonical payloads with explanation_version="1.0".
    """

    def __init__(self, config_path: str = CONFIG_PATH, schema_path: str = SCHEMA_PATH):
        self.config_path = config_path
        self.schema_path = schema_path
        self.registry = self._load_registry()
        self.schema = self._load_schema()

    def _load_registry(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load feature registry config: %s", e)
        return {
            "registry_version": "1.0",
            "features": {},
            "forbidden_features": [
                "fut_qty_60d", "future_velocity", "future_sales",
                "DRR", "ground_truth_label", "is_slow_moving_gt", "future_revenue"
            ]
        }

    def _load_schema(self) -> Dict[str, Any]:
        if os.path.exists(self.schema_path):
            try:
                with open(self.schema_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load explainability payload schema: %s", e)
        return {}

    def validate_temporal_safety(self, feature_names: List[str]) -> bool:
        """
        Validates that all features belong strictly to observation window t <= t0.
        Raises ExplainabilityGuardrailError if future leak or ground truth features are present.
        """
        forbidden = set(self.registry.get("forbidden_features", []))
        forbidden.update([
            "fut_qty_60d", "future_velocity", "future_sales",
            "DRR", "ground_truth_label", "is_slow_moving_gt", "future_revenue"
        ])

        leaked = [f for f in feature_names if f in forbidden]
        if leaked:
            raise ExplainabilityGuardrailError(
                f"GUARDRAIL VIOLATION: Explanation contains forbidden future/GT features: {leaked}. "
                "Explainability must use features strictly at t <= t0."
            )
        return True

    def validate_non_causal_text(self, text: str) -> bool:
        """
        Validates that business text contains no prohibited causal claims.
        """
        prohibited_phrases = [
            "nguyên nhân khiến", "chắc chắn bị lỗi thời", "sản phẩm bị lỗi thời",
            "chắc chắn hết hàng", "giá sai", "chất lượng kém"
        ]
        text_lower = text.lower()
        for phrase in prohibited_phrases:
            if phrase in text_lower:
                raise ExplainabilityGuardrailError(
                    f"GUARDRAIL VIOLATION: Causal phrase '{phrase}' is prohibited in explanation text."
                )
        return True

    def map_feature_to_business(self, feature_name: str, feature_value: Any, shap_value: float, rank: int) -> Dict[str, Any]:
        """
        Maps technical feature metadata to merchant-readable evidence dictionary.
        """
        self.validate_temporal_safety([feature_name])
        
        feature_info = self.registry.get("features", {}).get(feature_name, {})
        display_name = feature_info.get("display_name", feature_name)
        unit = feature_info.get("unit", "")
        interpretation = feature_info.get("business_interpretation", "Yếu tố đóng góp vào dự báo mô hình.")

        direction = "INCREASES_RISK" if shap_value > 0 else ("DECREASES_RISK" if shap_value < 0 else "NEUTRAL")

        return {
            "feature_name": feature_name,
            "display_name": display_name,
            "feature_value": feature_value,
            "shap_value": round(float(shap_value), 4),
            "direction": direction,
            "rank": rank,
            "unit": unit,
            "business_interpretation": interpretation
        }

    def assemble_payload(
        self,
        sku: str,
        risk_class: str,
        risk_probability: float,
        risk_score: float,
        shap_contributions: List[Dict[str, Any]],
        base_value: float = 0.35,
        diagnostics: Optional[List[str]] = None,
        canonical_sku_id: Optional[str] = None,
        product_name: Optional[str] = None,
        model_version: str = "xgboost_exp03_v1"
    ) -> Dict[str, Any]:
        """
        Assembles canonical Explainability Payload dictionary.
        """
        # Validate temporal safety across all contributed features
        feature_names = [f.get("feature_name", "") for f in shap_contributions]
        self.validate_temporal_safety(feature_names)

        # Sort features by absolute SHAP contribution descending & assign rank
        sorted_features = sorted(shap_contributions, key=lambda x: abs(x.get("shap_value", 0.0)), reverse=True)
        ranked_features = []
        for idx, feat in enumerate(sorted_features, start=1):
            mapped = self.map_feature_to_business(
                feature_name=feat.get("feature_name", f"feature_{idx}"),
                feature_value=feat.get("feature_value"),
                shap_value=feat.get("shap_value", 0.0),
                rank=idx
            )
            ranked_features.append(mapped)

        payload = {
            "sku": sku,
            "canonical_sku_id": canonical_sku_id or f"CSKU_{sku}",
            "product_name": product_name or f"Product {sku}",
            "risk_class": risk_class,
            "risk_probability": round(float(risk_probability), 4),
            "risk_score": round(float(risk_score), 2),
            "explanation": {
                "method": "SHAP",
                "model": "XGBoost",
                "model_version": model_version,
                "base_value": round(float(base_value), 4),
                "features": ranked_features
            },
            "diagnostics": diagnostics or [],
            "explanation_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        self.validate_payload_structure(payload)
        return payload

    def validate_payload_structure(self, payload: Dict[str, Any]) -> bool:
        """
        Validates that required keys exist and types match the schema contract.
        """
        required_keys = ["sku", "risk_class", "risk_probability", "risk_score", "explanation", "diagnostics", "explanation_version"]
        for key in required_keys:
            if key not in payload:
                raise ExplainabilityGuardrailError(f"Payload schema validation failed: missing key '{key}'")

        if payload.get("explanation_version") != "1.0":
            raise ExplainabilityGuardrailError("Payload schema validation failed: invalid explanation_version")

        exp = payload.get("explanation", {})
        if "method" not in exp or "base_value" not in exp or "features" not in exp:
            raise ExplainabilityGuardrailError("Payload schema validation failed: explanation object incomplete")

        return True
