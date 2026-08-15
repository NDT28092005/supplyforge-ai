"""Deterministic Business Rule Engine Module."""
import pandas as pd
from typing import Dict, List

STANDARD_DSS_CAVEATS = [
    "Dữ liệu tồn kho kho vận thực tế không được quan sát trực tiếp trong tập tính năng quan sát t0.",
    "Các cờ nguyên nhân nghiệp vụ (Business Cause Tags) là tín hiệu chẩn đoán hỗ trợ (diagnostic signals), không phải kết luận nguyên nhân tuyệt đối.",
    "Mọi khuyến nghị hành động mang tính chất gợi ý tham khảo cho Merchant/Planner ra quyết định cuối cùng."
]

def evaluate_business_rules(row: pd.Series, risk_label: str) -> Dict[str, List[str]]:
    """Evaluate business cause rules and return Cause Tags, Interpretations, and Action Recommendations."""
    tags = []
    interpretations = []
    actions = []

    vel = float(row.get("sales_velocity_90d", 0))
    adi = float(row.get("adi", 0))
    cv2 = float(row.get("cv2", 0))
    dsls = float(row.get("dsls", 0))
    promo_rate = float(row.get("promo_rate", 0))
    zero_r_90 = float(row.get("zero_rate_90d", 0))
    active_30 = int(row.get("active_30d", 0))

    if vel < 0.1:
        tags.append("LOW_SALES_VELOCITY")
        interpretations.append("Sản phẩm có tốc độ bán hàng rất thấp trong 90 ngày gần nhất (dưới 0.1 sp/ngày).")
        actions.append("Đánh giá lại chính sách giá bán và hiển thị sản phẩm trên sàn e-commerce.")
        actions.append("Cân nhắc tạo chương trình kích cầu hoặc tạo gói Combo ghép với sản phẩm bán chạy (Fast-moving SKU).")

    if adi > 1.32 and cv2 > 0.49:
        tags.append("LUMPY_DEMAND")
        interpretations.append("Nhu cầu có tính gián đoạn cao (ADI > 1.32) kết hợp biến động quy mô đơn trồi sụt mạnh (CV² > 0.49).")
        actions.append("Hạn chế nhập hàng ồ ạt; rà soát lại chính sách tồn kho an toàn (Safety Stock).")

    if dsls > 180 or risk_label == "CRITICAL":
        tags.append("POSSIBLE_OBSOLESCENCE")
        interpretations.append("Sản phẩm có dấu hiệu dừng phát sinh giao dịch kéo dài (DSLS > 180 ngày hoặc thuộc nhóm CRITICAL); cần kiểm tra nguy cơ suy giảm vòng đời.")
        actions.append("Rà soát vòng đời sản phẩm, xem xét chiến lược xả hàng hoặc tạm ngừng kế hoạch nhập bổ sung.")

    if promo_rate > 0.20 and vel < 0.5:
        tags.append("PROMO_ASSOCIATED_LOW_VELOCITY")
        interpretations.append("Sản phẩm được tham gia khuyến mãi thường xuyên (>20% số ngày) nhưng tốc độ bán thực tế vẫn dưới 0.5 sp/ngày.")
        actions.append("Đánh giá lại hiệu quả chương trình khuyến mãi và mức độ sâu của giảm giá.")

    if zero_r_90 > 0.70 and active_30 == 1:
        tags.append("POSSIBLE_STOCKOUT_EFFECT")
        interpretations.append("Ghi nhận tỷ lệ ngày zero-sales cao (>70%) nhưng sản phẩm vẫn có giao dịch phát sinh trong 30 ngày gần đây; cần kiểm tra khả năng gián đoạn nguồn cung.")
        actions.append("Kiểm tra dữ liệu tồn kho thực tế và khả năng cung ứng của nhà cung cấp để xác nhận tình trạng hàng sẵn có.")

    if not tags:
        tags.append("NORMAL_MONITORED")
        interpretations.append("Các chỉ số bán hàng và nhu cầu nằm trong ngưỡng theo dõi bình thường.")
        actions.append("Tiếp tục duy trì kế hoạch bán hàng và theo dõi định kỳ.")

    return {
        "business_cause_tags": list(dict.fromkeys(tags)),
        "interpretations_vi": list(dict.fromkeys(interpretations)),
        "recommended_actions_vi": list(dict.fromkeys(actions))
    }
