import re


class IndustryPlaybook:
    def __init__(self, display_name, aging_risk_multiplier, max_shelf_life_days, liquidation_strategies, risk_factors):
        self.display_name = display_name
        self.aging_risk_multiplier = aging_risk_multiplier
        self.max_shelf_life_days = max_shelf_life_days
        self.liquidation_strategies = liquidation_strategies
        self.risk_factors = risk_factors

    def calculate_aging_score(self, days_in_inventory):
        return days_in_inventory * self.aging_risk_multiplier

    def classify_aging_bucket(self, days_in_inventory):
        shelf_life = self.max_shelf_life_days
        aging_score = self.calculate_aging_score(days_in_inventory)

        dead_threshold = shelf_life * self.aging_risk_multiplier
        slow_threshold = shelf_life * self.aging_risk_multiplier * 0.67
        watchlist_threshold = shelf_life * self.aging_risk_multiplier * 0.33

        if aging_score >= dead_threshold:
            return "DEAD_STOCK"
        elif aging_score >= slow_threshold:
            return "SLOW_MOVING"
        elif aging_score >= watchlist_threshold:
            return "WATCHLIST"
        else:
            return "HEALTHY"


PLAYBOOKS = {
    'MOTHER_BABY': IndustryPlaybook(
        "Mẹ & Bé (Tã bỉm & Chăm sóc)", 1.1, 90,
        ["Bundle Combo Mẹ & Bé", "Flash Sale Tã Bỉm", "Quà Tặng Kèm Baby"],
        ["Đổi cỡ (up-size) theo độ tuổi bé", "Nhạy cảm thương hiệu"]
    ),
    'FASHION_FAST': IndustryPlaybook(
        "Thời trang nhanh", 1.8, 60,
        ["Cross-season Bundle", "Flash Sale Size-break", "KOL Clearance"],
        ["Lỗi thời theo mùa", "Rủi ro tồn lẻ size", "Nhạy cảm trend"]
    ),
    'ELECTRONICS_TECH': IndustryPlaybook(
        "Điện tử & Công nghệ", 1.2, 180,
        ["B2B Wholesale", "Refurbishment / Spare Parts", "Trade-in Upgrade Program"],
        ["Lỗi thời công nghệ", "Ra mắt model mới làm giảm giá trị", "Rủi ro tương thích phần mềm"]
    ),
    'FMCG_FOOD': IndustryPlaybook(
        "Thực phẩm & FMCG", 2.5, 30,
        ["Dynamic Markdown theo ngày", "Donation (Từ thiện) — LIFO Tax Shield", "Flash Deal cuối ngày"],
        ["Rủi ro hết hạn sử dụng", "Quy định an toàn thực phẩm", "Chi phí tiêu hủy nếu quá date"]
    ),
    'HOME_LIVING': IndustryPlaybook(
        "Nội thất & Gia dụng", 1.0, 120,
        ["Showroom Display Deal", "B2B Contract Supply", "Bundle theo phòng (Room Package)"],
        ["Chi phí lưu kho cao (cồng kềnh)", "Xu hướng thiết kế nội thất thay đổi", "Rủi ro hư hại vật lý khi di chuyển"]
    ),
    'GENERAL': IndustryPlaybook(
        "Tổng hợp", 1.0, 90,
        ["Progressive Discount", "Bundle Cross-sell", "B2B Wholesale"],
        ["Rủi ro tồn kho tổng hợp"]
    )
}


class IndustryDetectionService:
    KEYWORD_MAP = [
        # Mother & Baby / Diapers (Must be checked BEFORE Fashion so 'Tã bỉm quần XL/L' matches Mother & Baby)
        (re.compile(r"\b(tã|ta|bỉm|bim|mẹ|me|bé|be|em bé|em be|trẻ em|tre em|sơ sinh|so sinh|pampers|merries|moony|huggies|goon|genki|bobby|mustela|chăm sóc bé|khăn ướt|khan uot)\b", re.IGNORECASE), 'MOTHER_BABY'),
        # FMCG & Food
        (re.compile(r"\b(sữa|sua|bột|bot|thực phẩm|thuc pham|ăn|uống|an uong|đồ ăn|do an|bánh|banh|kẹo|keo|nước|nuoc|đồ uống|do uong|vitamin|supplement|snack|mì|mi|gạo|gao|dầu ăn|dau an|gia vị|gia vi|sốt|sot|yogurt|fmcg|date|hsd|han su dung)\b", re.IGNORECASE), 'FMCG_FOOD'),
        # Fashion
        (re.compile(r"\b(áo|ao|quần|quan|váy|vay|đầm|dam|đồ|do|size|xl|xxl|m|l|s|shirt|dress|pants|skirt|jacket|coat|jeans|hoodie|sweater|blouse|suit|phong cách|thời trang|thoi trang|mùa|mua|xuân|xuan|hè|he|thu|đông|dong|fashion|wear|outfit|sandal|dép|dep|giày|giay|túi|tui|ví|vi|balo|mũ|mu|nón|non)\b", re.IGNORECASE), 'FASHION_FAST'),
        # Electronics
        (re.compile(r"\b(iphone|samsung|laptop|macbook|dell|lenovo|asus|hp|máy tính|may tinh|điện thoại|dien thoai|tai nghe|headphone|earphone|airpod|speaker|loa|chuột|chuot|bàn phím|ban phim|keyboard|mouse|monitor|màn hình|man hinh|ssd|hdd|ram|cpu|gpu|card|chip|usb|hub|cable|cáp|cap|router|modem|wifi|gaming|game|controller|console|playstation|xbox|nintendo|camera|máy ảnh|may anh|lens|ống kính|ong kinh|drone|smartwatch|tablet|ipad|android|ios|tech|gb|tb|mhz|ghz|4k|8k)\b", re.IGNORECASE), 'ELECTRONICS_TECH'),
        # Home & Living
        (re.compile(r"\b(bàn|ban|ghế|ghe|tủ|tu|kệ|ke|giường|giuong|sofa|nội thất|noi that|đèn|den|lamp|đồ gia dụng|do gia dung|nồi|noi|chảo|chao|bình|binh|ly|cốc|coc|chén|chen|bếp|bep|tủ lạnh|tu lanh|máy lạnh|may lanh|điều hòa|dieu hoa|máy giặt|may giat|tivi|tv|home|living|decor|nến|nen|thảm|tham|gối|goi|chăn|chan|màn|man|rèm|rem|bình hoa|binh hoa|tranh|khung|frame|mirror|gương|guong)\b", re.IGNORECASE), 'HOME_LIVING')
    ]

    @staticmethod
    def detect(sku_name, category=None):
        combined = (sku_name or "").strip().lower()
        if category:
            combined += " " + category.strip().lower()

        for pattern, playbook_key in IndustryDetectionService.KEYWORD_MAP:
            if pattern.search(combined):
                return PLAYBOOKS[playbook_key], playbook_key

        return PLAYBOOKS['GENERAL'], 'GENERAL'
