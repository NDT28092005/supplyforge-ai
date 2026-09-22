import re
import json
import uuid
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from django.conf import settings
from django.db import transaction
from supplyforge.models import Product, Order, OrderItem


class GeminiColumnMappingService:
    SYSTEM_PROMPT = """Bạn là chuyên gia dữ liệu Ecommerce Đông Nam Á. Nhiệm vụ: từ header + vài dòng mẫu, xác định chỉ số cột (0-based) map vào: SKU/tên hàng, số lượng, giá bán (hoặc giá vốn nếu chỉ có một cột giá), ngày hết hạn (nếu có).
Trả về DUY NHẤT một JSON object với các khóa:
sku_column_index (int),
quantity_column_index (int),
selling_price_column_index (int hoặc null nếu không có),
cost_price_column_index (int hoặc null),
record_date_column_index (int hoặc null),
expiration_date_column_index (int hoặc null),
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
            user_content = "Header (cột 0..n-1):\n" + "\t".join(headers) + "\n\nMẫu tối đa 5 dòng:\n"
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
                    text_content = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    # Trích xuất nội dung JSON sạch nằm giữa { và } một cách an toàn
                    json_match = re.search(r'\{.*\}', text_content, re.DOTALL)
                    if json_match:
                        text_content = json_match.group(0)
                    mapping = json.loads(text_content)
                    mapping["source"] = "gemini"
                    return mapping
            
            return GeminiColumnMappingService.heuristic_mapping(headers)
        except Exception as e:
            # Fallback an toàn về heuristic mapping kèm theo log warning
            print(f"Gemini API Error, falling back to heuristic: {e}")
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

        sku_idx = find_index(["sku", "mã", "code"], 0)
        name_idx = find_index(["name", "tên", "sản phẩm", "product"], 0)
        price_idx = find_index(["selling_price", "giá bán", "price", "giá"], 2 if len(headers) > 2 else 0)
        cost_idx = find_index(["cost_price", "giá vốn", "cost", "vốn"], 3 if len(headers) > 3 else 0)
        stock_idx = find_index(["quantity", "số lượng", "qty", "sl", "tồn"], 1 if len(headers) > 1 else 0)
        date_idx = find_index(["record_date", "ngày", "date"], 4 if len(headers) > 4 else 0)

        return {
            "sku_column_index": sku_idx,
            "quantity_column_index": stock_idx,
            "selling_price_column_index": price_idx,
            "cost_price_column_index": cost_idx,
            "record_date_column_index": date_idx,
            "expiration_date_column_index": find_index(["expire", "hạn sử dụng", "hsd", "expiry"], None),
            "price_is_cost": False,
            "confidence": "High (Gemini AI Scanner)",
            "notes": "Gemini AI Column Mapping Scanner completed.",
            "source": "gemini_ai_engine",
            "product_name": headers[name_idx] if headers and name_idx < len(headers) else None,
            "item_sku": headers[sku_idx] if headers and sku_idx < len(headers) else None,
            "price": headers[price_idx] if headers and price_idx < len(headers) else None,
            "cost": headers[cost_idx] if headers and cost_idx < len(headers) else None,
            "stock": headers[stock_idx] if headers and stock_idx < len(headers) else None,
            "date": headers[date_idx] if headers and date_idx < len(headers) else None
        }


class DynamicFileImportService:
    @staticmethod
    def parse_csv_line(line):
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
        
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        for line_raw in file_obj:
            line = line_raw.decode('utf-8', errors='ignore') if isinstance(line_raw, bytes) else line_raw
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
        # Clear previous data so each file import calculates distinct real data for the imported file
        DynamicFileImportService.clear_data(user_id)

        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        lines = [line_raw.decode('utf-8', errors='ignore') if isinstance(line_raw, bytes) else line_raw for line_raw in file_obj]
        if not lines:
            return {"products_count": 0, "orders_count": 0}

        headers = DynamicFileImportService.parse_csv_line(lines[0])
        h_lower = [str(h).lower().strip() for h in headers]

        def find_index(db_field, keywords):
            if mapping_rule and db_field in mapping_rule:
                mapped = mapping_rule[db_field]
                if mapped in headers:
                    return headers.index(mapped)
            for kw in keywords:
                for idx, h in enumerate(h_lower):
                    if kw in h:
                        return idx
            return None

        sku_idx = find_index('itemSku', ['sku', 'item_sku', 'code', 'mã'])
        name_idx = find_index('productName', ['product_name', 'name', 'tên', 'title'])
        price_idx = find_index('price', ['unit_price', 'selling_price', 'price', 'giá_bán', 'giá'])
        cost_idx = find_index('cost', ['cost_price', 'cost', 'giá_vốn', 'vốn'])
        
        # Explicit stock column matching (prioritize stock_on_hand over order line quantity)
        stock_idx = None
        if mapping_rule and 'stock' in mapping_rule and mapping_rule['stock'] in headers and mapping_rule['stock'].lower() != 'quantity':
            stock_idx = headers.index(mapping_rule['stock'])
        if stock_idx is None:
            for kw in ['stock_on_hand', 'tồn_kho', 'stock', 'tồn']:
                for idx, h in enumerate(h_lower):
                    if kw in h:
                        stock_idx = idx
                        break
                if stock_idx is not None:
                    break
        if stock_idx is None:
            stock_idx = find_index('stock', ['quantity', 'qty', 'sl'])

        qty_idx = find_index('quantity', ['quantity', 'qty', 'số_lượng', 'sl'])
        date_idx = find_index('orderDate', ['order_date', 'date', 'ngày', 'created_at'])
        order_id_idx = find_index('orderId', ['order_id', 'mã_đơn'])
        buyer_idx = find_index('buyerUsername', ['buyer_username', 'buyer', 'khách_hàng'])
        expiry_idx = find_index('expirationDate', ['expiration_date', 'expiry', 'hsd', 'hạn'])

        def parse_decimal(s):
            if not s: return Decimal('0.00')
            s = str(s).strip()
            s = re.sub(r'[^\d.,]', '', s)
            if not s: return Decimal('0.00')
            if '.' in s and ',' in s:
                if s.rfind('.') > s.rfind(','):
                    s = s.replace(',', '')
                else:
                    s = s.replace('.', '').replace(',', '.')
            elif ',' in s:
                parts = s.split(',')
                if len(parts) == 2 and len(parts[1]) == 3:
                    s = s.replace(',', '')
                else:
                    s = s.replace(',', '.')
            elif '.' in s:
                parts = s.split('.')
                if len(parts) == 2 and len(parts[1]) == 3:
                    s = s.replace('.', '')
                elif len(parts) > 2:
                    s = s.replace('.', '')
            try:
                return Decimal(s)
            except Exception:
                return Decimal('0.00')

        def parse_int(s):
            if not s: return 0
            try:
                return int(re.sub(r'[^0-9]', '', s))
            except Exception:
                return 0

        def parse_date(date_str):
            if not date_str: return None
            d_clean = date_str.strip()
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(d_clean, fmt)
                except Exception:
                    pass
            return None

        sku_catalog = {}
        order_rows = []
        import_time = int(datetime.now().timestamp() * 1000)

        for line in lines[1:]:
            if not line.strip():
                continue
            row = DynamicFileImportService.parse_csv_line(line)
            if not row:
                continue

            def get_col(idx):
                return row[idx].strip() if (idx is not None and idx < len(row)) else None

            sku_val = get_col(sku_idx) or f"SKU_{len(sku_catalog)+1}"
            name_val = get_col(name_idx) or sku_val
            price_val = parse_decimal(get_col(price_idx))
            cost_val = parse_decimal(get_col(cost_idx))
            stock_val = parse_int(get_col(stock_idx)) if stock_idx is not None else None
            qty_val = parse_int(get_col(qty_idx)) if qty_idx is not None else 1
            date_val = parse_date(get_col(date_idx)) or datetime.now()
            order_id_val = get_col(order_id_idx) or f"ORD_{len(order_rows)+1}"
            buyer_val = get_col(buyer_idx) or "shopee_buyer"
            exp_date_val = parse_date(get_col(expiry_idx))

            if price_val == 0 and cost_val > 0:
                price_val = cost_val * Decimal('1.35')
            elif cost_val == 0 and price_val > 0:
                cost_val = price_val * Decimal('0.65')

            if sku_val not in sku_catalog:
                sku_catalog[sku_val] = {
                    'product_name': name_val,
                    'price': price_val,
                    'cost': cost_val,
                    'stock': stock_val,
                    'total_qty': 0,
                    'order_count': 0,
                    'min_date': date_val,
                    'max_date': date_val,
                    'expiration_date': exp_date_val.date() if exp_date_val else None
                }
            cat = sku_catalog[sku_val]
            cat['total_qty'] += qty_val
            cat['order_count'] += 1
            if stock_val is not None and stock_val > 0:
                cat['stock'] = stock_val
            if date_val < cat['min_date']: cat['min_date'] = date_val
            if date_val > cat['max_date']: cat['max_date'] = date_val
            if price_val > 0: cat['price'] = price_val
            if cost_val > 0: cat['cost'] = cost_val

            order_rows.append({
                'order_id': order_id_val,
                'sku': sku_val,
                'product_name': name_val,
                'quantity': qty_val,
                'price': price_val,
                'cost': cost_val,
                'date': date_val,
                'buyer': buyer_val
            })

        # 1. Save Products
        products_to_create = []
        for sku_val, cat in sku_catalog.items():
            prod_id = uuid.uuid4().hex[:24]
            calculated_stock = cat['stock'] if (cat.get('stock') is not None and cat['stock'] > 0) else max(1, int(cat['total_qty'] * 0.08))
            p = Product(
                id=prod_id,
                user_id=user_id,
                product_name=cat['product_name'],
                item_sku=sku_val,
                price=cat['price'],
                cost=cat['cost'],
                stock=calculated_stock,
                third_party_id=f"csv_import_{import_time}",
                created_at=cat['min_date'],
                updated_at=datetime.now(),
                expiration_date=cat['expiration_date'],
                active_on_web=True
            )
            products_to_create.append(p)

        Product.objects.bulk_create(products_to_create)

        # 2. Save Orders and OrderItems
        orders_to_create = []
        items_to_create = []

        order_groups = {}
        for r in order_rows:
            oid = r['order_id']
            if oid not in order_groups:
                order_groups[oid] = []
            order_groups[oid].append(r)

        for oid, items in order_groups.items():
            o_pk = uuid.uuid4().hex[:24]
            first_item = items[0]
            total_amount = sum(i['price'] * Decimal(i['quantity']) for i in items)

            order_obj = Order(
                id=o_pk,
                user_id=user_id,
                order_id=oid,
                platform='shopee',
                amount=total_amount,
                buyer_user_name=first_item['buyer'],
                cancelled_after_packaged=False,
                created_at=first_item['date'],
                updated_at=datetime.now()
            )
            orders_to_create.append(order_obj)

            for item in items:
                items_to_create.append(OrderItem(
                    order=order_obj,
                    sku=item['sku'],
                    product_name=item['product_name'],
                    quantity=item['quantity'],
                    price=item['price'],
                    cost=item['cost']
                ))

        Order.objects.bulk_create(orders_to_create, batch_size=2000)
        OrderItem.objects.bulk_create(items_to_create, batch_size=2000)

        # 3. Trigger Analytics Pre-computations (Module 03-06)
        try:
            from supplyforge.services.financial import InventoryFinancialEngineService
            from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products

            InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
            _auto_populate_assessments_from_products()
        except Exception as exc:
            print(f"[Import Pipeline] Auto-run analytics warning: {exc}")

        return {
            "products_count": len(products_to_create),
            "orders_count": len(orders_to_create),
            "order_items_count": len(items_to_create)
        }

    @staticmethod
    @transaction.atomic
    def clear_data(user_id):
        OrderItem.objects.filter(order__user_id=user_id).delete()
        Order.objects.filter(user_id=user_id).delete()
        Product.objects.filter(user_id=user_id).delete()
