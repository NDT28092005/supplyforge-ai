import re
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.conf import settings
from django.db import connection, transaction, models
from django.db.models import Sum
from core.models import Product, Order, OrderItem, InsightAnomaly, Workspace
from core.features.sku_tinder.services import VietnameseNormalizer

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
        (re.compile(r"\b(sữa|sua|bột|bot|thực phẩm|thuc pham|ăn|uống|an uong|đồ ăn|do an|bánh|banh|kẹo|keo|nước|nuoc|đồ uống|do uong|vitamin|supplement|snack|mì|mi|gạo|gao|dầu ăn|dau an|gia vị|gia vi|sốt|sot|yogurt|fmcg|date|hsd|han su dung)\b", re.IGNORECASE), 'FMCG_FOOD'),
        (re.compile(r"\b(áo|ao|quần|quan|váy|vay|đầm|dam|đồ|do|size|xl|xxl|m|l|s|shirt|dress|pants|skirt|jacket|coat|jeans|hoodie|sweater|blouse|suit|phong cách|thời trang|thoi trang|mùa|mua|xuân|xuan|hè|he|thu|đông|dong|fashion|wear|outfit|sandal|dép|dep|giày|giay|túi|tui|ví|vi|balo|mũ|mu|nón|non)\b", re.IGNORECASE), 'FASHION_FAST'),
        (re.compile(r"\b(iphone|samsung|laptop|macbook|dell|lenovo|asus|hp|máy tính|may tinh|điện thoại|dien thoai|tai nghe|headphone|earphone|airpod|speaker|loa|chuột|chuot|bàn phím|ban phim|keyboard|mouse|monitor|màn hình|man hinh|ssd|hdd|ram|cpu|gpu|card|chip|usb|hub|cable|cáp|cap|router|modem|wifi|gaming|game|controller|console|playstation|xbox|nintendo|camera|máy ảnh|may anh|lens|ống kính|ong kinh|drone|smartwatch|tablet|ipad|android|ios|tech|gb|tb|mhz|ghz|4k|8k)\b", re.IGNORECASE), 'ELECTRONICS_TECH'),
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


