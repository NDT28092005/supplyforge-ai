"""4-Tier Operational Decision Priority Policy Module."""

def assign_decision_policy(calibrated_prob: float) -> dict:
    """Map calibrated probability to 4-tier operational decision priority."""
    if calibrated_prob >= 0.90:
        return {
            "tier_code": "CRITICAL_ATTENTION",
            "tier_display": "🔴 Critical Attention",
            "priority_rank": 1,
            "merchant_action": "Rà soát giảm giá xả hàng ngay lập tức (Immediate Clearance / Markdown Review)."
        }
    elif calibrated_prob >= 0.75:
        return {
            "tier_code": "HIGH_ATTENTION",
            "tier_display": "🟠 High Attention",
            "priority_rank": 2,
            "merchant_action": "Tạo chương trình Combo / Kích cầu và rà soát mức tồn kho an toàn (Safety Stock Audit)."
        }
    elif calibrated_prob >= 0.50:
        return {
            "tier_code": "MONITOR",
            "tier_display": "🟡 Monitor",
            "priority_rank": 3,
            "merchant_action": "Theo dõi chu kỳ đặt hàng bổ sung & biến động nhu cầu gián đoạn (Scheduled Replenishment)."
        }
    else:
        return {
            "tier_code": "NORMAL",
            "tier_display": "🟢 Normal",
            "priority_rank": 4,
            "merchant_action": "Duy trì hoạt động bán hàng & giám sát định kỳ (Routine Sales Monitoring)."
        }
