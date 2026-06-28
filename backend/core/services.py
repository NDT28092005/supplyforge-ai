import re
import math
import unicodedata
import requests
import json
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction, connection, models
from django.db.models import Sum, Count, Q
from .models import Product, Order, OrderItem, Sku, InventoryRecord, InsightAnomaly, User, Workspace

# ─── Vietnamese Normalizer ───
class VietnameseNormalizer:
    @staticmethod
    def strip_accents(input_str):
        if not input_str:
            return ""
        # Replace đ/Đ
        replaced = re.sub(r'đ', 'd', input_str)
        replaced = re.sub(r'Đ', 'D', replaced)
        # NFD decompose
        decomposed = unicodedata.normalize('NFD', replaced)
        # Remove combining marks
        stripped = "".join([c for c in decomposed if not unicodedata.combining(c)])
        return stripped.lower()


# ─── Levenshtein Distance ───
class Levenshtein:
    @staticmethod
    def distance(a, b):
        if a is None:
            a = ""
        if b is None:
            b = ""
        n, m = len(a), len(b)
        if n == 0:
            return m
        if m == 0:
            return n

        prev = list(range(m + 1))
        curr = [0] * (m + 1)

        for i in range(1, n + 1):
            curr[0] = i
            ca = a[i - 1]
            for j in range(1, m + 1):
                cost = 0 if ca == b[j - 1] else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = list(curr)

        return prev[m]


# ─── Industry Playbooks ───
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


# ─── Gemini Column Mapping Service ───
class GeminiColumnMappingService:
    SYSTEM_PROMPT = """Bạn là chuyên gia dữ liệu Ecommerce Đông Nam Á. Nhiệm vụ: từ header + vài dòng mẫu, xác định chỉ số cột (0-based) map vào: SKU/tên hàng, số lượng, giá bán (hoặc giá vốn nếu chỉ có một cột giá).
Trả về DUY NHẤT một JSON object với các khóa:
sku_column_index (int),
quantity_column_index (int),
selling_price_column_index (int hoặc null nếu không có),
cost_price_column_index (int hoặc null),
record_date_column_index (int hoặc null),
price_is_cost (boolean, true nếu cột giá duy nhất là giá vốn),
confidence (string: high|medium|low),
notes (string ngắn).
Tên cột có thể tiếng Việt sai chính tả. Nếu không chắc, chọn mức confidence thấp và giải thích ngắn trong notes."""

    @staticmethod
    def infer_column_mapping(headers, sample_rows):
        api_key = settings.SUPPLYFORGE['gemini']['api_key']
        model = settings.SUPPLYFORGE['gemini']['model']
        base_url = settings.SUPPLYFORGE['gemini']['base_url']

        if not api_key:
            return GeminiColumnMappingService.heuristic_mapping(headers)

        try:
            # Build payload matching Gemini API structure
            user_content = f"Header (cột 0..n-1):\n" + "\t".join(headers) + "\n\nMẫu tối đa 5 dòng:\n"
            for row in sample_rows:
                user_content += "\t".join(row) + "\n"

            prompt = f"{GeminiColumnMappingService.SYSTEM_PROMPT}\n\n{user_content}"
            
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.1
                }
            }

            url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
            headers_http = {"Content-Type": "application/json"}
            
            response = requests.post(url, json=payload, headers=headers_http, timeout=30)
            if response.status_code == 200:
                res_data = response.json()
                if "candidates" in res_data:
                    text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    mapping = json.loads(text_content)
                    mapping["source"] = "gemini"
                    return mapping
            
            return GeminiColumnMappingService.heuristic_mapping(headers)
        except Exception:
            return GeminiColumnMappingService.heuristic_mapping(headers)

    @staticmethod
    def heuristic_mapping(headers):
        h = [col.lower() for col in headers]

        def find_index(keywords, fallback):
            for i, head in enumerate(h):
                for kw in keywords:
                    if kw in head:
                        return i
            return fallback

        return {
            "sku_column_index": find_index(["sku", "mã", "code"], 0),
            "quantity_column_index": find_index(["quantity", "số lượng", "qty", "sl"], 1),
            "selling_price_column_index": find_index(["selling_price", "giá bán", "price", "giá"], 2),
            "cost_price_column_index": find_index(["cost_price", "giá vốn", "cost", "vốn"], 3),
            "record_date_column_index": find_index(["record_date", "ngày", "date"], 5),
            "price_is_cost": False,
            "confidence": "medium",
            "notes": "Heuristic Mapping (không dùng AI do thiếu API Key).",
            "source": "heuristic_improved"
        }


