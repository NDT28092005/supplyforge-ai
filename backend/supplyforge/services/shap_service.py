import requests
from django.conf import settings
from supplyforge.models import Product
from supplyforge.services.gemini_copilot import GeminiCopilotService

class ShapExplanationService:
    """
    Service for calculating and interpreting SHAP (SHapley Additive exPlanations) values (Phase 7 & 8).
    Translates cryptic feature names into business-friendly Vietnamese.
    Generates natural language business explanation via Gemini Copilot or fallback rule engine.
    """

    FEATURE_TRANSLATIONS = {
        "inventory_coverage_days": "Khả năng đáp ứng tồn kho",
        "sales_trend": "Xu hướng tăng trưởng doanh số",
        "delay_rate": "Rủi ro nhà cung cấp giao hàng chậm",
        "expiration_days_left": "Thời hạn sử dụng còn lại",
        "inventory_ratio": "Tỷ trọng vốn lưu động",
        "sales_velocity": "Tốc độ bán hàng trung bình",
        "inventory_qty": "Số lượng tồn kho thực tế"
    }

    @staticmethod
    def format_feature_value(feature_key, value):
        """Helper to format raw numerical values into standard readable strings."""
        if value is None:
            return "N/A"
        if feature_key in ["inventory_coverage_days", "expiration_days_left"]:
            if value >= 999.0:
                return "Không giới hạn"
            return f"{int(value)} ngày"
        if feature_key in ["delay_rate", "inventory_ratio"]:
            return f"{value * 100:.1f}%"
        if feature_key == "sales_trend":
            return f"x{value:.2f}"
        if feature_key == "sales_velocity":
            return f"{value:.2f} đơn vị/ngày"
        if feature_key == "inventory_qty":
            return f"{int(value)} đơn vị"
        return str(value)

    @staticmethod
    def explain_prediction(pred_result, sku_id, workspace_id=1):
        """
        Phase 7: Explainable AI.
        Calculates feature contributions (SHAP values) in the probability space.
        Maps values to human-readable strings.
        """
        if not pred_result:
            return None

        features = pred_result["features"]
        risk_probability = pred_result["risk_probability"]
        base_value = pred_result["base_value"]
        model_version = pred_result["model_version"]

        # Recalculate contributions in log-odds space to distribute the probability delta.
        # This is mathematically consistent with the model's logistic formulation.
        coef_coverage = -0.01
        coef_trend = 0.8
        coef_delay = 2.5
        coef_expiry = -0.05

        coverage_c = coef_coverage * (features["inventory_coverage_days"] - 30.0)
        coverage_c = max(-2.0, min(2.0, coverage_c))
        
        trend_c = coef_trend * (features["sales_trend"] - 1.0)
        delay_c = coef_delay * (features["delay_rate"] - 0.05)
        
        if features["expiration_days_left"] < 999.0:
            expiry_c = coef_expiry * (features["expiration_days_left"] - 30.0)
            expiry_c = max(0.0, expiry_c)
        else:
            expiry_c = 0.0

        # Small default for ratio
        ratio_c = 0.3 * (features["inventory_ratio"] - 0.05)

        contrib_map = {
            "inventory_coverage_days": coverage_c,
            "sales_trend": trend_c,
            "delay_rate": delay_c,
            "expiration_days_left": expiry_c,
            "inventory_ratio": ratio_c
        }

        # Project log-odds contributions to probability space proportionally and consistently
        import math
        base_prob = base_value
        base_log_odds = -0.62

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
                        "feature_name": ShapExplanationService.FEATURE_TRANSLATIONS.get(key, key),
                        "feature_value": ShapExplanationService.format_feature_value(key, features[key]),
                        "shap_value": round(shap_val, 3)
                    })
        
        # Sort contributions by absolute impact descending
        shap_contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)

        # Phase 8: AI Copilot natural language explanation
        ai_explanation = ShapExplanationService.generate_copilot_explanation(
            sku_id, workspace_id, risk_probability, base_value, model_version, shap_contributions
        )

        return {
            "risk_probability": risk_probability,
            "base_value": base_value,
            "model_version": model_version,
            "shap_contributions": shap_contributions,
            "ai_explanation": ai_explanation
        }

    @staticmethod
    def generate_copilot_explanation(sku_id, workspace_id, risk_probability, base_value, model_version, shap_contributions):
        """
        Phase 8: AI Copilot Natural Language Explanation.
        Calls Gemini API with grounded context if API key exists, otherwise generates structured rule explanation.
        """
        try:
            product = Product.objects.get(id=sku_id)
            product_name = product.product_name or "Sản phẩm"
        except Product.DoesNotExist:
            product_name = "Sản phẩm"

        # Generate text description of SHAP contributions
        shap_lines = []
        for c in shap_contributions:
            direction = "tăng rủi ro" if c["shap_value"] > 0 else "giảm rủi ro"
            shap_lines.append(f"- {c['feature_name']} ({c['feature_value']}): {direction} {c['shap_value']*100:+.0f}%")
        shap_text = "\n".join(shap_lines)

        # Check API key via GeminiCopilotService
        api_key = GeminiCopilotService.get_api_key_for_workspace(workspace_id=workspace_id)
        if api_key:
            # Construct Copilot Prompt
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
                base_url = settings.SUPPLYFORGE.get('gemini', {}).get('base_url', 'https://generativelanguage.googleapis.com')
                url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"

                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                    }
                }
                resp = requests.post(url, json=payload, timeout=8)
                if resp.status_code == 200:
                    res_data = resp.json()
                    text_content = res_data['candidates'][0]['content']['parts'][0]['text']
                    return text_content.strip()
            except Exception as e:
                print(f"[SHAP Copilot Gemini API Error]: {e}")

        # High-fidelity Rule-based Fallback Generator
        # Identifies top factors and structures them into natural supply chain insights
        if not shap_contributions:
            return f"Rủi ro tồn kho của {product_name} duy trì ổn định ở mức trung bình {risk_probability * 100:.0f}%. Không phát hiện bất thường về tốc độ bán hàng hoặc thời hạn lưu kho."

        top_factor = shap_contributions[0]
        direction_word = "tăng đáng kể" if top_factor["shap_value"] > 0 else "giảm thiểu"
        
        reasons = []
        recommendations = []

        # Draft reasoning based on top factors
        for c in shap_contributions[:2]:
            sign_char = "+" if c["shap_value"] > 0 else "-"
            reasons.append(f"{c['feature_name']} ở mức {c['feature_value']} ({sign_char}{abs(c['shap_value'])*100:.0f}%)")

        if top_factor["feature_name"] == "Khả năng đáp ứng tồn kho":
            if top_factor["shap_value"] > 0:
                recommendations.append("cần xem xét giảm giá thanh lý để giải phóng kho và bảo toàn dòng tiền")
            else:
                recommendations.append("sản phẩm đang tiêu thụ tốt, có thể cân nhắc nhập thêm hàng")
        elif top_factor["feature_name"] == "Rủi ro nhà cung cấp giao hàng chậm":
            recommendations.append("nên thương lượng tăng lượng an toàn (safety stock) hoặc đa dạng hóa nhà cung cấp")
        elif top_factor["feature_name"] == "Thời hạn sử dụng còn lại":
            recommendations.append("cần triển khai gấp chương trình khuyến mãi bundle để đẩy nhanh hạn dùng")
        else:
            recommendations.append("hãy theo dõi sát sao tốc độ bán hàng trong 14 ngày tới")

        reason_text = " và ".join(reasons)
        rec_text = recommendations[0] if recommendations else "cần theo dõi thêm"

        fallback_explanation = (
            f"Rủi ro tồn kho của sản phẩm là {risk_probability * 100:.0f}% (mức nền: {base_value * 100:.0f}%), "
            f"được thúc đẩy bởi {reason_text}. Để tối ưu, doanh nghiệp {rec_text}."
        )
        return fallback_explanation
