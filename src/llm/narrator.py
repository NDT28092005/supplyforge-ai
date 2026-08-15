"""Gemini Natural Language Decision Narrator Module."""
import json
from typing import Dict

RISK_TRANSLATION_VI = {
    "CRITICAL": "Rủi ro Cực kỳ Cao (CRITICAL)",
    "HIGH_RISK": "Rủi ro Cao (HIGH RISK)",
    "MEDIUM_RISK": "Rủi ro Trung bình (MEDIUM RISK)",
    "LOW_RISK": "Rủi ro Thấp (LOW RISK)"
}

def generate_merchant_report(dss_payload: Dict) -> str:
    """Generate natural Vietnamese merchant decision report from Canonical DSS Payload."""
    sku_id = dss_payload["itemId"]
    risk_lvl = dss_payload["risk_level"]
    risk_lbl_vi = RISK_TRANSLATION_VI.get(risk_lvl, risk_lvl)
    prob_pct = round(float(dss_payload["predicted_risk_prob"]) * 100, 1)
    demand_pat = dss_payload.get("demand_pattern", "Gián đoạn")
    
    # Section 1: Executive Summary
    sec1 = f"### 1. TỔNG QUAN RỦI RO SẢN PHẨM (SKU {sku_id})\n"
    sec1 += f"- **Phân loại rủi ro**: **{risk_lbl_vi}**\n"
    sec1 += f"- **Xác suất rủi ro dự báo từ mô hình**: **{prob_pct}%**\n"
    sec1 += f"- **Mô hình nhu cầu (Demand Pattern)**: **{demand_pat}**\n"
    sec1 += f"- **Tốc độ bán quan sát (90 ngày)**: **{dss_payload.get('sales_velocity_90d', 0)} sp/ngày**\n"
    
    # Section 2: Key SHAP Evidence
    sec2 = "\n### 2. TÍN HIỆU DỮ LIỆU CHÍNH (SHAP EVIDENCE)\n"
    for ev in dss_payload.get("shap_top_evidence", []):
        sec2 += f"- **{ev['business_name_vi']}**: Mức quan sát `{ev['observed_value']}` ──> {ev['impact']}\n"
        
    # Section 3: Business Diagnosis Tags
    sec3 = "\n### 3. CHẨN ĐOÁN NGUYÊN NHÂN NGHIỆP VỤ (BUSINESS DIAGNOSIS)\n"
    for tag, interp in zip(dss_payload.get("business_cause_tags", []), dss_payload.get("interpretations_vi", [])):
        sec3 += f"- **[{tag}]**: {interp}\n"
        
    # Section 4: Recommended Actions
    sec4 = "\n### 4. KHUYẾN NGHỊ HÀNH ĐỘNG CHO MERCHANT\n"
    for act in dss_payload.get("recommended_actions_vi", []):
        sec4 += f"- {act}\n"
        
    # Section 5: Standard Caveats
    sec5 = "\n### 5. LƯU Ý KHI SỬ DỤNG HỆ THỐNG DSS\n"
    for cav in dss_payload.get("dss_caveats", []):
        sec5 += f"- *{cav}*\n"

    return sec1 + sec2 + sec3 + sec4 + sec5
