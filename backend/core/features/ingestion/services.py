import re
import json
import uuid
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from django.conf import settings
from django.db import transaction
from core.models import Product, Order, OrderItem

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
            "expiration_date_column_index": find_index(["expire", "hạn sử dụng", "hsd", "expiry"], None),
            "price_is_cost": False,
            "confidence": "medium",
            "notes": "Heuristic Mapping (không dùng AI do thiếu API Key).",
            "source": "heuristic_improved"
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
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        lines = [line_raw.decode('utf-8', errors='ignore') if isinstance(line_raw, bytes) else line_raw for line_raw in file_obj]
        if not lines:
            return

        headers = DynamicFileImportService.parse_csv_line(lines[0])
        
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
            expiry_str = get_val("expirationDate") or get_val("expiration_date")

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

            # Parse created date
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
                import random
                created_at = datetime.now() - timedelta(days=random.randint(0, 90))

            # Parse expiration date (F&B)
            expiration_date = None
            if expiry_str:
                expiry_clean = expiry_str.strip()
                try:
                    if "/" in expiry_clean:
                        expiration_date = datetime.strptime(expiry_clean, "%d/%m/%Y").date()
                    else:
                        expiration_date = datetime.strptime(expiry_clean, "%Y-%m-%d").date()
                except Exception:
                    pass

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
                expiration_date=expiration_date,
                active_on_web=True
            )
            batch.append(product)

            if len(batch) >= 1000:
                Product.objects.bulk_create(batch)
                batch = []

        if batch:
            Product.objects.bulk_create(batch)

    @staticmethod
    @transaction.atomic
    def clear_data(user_id):
        OrderItem.objects.filter(order__user_id=user_id).delete()
        Order.objects.filter(user_id=user_id).delete()
        Product.objects.filter(user_id=user_id).delete()
