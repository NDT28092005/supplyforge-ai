import csv
import random
from datetime import datetime, timedelta

def generate_enterprise_csv():
    random.seed(42)
    filename = "/home/nguyen-dai-tung/supplyforge-ai/test_data/enterprise_inventory_500_skus.csv"
    
    # Reference cutoff date
    ref_date = datetime(2026, 10, 1)
    
    categories = ['Thời trang Nam', 'Mẹ & Bé', 'Thiết bị điện tử', 'Nhà cửa & Đời sống', 'Mỹ phẩm & Làm đẹp']
    
    headers = [
        'order_id', 'order_date', 'sku', 'product_name', 'category',
        'quantity', 'unit_price', 'total_amount', 'cost_price', 'stock_on_hand', 'order_status'
    ]

    rows = []
    order_id_counter = 100000

    # 500 SKUs configuration:
    # 001..100: CRITICAL (100 SKUs) - DSLS > 90d, zero_rate high, high capital
    # 101..200: HIGH_RISK (100 SKUs) - DSLS 45-89d, low velocity
    # 201..350: MEDIUM_RISK (150 SKUs) - DSLS 20-40d, moderate velocity
    # 351..500: LOW_RISK (150 SKUs) - DSLS 1-10d, high velocity

    for i in range(1, 501):
        if i <= 100:
            tier = "CRITICAL"
            sku = f"CRIT-{i:03d}"
            name = f"Sản phẩm Nguy Cơ Bán Chậm Rất Cao {i}"
            cat = categories[(i - 1) % len(categories)]
            stock = 150 + (i * 3)  # 153..450
            cost = 200000 + (i * 2000)  # 202,000..400,000
            price = int(cost * 1.4)
            # Sales: 1 order 120-180 days ago (no sales in last 90d)
            order_days_ago = 100 + (i % 60)
            num_orders = 1
        elif i <= 200:
            tier = "HIGH_RISK"
            idx = i - 100
            sku = f"HIGH-{idx:03d}"
            name = f"Sản phẩm Nguy Cơ Bán Chậm Cao {idx}"
            cat = categories[(i - 1) % len(categories)]
            stock = 100 + (idx * 2)  # 102..300
            cost = 120000 + (idx * 1500)  # 121,500..270,000
            price = int(cost * 1.35)
            # Sales: 2 orders 50..85 days ago
            order_days_ago = 50 + (idx % 35)
            num_orders = 2
        elif i <= 350:
            tier = "MEDIUM_RISK"
            idx = i - 200
            sku = f"MED-{idx:03d}"
            name = f"Sản phẩm Cần Theo Dõi {idx}"
            cat = categories[(i - 1) % len(categories)]
            stock = 60 + (idx * 1)  # 61..210
            cost = 80000 + (idx * 800)  # 80,800..200,000
            price = int(cost * 1.3)
            # Sales: 5..8 orders in last 90d, latest 20..38 days ago
            order_days_ago = 20 + (idx % 18)
            num_orders = 6
        else:
            tier = "LOW_RISK"
            idx = i - 350
            sku = f"SAFE-{idx:03d}"
            name = f"Sản phẩm Tồn Kho An Toàn {idx}"
            cat = categories[(i - 1) % len(categories)]
            stock = 25 + (idx % 45)  # 25..70
            cost = 50000 + (idx * 500)  # 50,500..125,000
            price = int(cost * 1.3)
            # Sales: 15..30 orders in last 90d, latest 1..8 days ago
            order_days_ago = 1 + (idx % 8)
            num_orders = 20

        # Generate orders
        for o in range(num_orders):
            order_id_counter += 1
            ord_id = f"ORD-2026-{order_id_counter}"
            # Spread order dates
            dt_offset = order_days_ago + (o * 12)
            ord_dt = ref_date - timedelta(days=dt_offset)
            qty = random.randint(1, 3)
            tot_amt = qty * price

            rows.append({
                'order_id': ord_id,
                'order_date': ord_dt.strftime('%Y-%m-%d'),
                'sku': sku,
                'product_name': name,
                'category': cat,
                'quantity': qty,
                'unit_price': price,
                'total_amount': tot_amt,
                'cost_price': cost,
                'stock_on_hand': stock,
                'order_status': 'COMPLETED'
            })

    # Sort rows by order_date ascending
    rows.sort(key=lambda r: r['order_date'])

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} order rows across 500 SKUs to {filename}")

if __name__ == "__main__":
    generate_enterprise_csv()
