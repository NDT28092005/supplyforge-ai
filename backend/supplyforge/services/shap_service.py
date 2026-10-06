"""
SupplyForge AI — SHAP Explanation Service (Independent Fallback Architecture)

Tier 3: Explanation Engine
    Primary: shap.TreeExplainer (real TreeSHAP values)
    Fallback: Linear Proxy (heuristic coefficients)

Key principles:
  - Explanation fallback is INDEPENDENT of prediction fallback
  - XGBoost prediction + Linear Proxy explanation is a VALID state
  - SHAP additivity is verified: base_value + Σ SHAP_i ≈ model_output
  - decision_confidence is computed from multiple governance signals
  - Fallback NEVER pretends to be ML — engine provenance is transparent
"""

import math
import logging

import numpy as np
import requests
from django.conf import settings
from supplyforge.models import Product
from supplyforge.services.gemini_copilot import GeminiCopilotService
from supplyforge.services.model_loader import (
    ModelLoaderService, MLServiceError, FailureType,
)

logger = logging.getLogger(__name__)


# ============================================================
# Business Feature Translation (Vietnamese)
# ============================================================

# Full translation map covering both XGBoost features and baseline features
FEATURE_TRANSLATIONS = {
    # XGBoost Risk Classifier features (25)
    "adi": "Khoảng cách trung bình giữa các lần bán (ADI)",
    "cv2": "Hệ số biến thiên nhu cầu (CV²)",
    "zero_rate_90d": "Tỷ lệ ngày không có đơn trong 90 ngày",
    "zero_rate_full": "Tỷ lệ ngày không có đơn toàn lịch sử",
    "sales_velocity_90d": "Tốc độ bán 90 ngày (sp/ngày)",
    "sales_velocity_full": "Tốc độ bán toàn lịch sử (sp/ngày)",
    "sales_last_30d": "Sản lượng bán trong 30 ngày qua",
    "past_total_sold": "Tổng sản lượng bán tích lũy",
    "dsls": "Số ngày kể từ lần bán gần nhất (DSLS)",
    "active_30d": "Trạng thái có giao dịch trong 30 ngày",
    "active_90d": "Trạng thái có giao dịch trong 90 ngày",
    "n_observation_days": "Số ngày theo dõi lịch sử",
    "forecast_7d": "Dự báo nhu cầu 7 ngày tới",
    "forecast_14d": "Dự báo nhu cầu 14 ngày tới",
    "forecast_30d": "Dự báo nhu cầu 30 ngày tới",
    "forecast_trend": "Tỷ lệ xu hướng nhu cầu dự báo",
    "demand_probability": "Xác suất phát sinh đơn hàng theo ngày (TSB)",
    "expected_demand_daily": "Kỳ vọng cầu hàng ngày (TSB)",
    "price": "Giá bán sản phẩm (VNĐ)",
    "cost": "Giá vốn nhập hàng (VNĐ)",
    "cost_imputed": "Cờ giá vốn suy đoán",
    "promo_rate": "Tỷ lệ ngày tham gia khuyến mãi",
    "brand_enc": "Mã hóa thương hiệu sản phẩm",
    "category_enc": "Mã hóa danh mục ngành hàng",
    "pattern_enc": "Mã hóa kiểu hình cầu (Intermittent/Lumpy)",
    # Baseline features
    "inventory_coverage_days": "Khả năng đáp ứng tồn kho",
    "sales_trend": "Xu hướng tăng trưởng doanh số",
    "delay_rate": "Rủi ro nhà cung cấp giao hàng chậm",
    "expiration_days_left": "Thời hạn sử dụng còn lại",
    "inventory_ratio": "Tỷ trọng vốn lưu động",
    "sales_velocity": "Tốc độ bán hàng trung bình",
    "inventory_qty": "Số lượng tồn kho thực tế",
}


# ============================================================
# Decision Confidence Computation
# ============================================================

