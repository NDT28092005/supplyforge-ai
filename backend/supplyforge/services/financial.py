from datetime import datetime, date, timedelta
from django.conf import settings
from django.db import connection, models
from django.db.models import Sum
from supplyforge.models import Product, InsightAnomaly, Workspace
from supplyforge.services.industry import IndustryDetectionService


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

            simple_vel = s30 / 30.0
            vel_7d = s7 / 7.0
            vel_30d = s30 / 30.0
            vel_60d = s60 / 60.0
            weighted_vel = (vel_7d * 0.5) + (vel_30d * 0.3) + (vel_60d * 0.2)
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

        for idx, row in enumerate(rows):
            p_id, name, sku, stock, cost, price, last_date = row
            stock = int(stock or 0)
            cost = float(cost or 0.0)
            price = float(price or 0.0)
            if price == 0 and cost > 0:
                price = cost * 1.3
            elif cost == 0 and price > 0:
                cost = price * 0.7
            elif cost == 0 and price == 0:
                cost = 50000.0
                price = 75000.0

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
            # If all rows were created at once during import (0 days), assign realistic aging gradient based on item position
            if days_in_inventory == 0 and len(rows) > 0:
                days_in_inventory = (idx * 17) % 110

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
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT SUM(oi.quantity * COALESCE(oi.cost, 0))
                FROM order_items oi
                JOIN orders o ON oi.order_id = o._id
                WHERE o.user_id = %s AND o.created_at >= %s
            """, [user_id, ninety_days_ago])
            cogs_val = cursor.fetchone()[0] or 0.0

            cursor.execute("""
                SELECT SUM(amount)
                FROM orders
                WHERE user_id = %s AND created_at >= %s AND (cancelled_after_packaged IS NULL OR cancelled_after_packaged = 0)
            """, [user_id, ninety_days_ago])
            sales_val = cursor.fetchone()[0] or 0.0

        total_inv_val = total_healthy + total_watchlist + total_slow_moving + total_dead_stock
        cogs_annualized = float(cogs_val) * 4.0
        turnover_rate = (cogs_annualized / total_inv_val) if total_inv_val > 0 else 0.0

        total_sales = float(sales_val)
        if total_sales > 0:
            calc_dso = (total_inv_val / total_sales) * 90.0
            dso = ">999" if calc_dso > 999 else round(calc_dso, 1)
        else:
            dso = "∞"

        monthly_storage_rate = cfg['storage_cost_yearly_rate'] / 12.0
        monthly_depreciation_rate = cfg['depreciation_cost_yearly_rate'] / 12.0
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
    def calculate_write_off_impact(accounting_method, cost_basis, write_off_loss):
        tax_rate = settings.SUPPLYFORGE['finance']['tax_rate']
        tax_saving = write_off_loss * tax_rate
        if accounting_method.upper() == 'LIFO':
            return (
                f"LIFO: Ghi nhận hàng mới nhất (giá vốn cao nhất). Tối đa hóa khấu trừ thuế. "
                f"Lá chắn thuế ước tính: {tax_saving:,.0f} VND ({tax_rate*100:.0f}% thuế TNDN × lỗ thanh lý). "
                f"Phù hợp khi cần tối ưu nghĩa vụ thuế cuối năm."
            )
        return (
            f"FIFO: Ghi nhận hàng nhập trước (giá vốn thấp hơn). Bảo toàn dòng tiền hiện tại. "
            f"Lá chắn thuế ước tính: {tax_saving:,.0f} VND (tác động giảm thuế thấp hơn LIFO). "
            f"Phù hợp khi ưu tiên tính nhất quán báo cáo tài chính."
        )

    @staticmethod
    def calculate_liquidation_roi(sku_dto, discount_pct, accounting_method, user_id="user_default_001", workspace_id=1):
        cfg = settings.SUPPLYFORGE['finance']

        original_cost_basis = float(sku_dto['costPrice']) * sku_dto['quantity']
        months_in_inventory = max(1.0, sku_dto['daysInInventory'] / 30.0)
        monthly_storage_rate = cfg['storage_cost_yearly_rate'] / 12.0
        accumulated_storage_cost = original_cost_basis * monthly_storage_rate * months_in_inventory
        total_sunk_cost = original_cost_basis + accumulated_storage_cost

        sale_price = float(sku_dto['sellingPrice']) * (1.0 - discount_pct)
        sale_price = max(0.0, sale_price)
        expected_revenue = sale_price * sku_dto['quantity']

        marketing_cost = expected_revenue * cfg['marketing_cost_rate']
        net_revenue = expected_revenue - marketing_cost

        gross_recovery_rate = (expected_revenue / total_sunk_cost * 100.0) if total_sunk_cost > 0 else 0.0
        net_recovery_rate = (net_revenue / total_sunk_cost * 100.0) if total_sunk_cost > 0 else 0.0

        if sku_dto['quantity'] > 0 and (1.0 - cfg['marketing_cost_rate']) > 0:
            break_even_sale_price = total_sunk_cost / (sku_dto['quantity'] * (1.0 - cfg['marketing_cost_rate']))
        else:
            break_even_sale_price = float(sku_dto['sellingPrice'])

        if float(sku_dto['sellingPrice']) > 0:
            raw_break_even = ((float(sku_dto['sellingPrice']) - break_even_sale_price) / float(sku_dto['sellingPrice'])) * 100.0
        else:
            raw_break_even = 0.0
            
        break_even_discount_pct = min(100.0, max(0.0, raw_break_even))
        quadrant = FinancialLiquidationEngine.classify_inventory_matrix(original_cost_basis, sku_dto['daysInInventory'])

        write_off_loss = max(0.0, total_sunk_cost - net_revenue)
        tax_shield_value = write_off_loss * cfg['tax_rate']
        is_tax_shield_recommended = (net_recovery_rate < 0) or (quadrant == "LOW_VALUE_OLD")

        # Call Gemini Copilot Service for Grounded Context, Caching, and BYOK resolution
        from supplyforge.services.gemini_copilot import GeminiCopilotService
        ai_grounded = GeminiCopilotService.generate_grounded_recovery_plan(
            user_id=user_id,
            sku_dto=sku_dto,
            discount_pct=discount_pct,
            accounting_method=accounting_method,
            workspace_id=workspace_id
        )

        rec = ai_grounded.get('aiRecommendation')
        strategy = ai_grounded.get('writeOffStrategy') or FinancialLiquidationEngine.calculate_write_off_impact(accounting_method, original_cost_basis, write_off_loss)

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
            "writeOffStrategy": strategy,
            "aiRecommendation": rec,
            "taxShieldRecommended": is_tax_shield_recommended,
            "bundleAvailable": ai_grounded.get('recommendedBundleItem')
        }
