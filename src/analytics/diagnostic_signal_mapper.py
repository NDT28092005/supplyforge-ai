"""
Task M4-06 — Diagnostic Signal Mapping
Module 04: Slow-Moving Risk Explainability (XAI)

Evaluates feature vectors and SHAP contributions against 5 standardized business diagnostic rules
for Slow-Moving Product Risk Detection without changing model predictions or making causal claims.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from src.analytics.explainability_architecture import (
    ExplainabilityOrchestrator,
    ExplainabilityGuardrailError,
    PROJECT_ROOT
)

logger = logging.getLogger(__name__)

TERMINOLOGY_DISCLAIMER = (
    "Tín hiệu chẩn đoán mang tính chất hỗ trợ diễn giải bằng chứng dữ liệu tại t0, "
    "không phải kết luận nguyên nhân nhân quả hay khẳng định tình trạng kho vật lý thực tế."
)


class DiagnosticSignalMapperError(Exception):
    """Raised when Diagnostic Signal evaluation or validation fails."""
    pass


class DiagnosticSignalMapper:
    """
    Production Diagnostic Signal Mapper for Task M4-06.
    
    Evaluates 5 standardized Business Diagnostic Signals in Scope:
    1. LOW_SALES_VELOCITY (sales_velocity_90d < 0.10)
    2. LUMPY_DEMAND (ADI > 1.32 AND CV² > 0.49)
    3. POSSIBLE_OBSOLESCENCE (DSLS > 180 OR risk_class == CRITICAL)
    4. PROMO_ASSOCIATED_LOW_VELOCITY (promotion_rate > 0.20 AND sales_velocity_90d < 0.50)
    5. POSSIBLE_STOCKOUT_EFFECT (zero_rate_90d > 0.70 AND active_30d == True)
    
    Guarantees:
    - 100% Deterministic Python Rule Engine (Zero LLM math calculation).
    - Traceable evidence pairing for every activated signal.
    - Strict terminology guardrails (blocks OBSOLETE, STOCKOUT_CONFIRMED, CAUSE_OF_RISK).
    - Preserves Module 03 risk predictions completely intact.
    """

    SIGNAL_DEFINITIONS = {
        "LOW_SALES_VELOCITY": {
            "name": "Tốc Độ Bán Hàng Rất Thấp",
            "description": "Phản ánh tình trạng tốc độ tiêu thụ sản phẩm ở mức quá thấp trong khoảng thời gian quan sát qua.",
            "category": "SALES_BEHAVIOR",
            "default_priority": "HIGH"
        },
        "LUMPY_DEMAND": {
            "name": "Nhu Cầu Ngắt Quãng & Biến Động Kéo Dài",
            "description": "Phản ánh dạng cầu ngắt quãng (Intermittent/Lumpy) theo tiêu chí Syntetos-Boylan (ADI > 1.32 & CV² > 0.49).",
            "category": "DEMAND_PATTERN",
            "default_priority": "HIGH"
        },
        "POSSIBLE_OBSOLESCENCE": {
            "name": "Khả Năng Đứng Trệ / Bán Chậm Kéo Dài",
            "description": "Tín hiệu cho thấy sản phẩm có khoảng thời gian trôi qua từ đơn hàng cuối (DSLS > 180 ngày) hoặc nằm trong nhóm rủi ro cao.",
            "category": "RECENCY_SIGNAL",
            "default_priority": "HIGH"
        },
        "PROMO_ASSOCIATED_LOW_VELOCITY": {
            "name": "Khuyến Mãi Cao Nhưng Sức Bán Vẫn Thấp",
            "description": "Sản phẩm có mức độ tham gia khuyến mãi (> 20%) nhưng tốc độ bán vẫn duy trì ở mức thấp (< 0.50 đơn vị/ngày).",
            "category": "PROMOTION_SIGNAL",
            "default_priority": "MEDIUM"
        },
        "POSSIBLE_STOCKOUT_EFFECT": {
            "name": "Mẫu Tín Hiệu Có Thể Liên Quan Đến Gián Đoạn Cung Ứng",
            "description": "Tỷ lệ ngày đứng hàng cao (> 70%) trong khi sản phẩm vẫn đang hoạt động; cần Merchant kiểm tra kho thực tế.",
            "category": "AVAILABILITY_SIGNAL",
            "default_priority": "MEDIUM"
        }
    }

    def __init__(self, config_path: Optional[str] = None):
        self.orchestrator = ExplainabilityOrchestrator(config_path=config_path) if config_path else ExplainabilityOrchestrator()

    def evaluate_sku_signals(
        self,
        sku: str,
        feature_dict: Dict[str, Any],
        risk_class: Optional[str] = None,
        risk_probability: Optional[float] = None,
        risk_score: Optional[float] = None,
        promotion_rate: Optional[float] = None,
        active_30d: bool = True,
        canonical_sku_id: Optional[str] = None,
        product_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates 5 deterministic diagnostic rules for a single SKU.
        """
        # Validate temporal safety across feature dict
        self.orchestrator.validate_temporal_safety(list(feature_dict.keys()))

        # Extract required features with safe fallbacks
        sv_90d = float(feature_dict.get("sales_velocity_90d", feature_dict.get("sales_velocity_30d", 0.0)))
        adi = float(feature_dict.get("adi", 0.0))
        cv2 = float(feature_dict.get("cv2", 0.0))
        dsls = float(feature_dict.get("dsls", 0.0))
        zr_90d = float(feature_dict.get("zero_rate_90d", feature_dict.get("zero_rate_full", 0.0)))
        p_rate = float(promotion_rate if promotion_rate is not None else feature_dict.get("promotion_rate", 0.0))

        r_class = risk_class or "MEDIUM_RISK"
        r_prob = float(risk_probability if risk_probability is not None else 0.50)
        r_score = float(risk_score if risk_score is not None else 50.0)

        signals_evaluated = []

        # -------------------------------------------------------------
        # Rule 1: LOW_SALES_VELOCITY (sales_velocity_90d < 0.10)
        # -------------------------------------------------------------
        is_low_vel = sv_90d < 0.10
        signals_evaluated.append({
            "code": "LOW_SALES_VELOCITY",
            "active": is_low_vel,
            "priority": "HIGH" if is_low_vel else "LOW",
            "evidence_strength": "HIGH" if sv_90d < 0.05 else ("MEDIUM" if is_low_vel else "NONE"),
            "evidence": [
                {
                    "feature": "sales_velocity_90d",
                    "display_name": "Tốc độ bán 90 ngày",
                    "value": round(sv_90d, 4),
                    "threshold": "< 0.10 đơn vị/ngày"
                }
            ]
        })

        # -------------------------------------------------------------
        # Rule 2: LUMPY_DEMAND (ADI > 1.32 AND CV² > 0.49)
        # -------------------------------------------------------------
        is_lumpy = (adi > 1.32) and (cv2 > 0.49)
        signals_evaluated.append({
            "code": "LUMPY_DEMAND",
            "active": is_lumpy,
            "priority": "HIGH" if is_lumpy else "LOW",
            "evidence_strength": "HIGH" if (adi > 2.0 and cv2 > 0.70) else ("MEDIUM" if is_lumpy else "NONE"),
            "evidence": [
                {
                    "feature": "adi",
                    "display_name": "Khoảng cách giữa các lần bán (ADI)",
                    "value": round(adi, 2),
                    "threshold": "> 1.32 ngày/chu kỳ"
                },
                {
                    "feature": "cv2",
                    "display_name": "Mức độ biến động nhu cầu (CV²)",
                    "value": round(cv2, 2),
                    "threshold": "> 0.49"
                }
            ]
        })

        # -------------------------------------------------------------
        # Rule 3: POSSIBLE_OBSOLESCENCE (DSLS > 180 OR risk_class == CRITICAL)
        # -------------------------------------------------------------
        is_obsolete_signal = (dsls > 180) or (r_class == "CRITICAL")
        obs_evidence = []
        if dsls > 180:
            obs_evidence.append({
                "feature": "dsls",
                "display_name": "Số ngày từ lần bán gần nhất",
                "value": round(dsls, 1),
                "threshold": "> 180 ngày"
            })
        if r_class == "CRITICAL":
            obs_evidence.append({
                "feature": "risk_class",
                "display_name": "Phân loại rủi ro mô hình",
                "value": r_class,
                "threshold": "== CRITICAL"
            })

        signals_evaluated.append({
            "code": "POSSIBLE_OBSOLESCENCE",
            "active": is_obsolete_signal,
            "priority": "HIGH" if (dsls > 180 and r_class == "CRITICAL") else ("MEDIUM" if is_obsolete_signal else "LOW"),
            "evidence_strength": "HIGH" if (dsls > 180 and r_class == "CRITICAL") else ("MEDIUM" if is_obsolete_signal else "NONE"),
            "evidence": obs_evidence
        })

        # -------------------------------------------------------------
        # Rule 4: PROMO_ASSOCIATED_LOW_VELOCITY (promotion_rate > 0.20 AND sales_velocity_90d < 0.50)
        # -------------------------------------------------------------
        is_promo_low = (p_rate > 0.20) and (sv_90d < 0.50)
        signals_evaluated.append({
            "code": "PROMO_ASSOCIATED_LOW_VELOCITY",
            "active": is_promo_low,
            "priority": "MEDIUM" if is_promo_low else "LOW",
            "evidence_strength": "MEDIUM" if is_promo_low else "NONE",
            "evidence": [
                {
                    "feature": "promotion_rate",
                    "display_name": "Tỷ lệ tham gia khuyến mãi",
                    "value": round(p_rate, 2),
                    "threshold": "> 0.20 (20%)"
                },
                {
                    "feature": "sales_velocity_90d",
                    "display_name": "Tốc độ bán 90 ngày",
                    "value": round(sv_90d, 4),
                    "threshold": "< 0.50 đơn vị/ngày"
                }
            ]
        })

        # -------------------------------------------------------------
        # Rule 5: POSSIBLE_STOCKOUT_EFFECT (zero_rate_90d > 0.70 AND active_30d == True)
        # -------------------------------------------------------------
        is_stockout_effect = (zr_90d > 0.70) and (active_30d is True)
        signals_evaluated.append({
            "code": "POSSIBLE_STOCKOUT_EFFECT",
            "active": is_stockout_effect,
            "priority": "MEDIUM" if is_stockout_effect else "LOW",
            "evidence_strength": "MEDIUM" if is_stockout_effect else "NONE",
            "evidence": [
                {
                    "feature": "zero_rate_90d",
                    "display_name": "Tỷ lệ ngày không phát sinh bán",
                    "value": round(zr_90d, 2),
                    "threshold": "> 0.70 (70%)"
                },
                {
                    "feature": "active_30d",
                    "display_name": "Trạng thái hoạt động 30 ngày qua",
                    "value": active_30d,
                    "threshold": "== TRUE"
                }
            ]
        })

        # Filter active signals & rank by priority
        active_signals = [s for s in signals_evaluated if s["active"]]
        active_signals.sort(key=lambda x: (0 if x["priority"] == "HIGH" else (1 if x["priority"] == "MEDIUM" else 2)))

        # Build non-causal merchant interpretation text
        summary_bullets = self._build_business_summary(active_signals, sku)

        payload = {
            "sku": sku,
            "canonical_sku_id": canonical_sku_id or f"CSKU_{sku}",
            "product_name": product_name or f"Product {sku}",
            "risk_class": r_class,
            "risk_probability": round(r_prob, 4),
            "risk_score": round(r_score, 2),
            "explanation_version": "1.0",
            "active_signals_count": len(active_signals),
            "diagnostic_signals": signals_evaluated,
            "active_diagnostic_signals": active_signals,
            "business_interpretation": summary_bullets,
            "disclaimer": TERMINOLOGY_DISCLAIMER,
            "evaluated_at": datetime.now(timezone.utc).isoformat()
        }

        # Guardrail check against forbidden causal phrases
        for b in summary_bullets:
            self.orchestrator.validate_non_causal_text(b)

        return payload

    def _build_business_summary(self, active_signals: List[Dict[str, Any]], sku: str) -> List[str]:
        """
        Generates readable merchant bullet points describing active diagnostic signals.
        """
        if not active_signals:
            return ["Dữ liệu quan sát tại t0 không kích hoạt tín hiệu rủi ro chẩn đoán đặc thù nào."]

        bullets = []
        codes = [s["code"] for s in active_signals]

        if "LOW_SALES_VELOCITY" in codes and "LUMPY_DEMAND" in codes:
            bullets.append(
                "SKU ghi nhận đồng thời tốc độ bán hàng rất thấp và dạng nhu cầu gián đoạn/biến động cao (Lumpy Demand)."
            )
        elif "LOW_SALES_VELOCITY" in codes:
            bullets.append("SKU ghi nhận tốc độ bán hàng ở mức rất thấp trong khoảng thời gian 90 ngày qua.")

        if "POSSIBLE_OBSOLESCENCE" in codes:
            bullets.append(
                "Có tín hiệu phù hợp với khả năng sản phẩm đang đứng trệ kéo dài hoặc thuộc nhóm có mức độ rủi ro cao."
            )

        if "POSSIBLE_STOCKOUT_EFFECT" in codes:
            bullets.append(
                "Hệ thống ghi nhận tín hiệu có thể liên quan đến gián đoạn cung ứng/stockout; Merchant cần xác minh thực tế tồn kho."
            )

        if "PROMO_ASSOCIATED_LOW_VELOCITY" in codes:
            bullets.append(
                "Sản phẩm có mức độ tham gia khuyến mãi khá cao nhưng sức tiêu thụ thực tế vẫn duy trì ở mức thấp."
            )

        return bullets

    def save_diagnostic_artifacts(
        self,
        diagnostic_payload: Dict[str, Any],
        batch_payloads: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves Diagnostic Signal Mapping artifacts into reports directory.
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports')
        os.makedirs(out_dir, exist_ok=True)

        sample_path = os.path.join(out_dir, 'diagnostic_signal_mapping_sample.json')
        summary_path = os.path.join(out_dir, 'diagnostic_signal_mapping_summary.json')

        with open(sample_path, 'w', encoding='utf-8') as f:
            json.dump(diagnostic_payload, f, indent=2, ensure_ascii=False)

        batch = batch_payloads or [diagnostic_payload]
        summary_data = {
            "task": "M4-06",
            "task_name": "Diagnostic Signal Mapping",
            "total_evaluated_skus": len(batch),
            "sample_sku": diagnostic_payload.get("sku"),
            "active_signals_in_sample": diagnostic_payload.get("active_signals_count", 0),
            "disclaimer": TERMINOLOGY_DISCLAIMER,
            "status": "COMPLETE",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        return {
            "sample_path": sample_path,
            "summary_path": summary_path
        }