def compute_decision_confidence(
    prediction_engine,
    explanation_engine,
    feature_completeness,
    model_calibrated,
    shap_additivity_passed,
):
    """
    Compute overall decision confidence score.

    This is NOT the same as risk_probability.
    risk_probability = model output (what the model predicts).
    decision_confidence = how much you should trust this prediction.

    Confidence penalties:
      - Baseline prediction engine: -0.30
      - Linear proxy explanation:   -0.15
      - Uncalibrated prediction:    -0.10
      - Feature incompleteness:     proportional up to -0.20
      - SHAP additivity failed:     -0.10
    """
    confidence = 1.0

    # Engine penalties
    if prediction_engine != "XGBOOST":
        confidence -= 0.30
    if explanation_engine != "TREESHAP":
        confidence -= 0.15

    # Calibration penalty
    if not model_calibrated:
        confidence -= 0.10

    # Feature completeness penalty (max -0.20)
    confidence -= (1.0 - feature_completeness) * 0.20

    # SHAP additivity penalty
    if not shap_additivity_passed:
        confidence -= 0.10

    return max(0.0, min(1.0, round(confidence, 2)))


# ============================================================
# SHAP Additivity Validation
# ============================================================

def validate_shap_additivity(
    shap_values_for_class,
    base_value,
    model_margin,
    tolerance=0.05,
):
    """
    Validate TreeSHAP additivity property:
        base_value + Σ SHAP_i ≈ model raw margin

    For XGBoost multi-class, this check is done in the log-odds (margin) space
    for the target class. Tolerance should be appropriate for the output space.

    Returns:
        dict with expected, computed, tolerance, passed, absolute_diff
    """
    shap_sum = float(np.sum(shap_values_for_class))
    computed = base_value + shap_sum
    diff = abs(computed - model_margin)

    return {
        "expected": round(float(model_margin), 4),
        "computed": round(computed, 4),
        "base_value": round(float(base_value), 4),
        "shap_sum": round(shap_sum, 4),
        "absolute_diff": round(diff, 4),
        "tolerance": tolerance,
        "passed": diff <= tolerance,
    }


# ============================================================
# SHAP Explanation Service
# ============================================================