class InventoryFinancialEngineService:
    @staticmethod
    def calculate_aging_and_hidden_costs(user_id):
        # F&B Auto-removal and near expiration warnings
        today_date = date.today()
        # 1. Auto-deactivate expired items
        expired_count = Product.objects.filter(user_id=user_id, expiration_date__lt=today_date, active_on_web=True).update(active_on_web=False)

        # 2. Near expiration warning list (next 15 days)
        near_expiry_query = Product.objects.filter(
            user_id=user_id, 
            expiration_date__gte=today_date, 
            expiration_date__lte=today_date + timedelta(days=15),
            active_on_web=True
        )
        near_expiry_list = [{
            "id": p.id,
            "name": p.product_name,
            "sku": p.item_sku or p.id,
            "stock": p.stock or 0,
            "expirationDate": p.expiration_date.strftime('%Y-%m-%d'),
            "daysLeft": (p.expiration_date - today_date).days
        } for p in near_expiry_query]

        # Fetch products matching standard query
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
        ninety_days_ago = now - timedelta(days=90)

        # Calculate unit velocities (Simple, Weighted, Seasonally Adjusted)
        # Fix: Explicit Timeframe windows (7d, 30d, 60d) so Weighted Velocity captures recent sales signals
        velocity_sql = """
            SELECT p._id,
                   SUM(CASE WHEN o.created_at >= %s THEN oi.quantity ELSE 0 END) as sold_7d,
                   SUM(CASE WHEN o.created_at >= %s THEN oi.quantity ELSE 0 END) as sold_30d,
                   SUM(CASE WHEN o.created_at >= %s THEN oi.quantity ELSE 0 END) as sold_60d
            FROM products p
            LEFT JOIN order_items oi ON p.item_id = oi.item_id OR p.item_sku = oi.sku
            LEFT JOIN orders o ON oi.order_id = o._id
            WHERE p.user_id = %s
            GROUP BY p._id
        """
        with connection.cursor() as cursor:
            cursor.execute(velocity_sql, [
                now - timedelta(days=7),
                now - timedelta(days=30),
                now - timedelta(days=60),
                user_id
            ])
            velocity_rows = cursor.fetchall()

        velocities = {}
        for vr in velocity_rows:
            p_id, s7, s30, s60 = vr
            s7 = float(s7 or 0)
            s30 = float(s30 or 0)
            s60 = float(s60 or 0)

            # Simple velocity (past 30 days daily average)
            simple_vel = s30 / 30.0

            # Weighted velocity (Recent signals capture: 50% for 7d velocity, 30% for 30d velocity, 20% for 60d velocity)
            vel_7d = s7 / 7.0
            vel_30d = s30 / 30.0
            vel_60d = s60 / 60.0
            weighted_vel = (vel_7d * 0.5) + (vel_30d * 0.3) + (vel_60d * 0.2)

            # Seasonally Adjusted velocity (Mock seasonal summer Q2 multiplier: 1.15)
            seasonal_vel = weighted_vel * 1.15

            velocities[p_id] = {
                "simple": round(simple_vel, 2),
                "weighted": round(weighted_vel, 2),
                "seasonal": round(seasonal_vel, 2)
            }

        total_healthy = 0.0
        total_watchlist = 0.0
        total_slow_moving = 0.0
        total_dead_stock = 0.0
        total_accumulated_sunk_cost = 0.0

        healthy_skus = []
        watchlist_skus = []
        slow_moving_skus = []
        dead_stock_skus = []

        cfg = settings.SUPPLYFORGE['finance']
        yearly_storage_rate = cfg.get('storage_cost_yearly_rate', 0.25)
        daily_storage_rate = yearly_storage_rate / 365.0

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
                last_date_str = last_date.strftime('%Y-%m-%d')
            else:
                last_date = now
                last_date_str = "N/A"

            days_in_inventory = max(0, (now - last_date).days)

            # Calculate actual Accumulated Sunk Cost for each SKU line based on actual age
            sku_sunk_cost = total_value * daily_storage_rate * days_in_inventory
            total_accumulated_sunk_cost += sku_sunk_cost

            playbook, playbook_key = IndustryDetectionService.detect(name)
            bucket = playbook.classify_aging_bucket(days_in_inventory)
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
                "accumulatedSunkCost": round(sku_sunk_cost, 2),
                "lastRecordDate": last_date_str,
                "daysInInventory": days_in_inventory,
                "bucket": bucket,
                "industryContext": industry_ctx,
                "velocities": velocities.get(p_id, {"simple": 0.0, "weighted": 0.0, "seasonal": 0.0})
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
        
        # ─── Financial Leak Indicators ───
        # COGS and Sales in past 90 days for Turnover Rate and DSO calculations
        with connection.cursor() as cursor:
            # 1. Total COGS
            cursor.execute("""
                SELECT SUM(oi.quantity * COALESCE(oi.cost, 0))
                FROM order_items oi
                JOIN orders o ON oi.order_id = o._id
                WHERE o.user_id = %s AND o.created_at >= %s
            """, [user_id, ninety_days_ago])
            cogs_val = cursor.fetchone()[0] or 0.0

            # 2. Total sales
            cursor.execute("""
                SELECT SUM(amount)
                FROM orders
                WHERE user_id = %s AND created_at >= %s AND (cancelled_after_packaged IS NULL OR cancelled_after_packaged = 0)
            """, [user_id, ninety_days_ago])
            sales_val = cursor.fetchone()[0] or 0.0

        # Annualized Inventory Turnover Rate
        total_inv_val = total_healthy + total_watchlist + total_slow_moving + total_dead_stock
        cogs_annualized = float(cogs_val) * 4.0
        turnover_rate = (cogs_annualized / total_inv_val) if total_inv_val > 0 else 0.0

        # DSO (Days Sales Outstanding / Days Sales of Inventory)
        # DSS logic: DSO = (Tồn kho / Doanh số trung bình). If total_sales == 0, catch division by zero error -> display infinity "∞" or ">999"
        total_sales = float(sales_val)
        if total_sales > 0:
            calc_dso = (total_inv_val / total_sales) * 90.0
            dso = ">999" if calc_dso > 999 else round(calc_dso, 1)
        else:
            dso = "∞"

        # Holding costs & Opportunity costs
        monthly_storage_rate = cfg['storage_cost_yearly_rate'] / 12.0
        monthly_depreciation_rate = cfg['depreciation_cost_yearly_rate'] / 12.0
        # Opportunity cost: 10% annual rate chôn vốn / 12
        monthly_opportunity_rate = 0.10 / 12.0

        storage_cost_monthly = total_frozen * monthly_storage_rate
        depreciation_cost_monthly = total_frozen * monthly_depreciation_rate
        opportunity_cost_monthly = total_frozen * monthly_opportunity_rate
        total_bleeding_rate = storage_cost_monthly + depreciation_cost_monthly + opportunity_cost_monthly

        return {
            "totalHealthyValue": total_healthy,
            "totalWatchlistValue": total_watchlist,
            "totalSlowMovingValue": total_slow_moving,
            "totalDeadStockValue": total_dead_stock,
            "totalFrozenValue": total_frozen,
            "totalBleedingRateMonthly": total_bleeding_rate,
            "turnoverRate": round(turnover_rate, 2),
            "dso": dso,
            "accumulatedSunkCost": round(total_accumulated_sunk_cost, 2),
            "storageCostMonthly": storage_cost_monthly,
            "depreciationCostMonthly": depreciation_cost_monthly,
            "opportunityCostMonthly": opportunity_cost_monthly,
            "expiredDeactivatedCount": expired_count,
            "nearExpiryWarnings": near_expiry_list,
            "healthySkus": healthy_skus,
            "watchlistSkus": watchlist_skus,
            "slowMovingSkus": slow_moving_skus,
            "deadStockSkus": dead_stock_skus
        }


class InventoryInsightService:
    INSIGHT_TYPE = "DEAD_STOCK_SUMMARY"

    @staticmethod
    def get_dashboard_insights(user_id, refresh=False):
        now = datetime.now()

        if not refresh:
            latest_insight = InsightAnomaly.objects.filter(
                insight_type=InventoryInsightService.INSIGHT_TYPE,
                valid_until__gt=now
            ).order_by('-computed_at').first()
            if latest_insight and latest_insight.payload:
                return latest_insight.payload

        computed = InventoryInsightService.compute_dashboard_insights(user_id)
        
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

        total_inv = Product.objects.filter(user_id=user_id, active_on_web=True).aggregate(
            val=Sum(models.F('stock') * models.F('cost'))
        )['val'] or 0.0

        total_skus = Product.objects.filter(user_id=user_id, active_on_web=True).count()

        return {
            "totalDeadStockValueVnd": total_frozen_value,
            "estimatedLoss30DaysVnd": total_frozen_value * 0.05,
            "totalInventoryValueVnd": float(total_inv),
            "staleSkuCount": len(stale_skus),
            "totalRootSkuCount": total_skus,
            "topStaleSkus": top_stale
        }
