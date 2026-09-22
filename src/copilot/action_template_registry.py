"""
Action Template Registry for Task M7-08 Action Planning.
Module 07: AI Copilot & Merchant Workspace

Defines operational task decomposition templates for M6 Decision Actions.
"""

from typing import Dict, Any, List


class ActionTemplateRegistry:
    """Registry of operational task templates for decision actions."""

    TEMPLATES = {
        "DISCOUNT": [
            {"task_id": "T01", "title": "Kiểm tra biên lợi nhuận hiện tại (Validate Margin)", "owner_role": "Merchandising", "sla_hours": 12, "depends_on": []},
            {"task_id": "T02", "title": "Chuẩn bị chiến dịch giảm giá (Prepare Campaign)", "owner_role": "Marketing", "sla_hours": 24, "depends_on": ["T01"]},
            {"task_id": "T03", "title": "Thiết lập mức giảm giá trên hệ thống (Apply Discount)", "owner_role": "Store Operator", "sla_hours": 12, "depends_on": ["T02"]},
            {"task_id": "T04", "title": "Theo dõi tốc độ bán hàng (Monitor Sales Performance)", "owner_role": "Inventory Manager", "sla_hours": 168, "depends_on": ["T03"]},
            {"task_id": "T05", "title": "Đánh giá hiệu quả thu hồi vốn (Evaluate Recovery Outcome)", "owner_role": "Inventory Manager", "sla_hours": 24, "depends_on": ["T04"]}
        ],
        "BUNDLE": [
            {"task_id": "T01", "title": "Lựa chọn sản phẩm đi kèm (Select Bundle Partner SKU)", "owner_role": "Merchandising", "sla_hours": 24, "depends_on": []},
            {"task_id": "T02", "title": "Tạo gói sản phẩm Combo (Create Bundle SKU)", "owner_role": "Store Operator", "sla_hours": 12, "depends_on": ["T01"]},
            {"task_id": "T03", "title": "Theo dõi doanh số Combo (Monitor Bundle Sales)", "owner_role": "Inventory Manager", "sla_hours": 168, "depends_on": ["T02"]}
        ],
        "LIQUIDATION": [
            {"task_id": "T01", "title": "Đánh giá chi phí thanh lý tồn kho (Evaluate Liquidation Costs)", "owner_role": "Merchandising", "sla_hours": 24, "depends_on": []},
            {"task_id": "T02", "title": "Liên hệ đối tác thanh lý (Contact Liquidation Partner)", "owner_role": "Inventory Manager", "sla_hours": 48, "depends_on": ["T01"]},
            {"task_id": "T03", "title": "Thực hiện xuất kho thanh lý (Execute Clearance)", "owner_role": "Store Operator", "sla_hours": 24, "depends_on": ["T02"]}
        ],
        "PROMOTION": [
            {"task_id": "T01", "title": "Lên kịch bản khuyến mãi (Design Promotion Scenario)", "owner_role": "Marketing", "sla_hours": 24, "depends_on": []},
            {"task_id": "T02", "title": "Phát hành voucher/khuyến mãi (Publish Promotion)", "owner_role": "Store Operator", "sla_hours": 12, "depends_on": ["T01"]}
        ],
        "HOLD": [
            {"task_id": "T01", "title": "Tạm dừng đơn đặt hàng mới (Pause Procurement Orders)", "owner_role": "Procurement", "sla_hours": 12, "depends_on": []},
            {"task_id": "T02", "title": "Theo dõi biến động cầu kho (Monitor Inventory Buffer)", "owner_role": "Inventory Manager", "sla_hours": 168, "depends_on": ["T01"]}
        ],
        "MONITOR": [
            {"task_id": "T01", "title": "Cài đặt cảnh báo tuổi tồn kho (Set Inventory Aging Alert)", "owner_role": "Inventory Manager", "sla_hours": 12, "depends_on": []}
        ]
    }

    @classmethod
    def get_template(cls, action_type: str) -> List[Dict[str, Any]]:
        return cls.TEMPLATES.get(action_type.upper(), cls.TEMPLATES["MONITOR"])