class ShapExplanationService:
    """
    Service for calculating and interpreting SHAP values (Phase 7 & 8).

    Explanation fallback is INDEPENDENT of prediction fallback.
    Valid state: XGBoost prediction + Linear Proxy explanation.

    Architecture:
        Prediction Result (from HybridModelPipeline)
            ↓
        Explanation Engine Selection
            ├── TreeSHAP (Primary)     → shap.TreeExplainer
            └── Linear Proxy (Fallback) → heuristic coefficients
            ↓
        SHAP Additivity Validation (TreeSHAP only)
            ↓
        Vietnamese Business Label Mapping
            ↓
        Decision Confidence Computation
            ↓
        AI Copilot Explanation (Gemini or rule-based)
            ↓
        Final Response
    """

    @staticmethod
    def format_feature_value(feature_key, value):
        """Format raw numerical values into human-readable Vietnamese strings."""
        if value is None:
            return "N/A"
        if feature_key in ["inventory_coverage_days", "expiration_days_left", "dsls", "n_observation_days"]:
            if value >= 999.0:
                return "Không giới hạn"
            return f"{int(value)} ngày"
        if feature_key in ["delay_rate", "inventory_ratio", "zero_rate_90d", "zero_rate_full", "promo_rate"]:
            return f"{value * 100:.1f}%"
        if feature_key in ["sales_trend", "forecast_trend"]:
            return f"x{value:.2f}"
        if feature_key in ["sales_velocity", "sales_velocity_90d", "sales_velocity_full", "expected_demand_daily"]:
            return f"{value:.2f} sp/ngày"
        if feature_key in ["inventory_qty", "sales_7d", "sales_30d", "sales_last_30d", "past_total_sold",
                           "forecast_7d", "forecast_14d", "forecast_30d", "active_30d", "active_90d"]:
            return f"{int(value)} đơn vị"
        if feature_key in ["adi"]:
            return f"{value:.2f} ngày/lần"
        if feature_key in ["cv2"]:
            return f"{value:.4f}"
        if feature_key in ["demand_probability"]:
            return f"{value * 100:.1f}%"
        if feature_key in ["price", "cost"]:
            return f"{value:,.0f} VNĐ"
        if feature_key in ["cost_imputed"]:
            return "Có" if value > 0.5 else "Không"
        if feature_key in ["brand_enc", "category_enc", "pattern_enc"]:
            return f"Mã {int(value)}"
        return str(round(value, 4))

    @staticmethod
    def explain_prediction(pred_result, sku_id, workspace_id=1):
        """
        Tier 3: Explanation Engine.

        Computes SHAP contributions using:
          - Primary: TreeSHAP (if model + explainer available)
          - Fallback: Linear Proxy (heuristic coefficients)

        Returns dict with:
          - risk_probability, risk_level, decision_confidence
          - prediction: {engine, model_version, status, ...}
          - explanation: {engine, status, fallback_reason?}
          - shap_contributions: list of {feature_name, feature_key, feature_value, shap_value}
          - additivity_check: {expected, computed, tolerance, passed} or None
          - data_provenance: {source, snapshot_date, is_offline_snapshot}
          - ai_explanation: str
        """
        if not pred_result:
            return None

        prediction_meta = pred_result["prediction"]
        explanation_meta = {}
        shap_contributions = []
        additivity_check = None

        # ---- Attempt TreeSHAP (Primary) ----
        if (prediction_meta.get("engine") == "XGBOOST"
                and pred_result.get("feature_vector") is not None):
            try:
                explainer = ModelLoaderService.get_explainer()
                if explainer is None:
                    raise MLServiceError(
                        FailureType.EXPLANATION_ERROR,
                        "TreeExplainer not available (initialization failed)"
                    )

                feature_vector = pred_result["feature_vector"]
                feature_cols = ModelLoaderService.get_feature_cols()
                le = ModelLoaderService.get_label_encoder()
                model = ModelLoaderService.get_model()

                # Compute SHAP values
                shap_vals = explainer.shap_values(feature_vector)

                # Determine target class for SHAP display
                # We show SHAP for the combined CRITICAL+HIGH_RISK direction
                classes = list(model.classes_)
                critical_idx = classes.index(le.transform(["CRITICAL"])[0])

                # Handle multi-class SHAP shape
                # shap_vals can be list of arrays (one per class) or 3D array
                if isinstance(shap_vals, list):
                    row_shap = np.array(shap_vals[critical_idx][0])
                    base_val = float(explainer.expected_value[critical_idx])
                elif len(shap_vals.shape) == 3:
                    row_shap = shap_vals[0, :, critical_idx]
                    base_val = float(explainer.expected_value[critical_idx])
                else:
                    row_shap = shap_vals[0]
                    base_val = float(explainer.expected_value)

                # Validate SHAP count matches feature count
                if len(row_shap) != len(feature_cols):
                    raise MLServiceError(
                        FailureType.EXPLANATION_ERROR,
                        f"SHAP values count ({len(row_shap)}) != feature count ({len(feature_cols)})"
                    )

                # SHAP Additivity Validation
                # For XGBoost, SHAP operates in log-odds (margin) space
                # Get model's raw margin for this sample
                try:
                    raw_margins = model.get_booster().predict(
                        __import__('xgboost').DMatrix(feature_vector, feature_names=feature_cols),
                        output_margin=True
                    )
                    if len(raw_margins.shape) > 1:
                        model_margin = float(raw_margins[0][critical_idx])
                    else:
                        model_margin = float(raw_margins[0])

                    additivity_check = validate_shap_additivity(
                        row_shap, base_val, model_margin, tolerance=0.05
                    )
                    if not additivity_check["passed"]:
                        logger.warning(
                            "SHAP additivity check FAILED for SKU %s: "
                            "expected=%.4f, computed=%.4f, diff=%.4f > tol=%.4f",
                            sku_id,
                            additivity_check["expected"],
                            additivity_check["computed"],
                            additivity_check["absolute_diff"],
                            additivity_check["tolerance"],
                        )
                except Exception as e:
                    logger.warning("SHAP additivity validation skipped: %s", e)
                    additivity_check = None

                # Build contribution list (sorted by absolute impact)
                raw_features = pred_result.get("feature_vector", np.zeros((1, len(feature_cols))))[0]
                for idx in np.argsort(np.abs(row_shap))[::-1]:
                    shap_val = float(row_shap[idx])
                    if abs(shap_val) < 0.001:
                        continue  # Skip negligible contributions
                    f_name = feature_cols[idx]
                    f_value = float(raw_features[idx]) if idx < len(raw_features) else 0.0
                    shap_contributions.append({
                        "feature_name": FEATURE_TRANSLATIONS.get(f_name, f_name),
                        "feature_key": f_name,
                        "feature_value": f_value,
                        "formatted_value": ShapExplanationService.format_feature_value(f_name, f_value),
                        "shap_value": round(shap_val, 4),
                        "impact": "Tăng rủi ro bán chậm (+)" if shap_val > 0 else "Giảm rủi ro bán chậm (-)"
                    })

                explanation_meta = {
                    "engine": "TREESHAP",
                    "status": "PRIMARY",
                }

                logger.debug(
                    "TreeSHAP explanation for SKU %s: %d contributions, additivity=%s",
                    sku_id, len(shap_contributions),
                    "PASS" if (additivity_check and additivity_check["passed"]) else "FAIL/SKIP"
                )

            except MLServiceError as e:
                if e.failure_type == FailureType.EXPLANATION_ERROR:
                    logger.warning(
                        "TreeSHAP failed for SKU %s: %s — using Linear Proxy",
                        sku_id, e.message
                    )
                    # Fall through to Linear Proxy below
                    explanation_meta = {}
                    shap_contributions = []
                else:
                    # Non-EXPLANATION errors should not be silently caught
                    raise
            except Exception as e:
                # Unexpected SHAP error — log critical but DO NOT downgrade prediction
                logger.critical(
                    "Unexpected SHAP error for SKU %s: %s — using Linear Proxy",
                    sku_id, e, exc_info=True
                )
                # Fall through to proxy — this is EXPLANATION_ERROR, not SYSTEM_ERROR
                explanation_meta = {}
                shap_contributions = []

        # ---- Fallback: Linear Proxy SHAP ----
        if not explanation_meta:
            shap_contributions = ShapExplanationService._linear_proxy_shap(pred_result)
            fallback_reason = (
                prediction_meta.get("fallback_reason")
                or FailureType.EXPLANATION_ERROR
            )
            explanation_meta = {
                "engine": "LINEAR_PROXY",
                "status": "FALLBACK",
                "fallback_reason": fallback_reason,
            }

        # ---- Decision Confidence ----
        decision_confidence = compute_decision_confidence(
            prediction_engine=prediction_meta.get("engine", "BASELINE_LOGISTIC"),
            explanation_engine=explanation_meta.get("engine", "LINEAR_PROXY"),
            feature_completeness=pred_result.get("feature_completeness", 1.0),
            model_calibrated=prediction_meta.get("calibrated", False),
            shap_additivity_passed=(
                additivity_check.get("passed", False) if additivity_check else False
            ),
        )

        # ---- AI Copilot Natural Language Explanation ----
        ai_explanation = ShapExplanationService.generate_copilot_explanation(
            sku_id, workspace_id,
            pred_result["risk_probability"],
            pred_result.get("base_value", 0.35),
            prediction_meta.get("model_version", "unknown"),
            shap_contributions
        )

        return {
            "risk_probability": pred_result["risk_probability"],
            "risk_level": pred_result["risk_level"],
            "decision_confidence": decision_confidence,
            "base_value": pred_result.get("base_value"),
            "prediction": prediction_meta,
            "explanation": explanation_meta,
            # Top-level aliases for direct access & backward compatibility
            "prediction_engine": prediction_meta.get("engine"),
            "explanation_engine": explanation_meta.get("engine"),
            "prediction_status": prediction_meta.get("status"),
            "explanation_status": explanation_meta.get("status"),
            "model_version": prediction_meta.get("model_version"),
            "shap_contributions": shap_contributions,
            "additivity_check": additivity_check,
            "data_provenance": pred_result.get("data_provenance"),
            "ai_explanation": ai_explanation,
        }

    # ================================================================
    # Linear Proxy SHAP (Fallback Engine)
    # ================================================================

    @staticmethod
    def _linear_proxy_shap(pred_result):
        """
        Original heuristic coefficient-based SHAP proxy.
        Used when TreeSHAP is unavailable.

        This is NOT real SHAP — it uses hardcoded linear coefficients
        to approximate feature contributions.
        """
        features = pred_result.get("features", {})
        risk_probability = pred_result.get("risk_probability", 0.5)
        base_value = pred_result.get("base_value", 0.35)

        coef_coverage = -0.01
        coef_trend = 0.8
        coef_delay = 2.5
        coef_expiry = -0.05

        coverage_c = coef_coverage * (features.get("inventory_coverage_days", 30) - 30.0)
        coverage_c = max(-2.0, min(2.0, coverage_c))

        trend_c = coef_trend * (features.get("sales_trend", 1.0) - 1.0)
        delay_c = coef_delay * (features.get("delay_rate", 0.05) - 0.05)

        if features.get("expiration_days_left", 999) < 999.0:
            expiry_c = coef_expiry * (features["expiration_days_left"] - 30.0)
            expiry_c = max(0.0, expiry_c)
        else:
            expiry_c = 0.0

        ratio_c = 0.3 * (features.get("inventory_ratio", 0.05) - 0.05)

        contrib_map = {
            "inventory_coverage_days": coverage_c,
            "sales_trend": trend_c,
            "delay_rate": delay_c,
            "expiration_days_left": expiry_c,
            "inventory_ratio": ratio_c,
        }

        # Project log-odds contributions to probability space
        base_log_odds = -0.62
        base_prob = base_value

        individual_impacts = {}
        for key, val in contrib_map.items():
            p_feature = 1.0 / (1.0 + math.exp(-(base_log_odds + val)))
            individual_impacts[key] = p_feature - base_prob

        sum_impacts = sum(individual_impacts.values())
        prob_delta = risk_probability - base_prob

        shap_contributions = []
        if sum_impacts != 0:
            scale = prob_delta / sum_impacts
            for key, val in individual_impacts.items():
                shap_val = val * scale
                if abs(shap_val) >= 0.005:
                    shap_contributions.append({
                        "feature_name": FEATURE_TRANSLATIONS.get(key, key),
                        "feature_key": key,
                        "feature_value": features.get(key),
                        "formatted_value": ShapExplanationService.format_feature_value(
                            key, features.get(key)
                        ),
                        "shap_value": round(shap_val, 3),
                        "impact": "Tăng rủi ro (+)" if shap_val > 0 else "Giảm rủi ro (-)"
                    })

        # Sort by absolute impact descending
        shap_contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
        return shap_contributions

    # ================================================================
    # AI Copilot Natural Language Explanation
    # ================================================================

    @staticmethod
    def generate_copilot_explanation(
        sku_id, workspace_id, risk_probability, base_value,
        model_version, shap_contributions
    ):
        """
        Phase 8: AI Copilot Natural Language Explanation.
        Calls Gemini API with grounded context if API key exists,
        otherwise generates structured rule explanation.
        """
        try:
            product = Product.objects.get(id=sku_id)
            product_name = product.product_name or "Sản phẩm"
        except Product.DoesNotExist:
            product_name = "Sản phẩm"

        # Generate text description of SHAP contributions
        shap_lines = []
        for c in shap_contributions[:5]:  # Top 5 factors
            direction = "tăng rủi ro" if c["shap_value"] > 0 else "giảm rủi ro"
            shap_lines.append(
                f"- {c['feature_name']} ({c['feature_value']}): "
                f"{direction} {c['shap_value']*100:+.0f}%"
            )
        shap_text = "\n".join(shap_lines)

        # Check API key via GeminiCopilotService
        api_key = GeminiCopilotService.get_api_key_for_workspace(workspace_id=workspace_id)
        if api_key:
            prompt = f"""Bạn là một chuyên gia hàng đầu về quản trị chuỗi cung ứng và hàng tồn kho.
Hãy viết một đoạn giải thích ngắn gọn (tối đa 3 câu, khoảng 70-90 từ, bằng tiếng Việt) về rủi ro tồn kho của sản phẩm này cho người quản lý kho/CFO:
- Tên sản phẩm: {product_name}
- Xác suất rủi ro hiện tại: {risk_probability * 100:.0f}% (So với mức trung bình hệ thống là {base_value * 100:.0f}%)
- Phiên bản mô hình: {model_version}

Tác động đóng góp của các yếu tố (SHAP values):
{shap_text}

Yêu cầu:
- Viết văn phong chuyên nghiệp, dễ hiểu.
- Giải thích rõ nguyên nhân chính gây ra rủi ro (yếu tố đóng góp lớn nhất).
- Đưa ra hành động cụ thể ngay lập tức (ví dụ: cần giảm giá xả hàng gấp, thương lượng lại thời gian giao với nhà cung ứng, hoặc giữ nguyên).
- TUYỆT ĐỐI KHÔNG chứa markdown triple backticks (```json hoặc ```). Trả về văn bản thuần túy."""

            try:
                model_name = settings.SUPPLYFORGE.get('gemini', {}).get('model', 'gemini-1.5-flash')
                base_url = settings.SUPPLYFORGE.get('gemini', {}).get(
                    'base_url', 'https://generativelanguage.googleapis.com'
                )
                url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"

                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.3},
                }
                resp = requests.post(url, json=payload, timeout=8)
                if resp.status_code == 200:
                    res_data = resp.json()
                    text_content = res_data['candidates'][0]['content']['parts'][0]['text']
                    return text_content.strip()
            except Exception as e:
                logger.warning("[SHAP Copilot Gemini API Error]: %s", e)

        # ---- High-fidelity Rule-based Fallback Generator ----
        if not shap_contributions:
            return (
                f"Rủi ro tồn kho của {product_name} duy trì ổn định ở mức trung bình "
                f"{risk_probability * 100:.0f}%. Không phát hiện bất thường về tốc độ bán hàng "
                f"hoặc thời hạn lưu kho."
            )

        top_factor = shap_contributions[0]
        reasons = []
        recommendations = []

        for c in shap_contributions[:2]:
            sign_char = "+" if c["shap_value"] > 0 else "-"
            reasons.append(
                f"{c['feature_name']} ở mức {c['feature_value']} "
                f"({sign_char}{abs(c['shap_value'])*100:.0f}%)"
            )

        # Context-aware recommendation based on top factor
        top_key = top_factor.get("feature_key", "")
        if top_key in ("inventory_coverage_days", "dsls") and top_factor["shap_value"] > 0:
            recommendations.append(
                "cần xem xét giảm giá thanh lý để giải phóng kho và bảo toàn dòng tiền"
            )
        elif top_key == "delay_rate" and top_factor["shap_value"] > 0:
            recommendations.append(
                "nên thương lượng tăng lượng an toàn (safety stock) hoặc đa dạng hóa nhà cung cấp"
            )
        elif top_key in ("expiration_days_left",) and top_factor["shap_value"] > 0:
            recommendations.append(
                "cần triển khai gấp chương trình khuyến mãi bundle để đẩy nhanh hạn dùng"
            )
        elif top_key in ("zero_rate_90d", "zero_rate_full") and top_factor["shap_value"] > 0:
            recommendations.append(
                "sản phẩm có tỷ lệ ngày không bán rất cao, cần đánh giá lại demand và xem xét ngừng nhập"
            )
        elif top_key in ("sales_velocity_90d", "sales_velocity_full", "forecast_7d", "forecast_30d"):
            if top_factor["shap_value"] < 0:
                recommendations.append(
                    "sản phẩm đang tiêu thụ tốt, có thể cân nhắc nhập thêm hàng"
                )
            else:
                recommendations.append(
                    "tốc độ bán hàng chậm, cần đẩy mạnh marketing hoặc giảm giá kích cầu"
                )
        else:
            recommendations.append("hãy theo dõi sát sao tốc độ bán hàng trong 14 ngày tới")

        reason_text = " và ".join(reasons)
        rec_text = recommendations[0] if recommendations else "cần theo dõi thêm"

        return (
            f"Rủi ro tồn kho của sản phẩm là {risk_probability * 100:.0f}% "
            f"(mức nền: {base_value * 100:.0f}%), "
            f"được thúc đẩy bởi {reason_text}. "
            f"Để tối ưu, doanh nghiệp {rec_text}."
        )