# ─── Financial Liquidation Engine ───
class FinancialLiquidationEngine:
    @staticmethod
    def classify_inventory_matrix(total_value, days_in_inventory):
        cfg = settings.SUPPLYFORGE['finance']
        slow_max = settings.SUPPLYFORGE['aging']['slow_moving_max_days']

        is_old = days_in_inventory > slow_max
        is_high_value = total_value >= cfg['high_value_threshold']
        is_mid_value = cfg['mid_value_threshold'] <= total_value < cfg['high_value_threshold']

        if not is_old and is_high_value: return "HIGH_VALUE_NEW"
        if not is_old and is_mid_value: return "MID_VALUE_NEW"
        if not is_old: return "LOW_VALUE_NEW"
        if is_high_value: return "HIGH_VALUE_OLD"
        if is_mid_value: return "MID_VALUE_OLD"
        return "LOW_VALUE_OLD"

    @staticmethod
    def calculate_write_off_impact(accounting_method, cost_basis):
        tax_rate = settings.SUPPLYFORGE['finance']['tax_rate']
        tax_saving = cost_basis * tax_rate
        if accounting_method.upper() == 'LIFO':
            return (
                f"LIFO: Ghi nhận hàng mới nhất (giá vốn cao nhất). Tối đa hóa khấu trừ thuế. "
                f"Lá chắn thuế ước tính: {tax_saving:,.0f} VND ({tax_rate*100:.0f}% thuế TNDN × giá vốn). "
                f"Phù hợp khi cần tối ưu nghĩa vụ thuế cuối năm."
            )
        return (
            f"FIFO: Ghi nhận hàng nhập trước (giá vốn thấp hơn). Bảo toàn dòng tiền hiện tại. "
            f"Lá chắn thuế ước tính: {tax_saving:,.0f} VND (tác động giảm thuế thấp hơn LIFO). "
            f"Phù hợp khi ưu tiên tính nhất quán báo cáo tài chính."
        )

    @staticmethod
    def calculate_liquidation_roi(sku_dto, discount_pct, accounting_method):
        cfg = settings.SUPPLYFORGE['finance']

        original_cost_basis = float(sku_dto['cost_price']) * sku_dto['quantity']
        months_in_inventory = max(1.0, sku_dto['days_in_inventory'] / 30.0)
        monthly_storage_rate = cfg['storage_cost_yearly_rate'] / 12.0
        accumulated_storage_cost = original_cost_basis * monthly_storage_rate * months_in_inventory
        total_sunk_cost = original_cost_basis + accumulated_storage_cost

        sale_price = float(sku_dto['selling_price']) * (1.0 - discount_pct)
        sale_price = max(0.0, sale_price)
        expected_revenue = sale_price * sku_dto['quantity']

        marketing_cost = expected_revenue * cfg['marketing_cost_rate']
        net_revenue = expected_revenue - marketing_cost

        gross_recovery_rate = (expected_revenue / original_cost_basis * 100.0) if original_cost_basis > 0 else 0.0
        net_recovery_rate = ((net_revenue - accumulated_storage_cost) / original_cost_basis * 100.0) if original_cost_basis > 0 else 0.0

        if sku_dto['quantity'] > 0 and (1.0 - cfg['marketing_cost_rate']) > 0:
            break_even_sale_price = total_sunk_cost / (sku_dto['quantity'] * (1.0 - cfg['marketing_cost_rate']))
        else:
            break_even_sale_price = float(sku_dto['selling_price'])

        if float(sku_dto['selling_price']) > 0:
            break_even_discount_pct = ((float(sku_dto['selling_price']) - break_even_sale_price) / float(sku_dto['selling_price'])) * 100.0
        else:
            break_even_discount_pct = 0.0
        break_even_discount_pct = min(100.0, max(0.0, break_even_discount_pct))

        quadrant = FinancialLiquidationEngine.classify_inventory_matrix(original_cost_basis, sku_dto['days_in_inventory'])

        write_off_loss = max(0.0, total_sunk_cost - expected_revenue)
        tax_shield_value = write_off_loss * cfg['tax_rate']
        is_tax_shield_recommended = (net_recovery_rate < 0) or (quadrant == "LOW_VALUE_OLD")

        # Build AI Recommendation
        if quadrant == "HIGH_VALUE_NEW":
            rec = "Hàng giá trị cao, vòng đời còn tốt. Ưu tiên Bundle cao cấp & phân phối kênh ngách. Tránh Flash Sale — sẽ phá vỡ định vị thương hiệu."
        elif quadrant == "HIGH_VALUE_OLD":
            rec = f"Hàng giá trị cao nhưng đã lâu ngày. Áp dụng giảm giá lũy tiến tối đa {break_even_discount_pct:.1f}% (ngưỡng hòa vốn). Hoặc tiếp cận kênh B2B Wholesale để bảo toàn margin."
        elif quadrant == "MID_VALUE_OLD":
            rec = f"Thực hiện Flash Sale với mức giảm không quá {break_even_discount_pct:.1f}% để giữ Net Recovery dương. Kết hợp Bundle với sản phẩm hot."
        elif quadrant == "LOW_VALUE_OLD":
            rec = f"Net Recovery ròng: {net_recovery_rate:.1f}%. Xả hàng không còn hiệu quả tài chính tối ưu. AI đề xuất: Quyên góp từ thiện hoặc Tiêu hủy để kích hoạt Lá chắn thuế ({accounting_method.upper()})."
        else:
            rec = "Tiếp tục theo dõi. Vòng đời tồn kho đang trong ngưỡng an toàn."

        return {
            "skuId": sku_dto['id'],
            "skuName": sku_dto['name'],
            "quantity": sku_dto['quantity'],
            "originalCostBasis": original_cost_basis,
            "accumulatedStorageCost": accumulated_storage_cost,
            "totalSunkCost": total_sunk_cost,
            "expectedRevenue": expected_revenue,
            "marketingAndShippingCost": marketing_cost,
            "grossRecoveryRate": round(gross_recovery_rate, 2),
            "netRecoveryRate": round(net_recovery_rate, 2),
            "breakEvenDiscountPct": round(break_even_discount_pct, 2),
            "taxShieldValueVnd": tax_shield_value,
            "matrixQuadrant": quadrant,
            "accountingMethod": accounting_method.upper(),
            "writeOffStrategy": FinancialLiquidationEngine.calculate_write_off_impact(accounting_method, original_cost_basis),
            "aiRecommendation": rec,
            "taxShieldRecommended": is_tax_shield_recommended
        }


