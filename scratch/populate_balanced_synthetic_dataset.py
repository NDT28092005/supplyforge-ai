import os
import sys
import random
import uuid
from datetime import datetime, timedelta

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, 'backend')
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from supplyforge.models import User, Workspace, Product, Order, OrderItem, SlowMovingRiskAssessment, IngestionSession
from supplyforge.models.capital_exposure import CapitalExposureAnalysisRecord, CapitalExposureItemRecord
from src.analytics.capital_exposure_repository import CapitalExposureRepository
from src.analytics.capital_valuation_engine import CapitalValuationEngine
from src.analytics.inventory_aging_engine import InventoryAgingEngine
from src.analytics.risk_weighted_exposure_engine import RiskWeightedExposureEngine
from src.analytics.aging_risk_classifier import AgingRiskClassifier
from src.analytics.financial_impact_engine import FinancialImpactEngine
import pandas as pd

def generate_balanced_dataset():
    print("🧹 Cleaning ALL existing products and orders in MySQL...")
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    SlowMovingRiskAssessment.objects.all().delete()
    IngestionSession.objects.all().delete()
    Product.objects.all().delete()
    CapitalExposureItemRecord.objects.all().delete()
    CapitalExposureAnalysisRecord.objects.all().delete()

    user, _ = User.objects.get_or_create(email="user_default_001@supplyforge.ai", defaults={"display_name": "Demo Seller"})
    workspace, _ = Workspace.objects.get_or_create(name="Default Workspace", defaults={"owner": user})

    session = IngestionSession.objects.create(
        workspace=workspace,
        original_filename="large_shopee_orders_50k.csv",
        storage_path="test-data/large_shopee_orders_50k.csv",
        file_size_bytes=5242880,
        total_rows=25000,
        status="COMPLETED"
    )

    print(f"⚡ Created Session {session.id}. Generating 100 SKUs rải đều 4 Mức Rủi Ro cho user_default_001...")
    
    categories = ['Sữa & Tã', 'Đồ Dùng Cho Bé', 'Thời Trang Trẻ Em', 'Đồ Chơi Sáng Tạo', 'Gia Dụng & Mẹ Bầu']
    now = datetime.now()

    groups = [
        {'risk': 'CRITICAL', 'aging': 'CRITICAL_AGING', 'dsls_min': 120, 'dsls_max': 240, 'sales_60d': 0, 'cost_min': 200000, 'cost_max': 500000, 'stock_min': 100, 'stock_max': 300},
        {'risk': 'HIGH_RISK', 'aging': 'AGING', 'dsls_min': 60, 'dsls_max': 90, 'sales_60d': 3, 'cost_min': 150000, 'cost_max': 350000, 'stock_min': 80, 'stock_max': 200},
        {'risk': 'MEDIUM_RISK', 'aging': 'STALE', 'dsls_min': 30, 'dsls_max': 45, 'sales_60d': 12, 'cost_min': 100000, 'cost_max': 250000, 'stock_min': 50, 'stock_max': 150},
        {'risk': 'LOW_RISK', 'aging': 'HEALTHY', 'dsls_min': 2, 'dsls_max': 10, 'sales_60d': 45, 'cost_min': 50000, 'cost_max': 180000, 'stock_min': 30, 'stock_max': 100},
    ]

    products_created = []
    orders_created = []
    order_items_created = []
    risk_created = []

    sku_index = 1001
    order_id_counter = 50001

    for grp in groups:
        risk_class = grp['risk']
        for i in range(25):
            sku_code = f"SKU_BAL_{sku_index}"
            cat = categories[i % len(categories)]
            prod_name = f"Sản phẩm Demo {risk_class} #{sku_index} - {cat}"
            unit_cost = random.randint(grp['cost_min'] // 1000, grp['cost_max'] // 1000) * 1000
            price = int(unit_cost * random.uniform(1.3, 1.8))
            stock = random.randint(grp['stock_min'], grp['stock_max'])

            p = Product.objects.create(
                id=f"65000000000000000000{sku_index:04d}",
                user_id="user_default_001",
                third_party_id=f"ITEM_{sku_index}",
                item_id=f"ITEM_{sku_index}",
                item_sku=sku_code,
                product_name=prod_name,
                stock=stock,
                cost=unit_cost,
                price=price,
                platform="Shopee"
            )
            products_created.append(p)

            dsls = random.randint(grp['dsls_min'], grp['dsls_max'])
            last_order_dt = now - timedelta(days=dsls)

            n_sales = grp['sales_60d']
            if n_sales > 0:
                for s in range(n_sales):
                    days_ago = dsls + random.randint(0, 60)
                    ord_dt = now - timedelta(days=days_ago)
                    ord_sn = f"ORD_{order_id_counter}"
                    hex_id = f"7500000000000000{order_id_counter:08d}"
                    order_id_counter += 1

                    o = Order(
                        id=hex_id,
                        user_id="user_default_001",
                        order_id=ord_sn,
                        amount=price,
                        platform="Shopee",
                        created_at=ord_dt
                    )
                    orders_created.append(o)

                    oi = OrderItem(
                        order=o,
                        sku=sku_code,
                        product_name=prod_name,
                        item_id=f"ITEM_{sku_index}",
                        quantity=1,
                        price=price,
                        cost=unit_cost
                    )
                    order_items_created.append(oi)
            else:
                ord_sn = f"ORD_{order_id_counter}"
                hex_id = f"7500000000000000{order_id_counter:08d}"
                order_id_counter += 1
                o = Order(
                    id=hex_id,
                    user_id="user_default_001",
                    order_id=ord_sn,
                    amount=price,
                    platform="Shopee",
                    created_at=last_order_dt
                )
                orders_created.append(o)
                oi = OrderItem(
                    order=o,
                    sku=sku_code,
                    product_name=prod_name,
                    item_id=f"ITEM_{sku_index}",
                    quantity=1,
                    price=price,
                    cost=unit_cost
                )
                order_items_created.append(oi)

            prob_map = {'CRITICAL': 0.95, 'HIGH_RISK': 0.78, 'MEDIUM_RISK': 0.48, 'LOW_RISK': 0.12}
            score_map = {'CRITICAL': 92.5, 'HIGH_RISK': 75.0, 'MEDIUM_RISK': 45.0, 'LOW_RISK': 12.0}

            r = SlowMovingRiskAssessment.objects.create(
                session=session,
                sku=sku_code,
                canonical_sku_id=sku_code,
                product_name=prod_name,
                category=cat,
                risk_class=risk_class,
                risk_probability=prob_map[risk_class],
                risk_score=score_map[risk_class],
                primary_signals=[f"DSLS={dsls}d", f"ZeroRate={(1.0 - n_sales/60.0):.2f}"],
                supporting_signals=[f"Stock={stock}", f"UnitCost={unit_cost:,.0f}đ"],
                diagnostics=[f"LUMPY_DEMAND" if grp['risk'] in ['CRITICAL', 'HIGH_RISK'] else 'NORMAL'],
                evidence={'dsls': dsls, 'sales_30d': n_sales, 'unit_cost': unit_cost, 'stock': stock}
            )
            risk_created.append(r)

            sku_index += 1

    print(f"📦 Saving {len(orders_created)} orders and order items...")
    Order.objects.bulk_create(orders_created, batch_size=1000)

    order_dict = {o.order_id: o for o in Order.objects.all()}
    for oi in order_items_created:
        oi.order = order_dict[oi.order.order_id]
    OrderItem.objects.bulk_create(order_items_created, batch_size=1000)

    print("✅ Clean balanced dataset generated for user_default_001!")

    print("🚀 Triggering Capital Exposure Pipeline Analysis...")
    product_rows = []
    for p in products_created:
        cost = float(p.cost)
        stock = int(p.stock)
        r = SlowMovingRiskAssessment.objects.get(sku=p.item_sku)
        product_rows.append({
            'sku': p.item_sku,
            'product_name': p.product_name,
            'category': p.product_name.split(' - ')[-1] if ' - ' in p.product_name else 'E-Commerce',
            'stock_on_hand': stock,
            'unit_cost': cost,
            'dsls': r.evidence.get('dsls', 30),
            'last_sale_date': (now - timedelta(days=r.evidence.get('dsls', 30))).strftime('%Y-%m-%d'),
        })

    sample_df = pd.DataFrame(product_rows)
    risk_assessments = [
        {
            'sku': r.sku,
            'risk_class': r.risk_class,
            'risk_probability': float(r.risk_probability),
            'risk_score': float(r.risk_score),
        }
        for r in risk_created
    ]

    val_engine = CapitalValuationEngine()
    aging_engine = InventoryAgingEngine()
    exposure_engine = RiskWeightedExposureEngine()
    classifier = AgingRiskClassifier()
    impact_engine = FinancialImpactEngine(default_opportunity_rate=0.12)

    sku_val_records, val_summary = val_engine.value_dataset(sample_df, risk_assessments)
    aging_records, matrix, aging_summary = aging_engine.analyze_dataset_aging(sku_val_records, analysis_date=now.strftime('%Y-%m-%d'))
    exposure_records, portfolio_summary = exposure_engine.evaluate_portfolio_exposure(aging_records)
    assessments, risk_dist, prio_dist, summary = classifier.evaluate_dataset_aging_risk(exposure_records)
    fin_summary = impact_engine.evaluate_portfolio_financial_impact(assessments, annual_rate=0.12)

    analysis_rec = CapitalExposureRepository.save_analysis(
        summary_payload=fin_summary,
        sku_assessment_records=assessments,
        merchant_id="user_default_001",
        dataset_version="v1.0_balanced",
        analysis_id="BALANCED_DATASET_RUN"
    )

    print("\n=======================================================")
    print("📊 VERIFYING FINANCIAL ENGINE VALUES FOR user_default_001")
    print("=======================================================\n")
    from supplyforge.services.financial import InventoryFinancialEngineService
    fin_res = InventoryFinancialEngineService.calculate_aging_and_hidden_costs('user_default_001')
    print(f"Total Healthy Value: {fin_res.get('totalHealthyValue'):,.0f} VNĐ")
    print(f"Total Watchlist Value: {fin_res.get('totalWatchlistValue'):,.0f} VNĐ")
    print(f"Total Slow Moving Value: {fin_res.get('totalSlowMovingValue'):,.0f} VNĐ")
    print(f"Total Dead Stock Value: {fin_res.get('totalDeadStockValue'):,.0f} VNĐ")
    print(f"Total Frozen Value (Dead + Slow): {fin_res.get('totalFrozenValue'):,.0f} VNĐ")

if __name__ == '__main__':
    generate_balanced_dataset()
