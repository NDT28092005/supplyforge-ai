import re
from decimal import Decimal
from datetime import datetime, timedelta
from django.conf import settings
from django.db import connection
from core.models import Product, Sku, Workspace, InsightAnomaly
from core.features.recovery_copilot.gemini_service import GeminiCopilotService
from core.features.leak_detector.services import IndustryDetectionService

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

        # Entity Resolution: Deduplicate SKUs
        import difflib
        deduped_rows = []
        raw_rows.sort(key=lambda x: x['total_value'], reverse=True)
        for r in raw_rows:
            is_dup = False
            r_name_lower = r['name'].lower()
            r_words = set(re.findall(r'[a-z0-9]+', r_name_lower))
            
            for d in deduped_rows:
                if r['sku'] and d['sku'] and r['sku'] == d['sku']:
                    is_dup = True
                    break
                
                similarity = difflib.SequenceMatcher(None, r_name_lower, d['name'].lower()).ratio()
                if similarity > 0.8:
                    is_dup = True
                    break
                
                d_words = set(re.findall(r'[a-z0-9]+', d['name'].lower()))
                intersect = r_words.intersection(d_words)
                model_numbers = [w for w in intersect if any(c.isalpha() for c in w) and any(c.isdigit() for c in w)]
                if len(model_numbers) > 0 and len(intersect) >= 2:
                    is_dup = True
                    break
            
            if not is_dup:
                deduped_rows.append(r)
        
        raw_rows = deduped_rows

        scored_skus = []
        for r in raw_rows:
            playbook, playbook_key = IndustryDetectionService.detect(r['name'])
            bucket = playbook.classify_aging_bucket(r['days'])

            if bucket in ["HEALTHY", "WATCHLIST"]:
                continue

            norm_val = min(1.0, r['total_value'] / global_max_value)
            norm_days = min(1.0, r['days'] / PortfolioOrchestrationService.MAX_DAYS_SCALE)
            sell_thru = 1.0 if bucket == "DEAD_STOCK" else 0.6
            
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

        cluster_dtos = []
        for key, skus in clusters_map.items():
            parts = key.split("_")
            if len(parts) == 3:
                ind_code = f"{parts[0]}_{parts[1]}"
                tier = parts[2]
            else:
                ind_code = parts[0]
                tier = parts[1]

            # Calculate Decision Matrix & Break-Even Logic
            total_cost_basis = sum(s['row']['cost'] * s['row']['stock'] for s in skus)
            cluster_sunk_cost = total_cost_basis * 1.05  # Approximate 5% accumulated storage
            total_retail = sum(s['row']['price'] * s['row']['stock'] for s in skus)
            
            if total_retail > 0:
                cluster_break_even_pct = max(0.0, (total_retail - cluster_sunk_cost) / total_retail * 100.0)
            else:
                cluster_break_even_pct = 0.0

            action = ""
            if tier == "CRITICAL":
                suggested_discount = 70.0
                if cluster_break_even_pct < suggested_discount:
                    action = f"Thanh lý cắt lỗ sâu −{suggested_discount}% (Chấp nhận hy sinh {suggested_discount - cluster_break_even_pct:.1f}% Margin)"
                else:
                    action = f"Batch Clearance Sale −{suggested_discount}%"
            elif tier == "HIGH":
                suggested_discount = 35.0
                if cluster_break_even_pct < suggested_discount:
                    action = f"Xả hàng −{suggested_discount}% (Cảnh báo: Vượt ngưỡng hòa vốn {cluster_break_even_pct:.1f}%)"
                else:
                    action = f"Promotional Campaign −{suggested_discount}%"
            else:
                suggested_discount = 15.0
                if cluster_break_even_pct < suggested_discount:
                    action = f"Giảm giá nhẹ −{cluster_break_even_pct:.1f}% (Giữ an toàn Margin hòa vốn)"
                else:
                    action = f"Early Bird / Seasonal Discount −{suggested_discount}%"
                    
            industry_prefix = {
                "FASHION_FAST": "Flash Sale Thời trang",
                "ELECTRONICS_TECH": "Clearance Công nghệ",
                "FMCG_FOOD": "Clearance Cận date",
                "HOME_LIVING": "Clearance Nội thất",
                "GENERAL": "Chiến dịch Xả hàng"
            }.get(ind_code, "Chiến dịch Xả hàng")
            
            action = f"{industry_prefix}: {action}"

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

            skus_sorted = sorted(skus, key=lambda s: s['risk_score'], reverse=True)[:3]
            samples = [{
                "name": s['row']['name'],
                "daysInInventory": s['row']['days'],
                "frozenValueVnd": s['row']['total_value'],
                "riskScore": s['risk_score']
            } for s in skus_sorted]
            
            # Cross-selling logic
            healthy_skus = [r for r in raw_rows if r not in [s['row'] for s in scored_skus]]
            avg_price = sum(s['row']['price'] for s in skus) / len(skus) if skus else 0
            suitable_cross_sells = [h for h in healthy_skus if h['price'] * 0.5 <= avg_price <= h['price'] * 2.0]
            if not suitable_cross_sells and healthy_skus:
                suitable_cross_sells = healthy_skus
            
            bundle_item = None
            if suitable_cross_sells:
                cluster_hash = abs(hash(str(key)))
                selected_match = suitable_cross_sells[cluster_hash % len(suitable_cross_sells)]
                bundle_item = {
                    "hotItemName": selected_match['name'],
                    "hotItemPrice": selected_match['price'],
                    "logic": "Cùng phân khúc giá (Price Segment) và tỷ lệ tiêu thụ cao"
                }

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
                "recommendedDiscountPct": suggested_discount,
                "estimatedClearDays": 7 if tier == "CRITICAL" else (14 if tier == "HIGH" else 30),
                "topSkuSamples": samples,
                "bundleAvailable": bundle_item
            })

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