# ─── Inventory Financial Engine Service ───
class InventoryFinancialEngineService:
    @staticmethod
    def calculate_aging_and_hidden_costs(user_id):
        # Raw query using django connection
        sql = """
            SELECT p._id, p.product_name, p.item_sku, p.stock, p.cost, p.price,
                   COALESCE(MAX(o.created_at), p.created_at) as last_date
            FROM products p
            LEFT JOIN order_items oi ON p.item_id = oi.item_id OR p.item_sku = oi.sku
            LEFT JOIN orders o ON oi.order_id = o._id
            WHERE p.user_id = %s 
              AND p.stock > 0
              AND (p.active_on_web IS NULL OR p.active_on_web = 1)
            GROUP BY p._id, p.product_name, p.item_sku, p.stock, p.cost, p.price, p.created_at
            ORDER BY (p.stock * COALESCE(p.cost, 0)) DESC
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [user_id])
            rows = cursor.fetchall()

        now = datetime.now()

        total_healthy = 0.0
        total_watchlist = 0.0
        total_slow_moving = 0.0
        total_dead_stock = 0.0

        healthy_skus = []
        watchlist_skus = []
        slow_moving_skus = []
        dead_stock_skus = []

        for row in rows:
            p_id, name, sku, stock, cost, price, last_date = row
            stock = int(stock or 0)
            cost = float(cost or 0.0)
            price = float(price or 0.0)
            total_value = cost * stock

            # Parse last date
            if last_date:
                if isinstance(last_date, str):
                    try:
                        last_date = datetime.strptime(last_date.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        last_date = now
                last_date_str = last_date.strftime('%Y-%m-%d')
            else:
                last_date = now
                last_date_str = "N/A"

            days_in_inventory = max(0, (now - last_date).days)

            # Classify
            playbook, playbook_key = IndustryDetectionService.detect(name)
            bucket = playbook.classify_aging_bucket(days_in_inventory)

            # Build industry context
            aging_score = playbook.calculate_aging_score(days_in_inventory)
            industry_ctx = {
                "industryCode": playbook_key,
                "displayName": playbook.display_name,
                "agingRiskMultiplier": playbook.aging_risk_multiplier,
                "maxShelfLifeDays": playbook.max_shelf_life_days,
                "liquidationStrategies": playbook.liquidation_strategies,
                "riskFactors": playbook.risk_factors,
                "agingScore": round(aging_score, 1),
                "isCritical": aging_score >= (playbook.max_shelf_life_days * playbook.aging_risk_multiplier)
            }

            sku_dto = {
                "id": p_id,
                "name": name,
                "sku": sku,
                "quantity": stock,
                "costPrice": cost,
                "sellingPrice": price,
                "totalValue": total_value,
                "lastRecordDate": last_date_str,
                "daysInInventory": days_in_inventory,
                "bucket": bucket,
                "industryContext": industry_ctx
            }

            if bucket == "HEALTHY":
                total_healthy += total_value
                healthy_skus.append(sku_dto)
            elif bucket == "WATCHLIST":
                total_watchlist += total_value
                watchlist_skus.append(sku_dto)
            elif bucket == "SLOW_MOVING":
                total_slow_moving += total_value
                slow_moving_skus.append(sku_dto)
            elif bucket == "DEAD_STOCK":
                total_dead_stock += total_value
                dead_stock_skus.append(sku_dto)

        total_frozen = total_slow_moving + total_dead_stock
        
        # Bleeding rates
        cfg = settings.SUPPLYFORGE['finance']
        monthly_storage_rate = cfg['storage_cost_yearly_rate'] / 12.0
        monthly_depreciation_rate = cfg['depreciation_cost_yearly_rate'] / 12.0
        
        storage_cost_monthly = total_frozen * monthly_storage_rate
        depreciation_cost_monthly = total_frozen * monthly_depreciation_rate
        total_bleeding_rate = storage_cost_monthly + depreciation_cost_monthly

        return {
            "totalHealthyValue": total_healthy,
            "totalWatchlistValue": total_watchlist,
            "totalSlowMovingValue": total_slow_moving,
            "totalDeadStockValue": total_dead_stock,
            "totalFrozenValue": total_frozen,
            "totalBleedingRateMonthly": total_bleeding_rate,
            "healthySkus": healthy_skus,
            "watchlistSkus": watchlist_skus,
            "slowMovingSkus": slow_moving_skus,
            "deadStockSkus": dead_stock_skus
        }


# ─── Inventory Insight Service (Dead Stock Analytics) ───
class InventoryInsightService:
    INSIGHT_TYPE = "DEAD_STOCK_SUMMARY"

    @staticmethod
    def get_dashboard_insights(user_id, refresh=False):
        now = datetime.now()

        if not refresh:
            # Check for recent valid insight snapshots
            latest_insight = InsightAnomaly.objects.filter(
                insight_type=InventoryInsightService.INSIGHT_TYPE,
                valid_until__gt=now
            ).order_by('-computed_at').first()
            if latest_insight and latest_insight.payload:
                return latest_insight.payload

        # Compute
        computed = InventoryInsightService.compute_dashboard_insights(user_id)
        
        # Save snapshot (valid for 1 hour)
        workspace = Workspace.objects.filter(slug='demo').first()
        if workspace:
            InsightAnomaly.objects.create(
                workspace=workspace,
                insight_type=InventoryInsightService.INSIGHT_TYPE,
                severity='CRITICAL',
                title="Tóm tắt tồn kho chết",
                summary="Snapshot cho dashboard — TTL 1 giờ",
                payload=computed,
                valid_until=now + timedelta(hours=1)
            )

        return computed

    @staticmethod
    def compute_dashboard_insights(user_id):
        # We find products matching dead stock criteria (no sales/changes > 45 days)
        # SELECT query matching Java SQL exactly
        dead_stock_sql = """
            SELECT p._id, p.product_name, p.item_sku, p.stock, p.cost, 
                   COALESCE(MAX(o.created_at), p.created_at) as last_date
            FROM products p
            LEFT JOIN order_items oi ON p.item_id = oi.item_id OR p.item_sku = oi.sku
            LEFT JOIN orders o ON oi.order_id = o._id AND o.created_at >= %s
            WHERE p.user_id = %s 
              AND p.stock > 0
              AND (p.active_on_web IS NULL OR p.active_on_web = 1)
            GROUP BY p._id, p.product_name, p.item_sku, p.stock, p.cost, p.created_at
            HAVING COALESCE(MAX(o.created_at), p.created_at) < %s
            ORDER BY (p.stock * COALESCE(p.cost, 0)) DESC
        """

        now = datetime.now()
        ninety_days_ago = now - timedelta(days=90)
        forty_five_days_ago = now - timedelta(days=45)

        with connection.cursor() as cursor:
            cursor.execute(dead_stock_sql, [ninety_days_ago, user_id, forty_five_days_ago])
            results = cursor.fetchall()

        total_frozen_value = 0.0
        stale_skus = []

        for row in results:
            p_id, name, sku, stock, cost, last_date = row
            stock = int(stock or 0)
            cost = float(cost or 0.0)
            frozen_value = cost * stock
            total_frozen_value += frozen_value

            if last_date:
                if isinstance(last_date, str):
                    last_date_str = last_date.split(" ")[0]
                else:
                    last_date_str = last_date.strftime('%Y-%m-%d')
            else:
                last_date_str = "N/A"

            stale_skus.append({
                "skuId": p_id,
                "name": name,
                "frozenValueVnd": frozen_value,
                "lastRecordDate": last_date_str
            })

        top_stale = stale_skus[:5]

        # Total Inventory Value
        total_inv = Product.objects.filter(user_id=user_id).aggregate(
            val=Sum(models.F('stock') * models.F('cost'))
        )['val'] or 0.0

        # Total root SKU count
        total_skus = Product.objects.filter(user_id=user_id).count()

        return {
            "totalDeadStockValueVnd": total_frozen_value,
            "estimatedLoss30DaysVnd": total_frozen_value * 0.05,
            "totalInventoryValueVnd": float(total_inv),
            "staleSkuCount": len(stale_skus),
            "totalRootSkuCount": total_skus,
            "topStaleSkus": top_stale
        }


# ─── Portfolio Orchestration Service ───
class PortfolioOrchestrationService:
    MAX_CLUSTERS = 3
    PHASE_DISCOUNT_DEAD = 0.70
    PHASE_DISCOUNT_SLOW = 0.35
    PHASE_DISCOUNT_WATCH = 0.15

    W_FROZEN_VALUE = 0.30
    W_AGING_DAYS = 0.25
    W_SELL_THRU = 0.20
    W_INDUSTRY_RISK = 0.25

    MAX_DAYS_SCALE = 365.0
    MAX_VALUE_SCALE = 500000000.0

    @staticmethod
    def build_command_plan(user_id):
        # Fetching products
        sql = """
            SELECT p._id, p.product_name, p.item_sku, p.stock, p.cost, p.price,
                   COALESCE(MAX(o.created_at), p.created_at) as last_date
            FROM products p
            LEFT JOIN order_items oi ON p.item_id = oi.item_id OR p.item_sku = oi.sku
            LEFT JOIN orders o ON oi.order_id = o._id
            WHERE p.user_id = %s
              AND p.stock > 0
              AND (p.active_on_web IS NULL OR p.active_on_web = 1)
            GROUP BY p._id, p.product_name, p.item_sku, p.stock, p.cost, p.price, p.created_at
            ORDER BY (p.stock * COALESCE(p.cost, 0)) DESC
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [user_id])
            rows = cursor.fetchall()

        now = datetime.now()
        raw_rows = []
        global_max_value = 1.0

        for row in rows:
            p_id, name, sku, stock, cost, price, last_date = row
            stock = int(stock or 0)
            cost = float(cost or 0.0)
            price = float(price or 0.0)
            total_value = cost * stock

            if last_date:
                if isinstance(last_date, str):
                    try:
                        last_date = datetime.strptime(last_date.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        last_date = now
            else:
                last_date = now

            days = max(0, (now - last_date).days)
            raw_rows.append({
                "id": p_id, "name": name, "sku": sku, "stock": stock,
                "cost": cost, "price": price, "days": days, "total_value": total_value
            })
            if total_value > global_max_value:
                global_max_value = total_value

        scored_skus = []
        for r in raw_rows:
            playbook, playbook_key = IndustryDetectionService.detect(r['name'])
            bucket = playbook.classify_aging_bucket(r['days'])

            # Only SLOW_MOVING and DEAD_STOCK
            if bucket in ["HEALTHY", "WATCHLIST"]:
                continue

            # Compute risk score
            norm_val = min(1.0, r['total_value'] / global_max_value)
            norm_days = min(1.0, r['days'] / PortfolioOrchestrationService.MAX_DAYS_SCALE)
            sell_thru = 1.0 if bucket == "DEAD_STOCK" else 0.6
            
            # Risk factor normalize
            multiplier = playbook.aging_risk_multiplier
            industry_risk = min(1.0, (multiplier - 1.0) / 1.5)

            score = (
                PortfolioOrchestrationService.W_FROZEN_VALUE * norm_val +
                PortfolioOrchestrationService.W_AGING_DAYS * norm_days +
                PortfolioOrchestrationService.W_SELL_THRU * sell_thru +
                PortfolioOrchestrationService.W_INDUSTRY_RISK * industry_risk
            )
            score = round(score * 100.0, 1)

            scored_skus.append({
                "row": r, "playbook_key": playbook_key, "playbook": playbook,
                "bucket": bucket, "risk_score": score
            })

        if not scored_skus:
            return {
                "priorityClusters": [],
                "totalExpectedRecovery": 0.0,
                "totalSkuCount": 0,
                "estimatedWarehouseSpaceFreedPct": 0.0,
                "planHorizonDays": 0
            }

        # Cluster by Industry & Urgency Tier
        def urgency_tier(score):
            if score >= 70: return "CRITICAL"
            if score >= 45: return "HIGH"
            return "MEDIUM"

        clusters_map = {}
        for s in scored_skus:
            tier = urgency_tier(s['risk_score'])
            key = f"{s['playbook_key']}_{tier}"
            if key not in clusters_map:
                clusters_map[key] = []
            clusters_map[key].append(s)

        # Build DTOs
        cluster_dtos = []
        for key, skus in clusters_map.items():
            parts = key.split("_")
            # Handling FASHION_FAST_CRITICAL
            if len(parts) == 3:
                ind_code = f"{parts[0]}_{parts[1]}"
                tier = parts[2]
            else:
                ind_code = parts[0]
                tier = parts[1]

            # Strategy / Action selection
            action = ""
            if tier == "CRITICAL":
                action = {
                    "FASHION_FAST": "Flash Sale TikTok −70% + KOL Seeding",
                    "ELECTRONICS_TECH": "B2B Wholesale Bulk Deal −50@",
                    "FMCG_FOOD": "Clearance Flash Deal Lazada −70%",
                    "HOME_LIVING": "Showroom Display Clearance −60%",
                    "GENERAL": "Batch Clearance Sale −70%"
                }.get(ind_code, "Batch Clearance Sale −70%")
            elif tier == "HIGH":
                action = {
                    "FASHION_FAST": "Flash Sale Shopee −35% + Cross-season Bundle",
                    "ELECTRONICS_TECH": "Trade-in Upgrade Campaign −35%",
                    "FMCG_FOOD": "Multi-buy Deal −30% FMCG Bundle",
                    "HOME_LIVING": "Room Package Bundle −35%",
                    "GENERAL": "Promotional Campaign −35%"
                }.get(ind_code, "Promotional Campaign −35%")
            else:
                action = {
                    "FASHION_FAST": "Seasonal Promotion −15%",
                    "ELECTRONICS_TECH": "Loyalty Member Deal −15%",
                    "FMCG_FOOD": "Buy-more-save-more −15%",
                    "HOME_LIVING": "Home Refresh Promo −15%",
                    "GENERAL": "Early Bird Discount −15%"
                }.get(ind_code, "Early Bird Discount −15%")

            # Names & Rationales
            labels = {
                "FASHION_FAST": "Thời trang",
                "ELECTRONICS_TECH": "Điện tử & Công nghệ",
                "FMCG_FOOD": "Thực phẩm & FMCG",
                "HOME_LIVING": "Nội thất & Gia dụng",
                "GENERAL": "Tổng hợp"
            }
            ind_label = labels.get(ind_code, "Tổng hợp")
            tier_label = {"CRITICAL": "— Thanh lý khẩn cấp", "HIGH": "— Xả hàng cắt máu"}.get(tier, "— Khuyến mãi kích cầu")
            cluster_name = f"{ind_label} {tier_label}"

            reasons = {
                "FASHION_FAST": "đang lỗi mùa vụ",
                "ELECTRONICS_TECH": "đối diện rủi ro model mới",
                "FMCG_FOOD": "cận hạn sử dụng",
                "HOME_LIVING": "chi phí lưu kho cao",
                "GENERAL": "tồn kho bất thường"
            }
            rationale = f"{len(skus)} SKU {reasons.get(ind_code, 'tồn kho bất thường')} — Nhóm vào chiến dịch duy nhất để thực thi hàng loạt."

            total_frozen = sum(s['row']['total_value'] for s in skus)
            discount_rate = {"CRITICAL": PortfolioOrchestrationService.PHASE_DISCOUNT_DEAD, "HIGH": PortfolioOrchestrationService.PHASE_DISCOUNT_SLOW}.get(tier, PortfolioOrchestrationService.PHASE_DISCOUNT_WATCH)
            recoverable = total_frozen * (1.0 - discount_rate)
            avg_risk = round(sum(s['risk_score'] for s in skus) / len(skus), 1)

            # Sort top 3 skus
            skus_sorted = sorted(skus, key=lambda s: s['risk_score'], reverse=True)[:3]
            samples = [{
                "name": s['row']['name'],
                "daysInInventory": s['row']['days'],
                "frozenValueVnd": s['row']['total_value'],
                "riskScore": s['risk_score']
            } for s in skus_sorted]

            cluster_dtos.append({
                "clusterId": key,
                "industryCode": ind_code,
                "urgencyLevel": tier,
                "clusterName": cluster_name,
                "rationale": rationale,
                "skuCount": len(skus),
                "totalFrozenValue": total_frozen,
                "totalPotentialRecovery": recoverable,
                "averageRiskScore": avg_risk,
                "recommendedBatchAction": action,
                "estimatedClearDays": 7 if tier == "CRITICAL" else (14 if tier == "HIGH" else 30),
                "topSkuSamples": samples
            })

        # Sort and limit to top 3 clusters
        cluster_dtos = sorted(cluster_dtos, key=lambda c: c['averageRiskScore'], reverse=True)[:PortfolioOrchestrationService.MAX_CLUSTERS]

        total_rec = sum(c['totalPotentialRecovery'] for c in cluster_dtos)
        total_skus_count = sum(c['skuCount'] for c in cluster_dtos)
        
        portfolio_frozen = sum(s['row']['total_value'] for s in scored_skus)
        cluster_frozen = sum(c['totalFrozenValue'] for c in cluster_dtos)
        space_pct = round((cluster_frozen / portfolio_frozen * 100.0), 1) if portfolio_frozen > 0 else 0.0
        
        horizon = max((c['estimatedClearDays'] for c in cluster_dtos), default=14)

        return {
            "priorityClusters": cluster_dtos,
            "totalExpectedRecovery": total_rec,
            "totalSkuCount": total_skus_count,
            "estimatedWarehouseSpaceFreedPct": space_pct,
            "planHorizonDays": horizon
        }


# ─── Sku Normalization Service ───
class SkuNormalizationService:
    @staticmethod
    def find_duplicate_candidates(user_id):
        products = list(Product.objects.filter(user_id=user_id, active_on_web=True))
        groups = []
        visited = [False] * len(products)

        for i in range(len(products)):
            if visited[i]:
                continue
            group = [products[i]]
            visited[i] = True

            for j in range(i + 1, len(products)):
                if visited[j]:
                    continue
                if is_similar(products[i], products[j]):
                    group.append(products[j])
                    visited[j] = True

            if len(group) > 1:
                groups.append(group)

        return groups

    @staticmethod
    @transaction.atomic
    def merge_products(parent_id, child_ids):
        try:
            parent = Product.objects.get(id=parent_id)
        except Product.DoesNotExist:
            raise ValueError("Parent product not found")

        children = Product.objects.filter(id__in=child_ids)

        parent_stock = parent.stock or 0
        parent_cost = Decimal(str(parent.cost or 0.0))
        total_stock = parent_stock
        total_value = parent_cost * parent_stock

        for child in children:
            child_stock = child.stock or 0
            child_cost = Decimal(str(child.cost or 0.0))

            total_stock += child_stock
            total_value += child_cost * child_stock

            child.active_on_web = False
            child.save()

        parent.stock = total_stock
        if total_stock > 0:
            parent.cost = total_value / Decimal(total_stock)
        else:
            if not parent.cost and children.exists() and children.first().cost:
                parent.cost = children.first().cost

        parent.save()


def is_similar(a, b):
    # Match item_sku
    if a.item_sku and b.item_sku and a.item_sku.strip().lower() == b.item_sku.strip().lower():
        return True
    
    # Match product name similarity
    if a.product_name and b.product_name:
        name_a = VietnameseNormalizer.strip_accents(a.product_name.strip().lower())
        name_b = VietnameseNormalizer.strip_accents(b.product_name.strip().lower())
        
        dist = Levenshtein.distance(name_a, name_b)
        max_len = max(len(name_a), len(name_b), 1)
        similarity = 1.0 - (dist / max_len)

        return similarity >= 0.65 or (name_b in name_a) or (name_a in name_b)

    return False


# ─── Dynamic File Import Service ───
class DynamicFileImportService:
    @staticmethod
    def parse_csv_line(line):
        # Splitting on comma outside of quotes (Golly, regex is clean!)
        tokens = re.split(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', line)
        result = []
        for token in tokens:
            cleaned = re.sub(r'^"|"$', '', token).strip()
            result.append(cleaned)
        return result

    @staticmethod
    def peek_sample_data(file_obj):
        headers = []
        sample_rows = []
        count = 0
        
        for line_bytes in file_obj:
            line = line_bytes.decode('utf-8')
            if not headers:
                headers = DynamicFileImportService.parse_csv_line(line)
            else:
                sample_rows.append(DynamicFileImportService.parse_csv_line(line))
                count += 1
                if count >= 5:
                    break
        return headers, sample_rows

    @staticmethod
    @transaction.atomic
    def process_batch_import(file_obj, mapping_rule, user_id):
        # Read file lines
        lines = [line.decode('utf-8') for line in file_obj]
        if not lines:
            return

        headers = DynamicFileImportService.parse_csv_line(lines[0])
        
        # Build index mapping
        index_map = {}
        for db_field, csv_header in mapping_rule.items():
            if csv_header in headers:
                index_map[db_field] = headers.index(csv_header)

        batch = []
        import_time = int(datetime.now().timestamp() * 1000)

        for line in lines[1:]:
            if not line.strip():
                continue
            row = DynamicFileImportService.parse_csv_line(line)
            if not row:
                continue

            def get_val(field):
                idx = index_map.get(field)
                if idx is not None and idx < len(row):
                    return row[idx]
                return None

            product_name = get_val("productName") or "Unknown"
            item_sku = get_val("itemSku") or ""
            price_str = get_val("price")
            cost_str = get_val("cost")
            stock_str = get_val("stock") or get_val("quantity")
            date_str = get_val("orderDate")

            # Parse numbers
            def parse_decimal(s):
                if not s: return Decimal('0.00')
                try:
                    return Decimal(re.sub(r'[^0-9.]', '', s))
                except Exception:
                    return Decimal('0.00')

            def parse_int(s):
                if not s: return 0
                try:
                    return int(re.sub(r'[^0-9]', '', s))
                except Exception:
                    return 0

            price = parse_decimal(price_str)
            cost = parse_decimal(cost_str)
            stock = parse_int(stock_str)

            # Parse date
            created_at = None
            if date_str:
                date_clean = date_str.strip()
                try:
                    if "/" in date_clean:
                        created_at = datetime.strptime(date_clean, "%d/%m/%Y")
                    else:
                        created_at = datetime.strptime(date_clean, "%Y-%m-%d")
                except Exception:
                    pass

            if not created_at:
                # Randomize 0 to 90 days ago fallback
                import random
                created_at = datetime.now() - timedelta(days=random.randint(0, 90))

            prod_id = uuid.uuid4().hex[:24]
            product = Product(
                id=prod_id,
                user_id=user_id,
                product_name=product_name,
                item_sku=item_sku,
                price=price,
                cost=cost,
                stock=stock,
                third_party_id=f"csv_import_{import_time}",
                created_at=created_at,
                updated_at=datetime.now(),
                active_on_web=True
            )
            batch.append(product)

            # Flush standard batches
            if len(batch) >= 1000:
                Product.objects.bulk_create(batch)
                batch = []

        if batch:
            Product.objects.bulk_create(batch)

    @staticmethod
    @transaction.atomic
    def clear_data(user_id):
        # Delete order items, orders, products
        OrderItem.objects.filter(order__user_id=user_id).delete()
        Order.objects.filter(user_id=user_id).delete()
        Product.objects.filter(user_id=user_id).delete()
