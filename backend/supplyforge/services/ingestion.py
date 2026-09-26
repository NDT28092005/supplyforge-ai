import os
import re
import json
import uuid
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Min, Max
from supplyforge.models import Product, Order, OrderItem, ArchivedDataSet


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


from supplyforge.services.csv_validator import CSVFormatValidator, ValidationStatus


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
    def process_batch_import(file_obj, mapping_rule, user_id, session_type='INITIAL', force_reset=False, session_id=None):
        """Execute IR-003, IR-004, IR-007 & IR-008 Import pipeline:
        Upload → Validate → Schema Mapping → Data Cleaning → Deduplication / Data Correction Upsert → Persist → DATA_READY
        """
        # --- Stage 1 & 2: Upload & Validate ---
        val_res = CSVFormatValidator.validate_file(file_obj)
        if val_res.status == ValidationStatus.REJECT:
            raise ValueError(f"CSV Validation Rejected: {'; '.join(val_res.errors)}")

        # Detect existing dataset for IR-004, IR-005, IR-006, IR-007 & IR-008 Incremental Ingestion
        existing_orders = Order.objects.filter(user_id=user_id)
        existing_products = Product.objects.filter(user_id=user_id)
        existing_orders_count = existing_orders.count()

        is_incremental = (session_type == 'INCREMENTAL' or existing_orders_count > 0) and not force_reset
        
        e_start = None
        e_end = None
        existing_order_ids = set()
        existing_items_map = {}
        existing_orders_map = {}
        before_sku_count = Product.objects.filter(user_id=user_id).count()

        if is_incremental:
            e_start = existing_orders.aggregate(Min('created_at'))['created_at__min']
            e_end = existing_orders.aggregate(Max('created_at'))['created_at__max']
            existing_order_ids = set(existing_orders.values_list('order_id', flat=True))
            existing_orders_map = {o.order_id: o for o in existing_orders}
            for item in OrderItem.objects.filter(order__user_id=user_id).select_related('order'):
                existing_items_map[(item.order.order_id, item.sku)] = item
        elif force_reset:
            # Clear & Archive previous data when merchant explicitly requested complete reset
            DynamicFileImportService.clear_data(user_id)

        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        lines = [line_raw.decode('utf-8', errors='ignore') if isinstance(line_raw, bytes) else line_raw for line_raw in file_obj]
        if not lines:
            return {
                "status": "DATA_READY",
                "import_type": "INCREMENTAL" if is_incremental else "INITIAL",
                "rows_received": 0,
                "new_rows": 0,
                "rows_valid": 0,
                "rows_rejected": 0,
                "duplicate_rows": 0,
                "updated_rows": 0,
                "data_corrections": [],
                "overlap_detected": False,
                "warnings": 0,
                "products_count": Product.objects.filter(user_id=user_id).count(),
                "orders_count": Order.objects.filter(user_id=user_id).count()
            }

        rows_received = max(0, len(lines) - 1)  # Exclude header
        corrupted_line_numbers = {cr['line_number'] for cr in val_res.corrupted_rows}
        warnings_count = len(val_res.warnings)

        # --- Stage 3: Schema Mapping ---
        headers = DynamicFileImportService.parse_csv_line(lines[0])
        h_lower = [str(h).lower().strip().replace('_', ' ') for h in headers]

        def find_index(db_field, keywords, exclude_words=None):
            if mapping_rule and db_field in mapping_rule:
                mapped = mapping_rule[db_field]
                if mapped in headers:
                    return headers.index(mapped)
            # Pass 1: Exact matches first
            for kw in keywords:
                kw_norm = kw.lower().replace('_', ' ')
                for idx, h in enumerate(h_lower):
                    if kw_norm == h:
                        return idx
            # Pass 2: Substring matches with exclusion check
            for kw in keywords:
                kw_norm = kw.lower().replace('_', ' ')
                for idx, h in enumerate(h_lower):
                    if kw_norm in h:
                        if exclude_words and any(ex in h for ex in exclude_words):
                            continue
                        return idx
            return None

        sku_idx = find_index('itemSku', ['mã sku', 'item sku', 'sku', 'mã sp', 'mã sản phẩm', 'product code', 'item code', 'barcode'], exclude_words=['đơn', 'order'])
        name_idx = find_index('productName', ['tên sản phẩm', 'tên sp', 'product name', 'name', 'tên', 'title'])
        price_idx = find_index('price', ['giá bán', 'unit price', 'selling price', 'price', 'giá'])
        cost_idx = find_index('cost', ['giá vốn', 'cost price', 'cost', 'vốn'])

        stock_idx = None
        if mapping_rule and 'stock' in mapping_rule and mapping_rule['stock'] in headers and mapping_rule['stock'].lower() != 'quantity':
            stock_idx = headers.index(mapping_rule['stock'])
        if stock_idx is None:
            for kw in ['stock on hand', 'tồn kho', 'stock', 'tồn']:
                for idx, h in enumerate(h_lower):
                    if kw in h:
                        stock_idx = idx
                        break
                if stock_idx is not None:
                    break
        if stock_idx is None:
            stock_idx = find_index('stock', ['quantity', 'qty', 'sl'])

        qty_idx = find_index('quantity', ['số lượng', 'quantity', 'qty', 'sl'])
        date_idx = find_index('orderDate', ['ngày tạo đơn', 'order date', 'ngày tạo', 'created at', 'date', 'ngày'])
        order_id_idx = find_index('orderId', ['mã đơn hàng', 'mã đơn', 'order id', 'order no', 'order'])
        buyer_idx = find_index('buyerUsername', ['buyer username', 'khách hàng', 'buyer'])
        expiry_idx = find_index('expirationDate', ['expiration date', 'hạn sử dụng', 'expiry', 'hsd'])

        # --- Stage 4: Data Cleaning Helpers ---
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

        # --- Stage 5 & 6: Deduplication, Null Data Validation & Canonicalization (IR-005 - IR-010) ---
        sku_catalog = {}
        order_rows = []
        seen_row_signatures = set()
        duplicate_rows_count = 0
        updated_rows_count = 0
        data_corrections_log = []
        rejected_rows_log = []

        # Include structural CSV corrupted rows from Stage 1 validation
        for cr in val_res.corrupted_rows:
            rejected_rows_log.append({
                "line_number": cr.get("line_number"),
                "raw_content": cr.get("raw_content", "")[:150],
                "reason": f"Lỗi cấu trúc CSV: {cr.get('reason', 'Malformed CSV line')}"
            })

        rows_rejected_count = len(rejected_rows_log)
        import_time = int(datetime.now().timestamp() * 1000)

        incoming_dates = []

        def validate_strict_qty(s):
            if not s: return None
            s_clean = s.strip()
            if not re.match(r'^-?\d+$', s_clean):
                return None
            try:
                val = int(s_clean)
                if val <= 0:
                    return None
                return val
            except Exception:
                return None

        for idx, line in enumerate(lines[1:], start=2):
            if idx in corrupted_line_numbers:
                continue

            if not line.strip():
                continue

            row = DynamicFileImportService.parse_csv_line(line)
            if not row:
                rows_rejected_count += 1
                rejected_rows_log.append({
                    "line_number": idx,
                    "raw_content": line[:150],
                    "reason": "Dòng dữ liệu rỗng (Empty row)"
                })
                continue

            def get_col(c_idx):
                return row[c_idx].strip() if (c_idx is not None and c_idx < len(row)) else None

            raw_sku = get_col(sku_idx)
            raw_date = get_col(date_idx)
            raw_qty = get_col(qty_idx)
            raw_price = get_col(price_idx)
            raw_cost = get_col(cost_idx)

            # --- IR-010 Rule 1: SKU must NOT be NULL / empty ---
            if not raw_sku or raw_sku.upper() in ["NULL", "NONE", "NAN", "UNDEFINED", ""]:
                rows_rejected_count += 1
                rejected_rows_log.append({
                    "line_number": idx,
                    "raw_content": line[:150],
                    "reason": "Thiếu mã SKU (SKU rỗng hoặc NULL)"
                })
                continue

            # --- IR-010 Rule 2: Date must be valid & parseable ---
            date_val = parse_date(raw_date) if raw_date else None
            if not date_val:
                rows_rejected_count += 1
                rejected_rows_log.append({
                    "line_number": idx,
                    "raw_content": line[:150],
                    "reason": f"Thiếu hoặc sai định dạng ngày tạo đơn ('{raw_date or 'NULL'}')"
                })
                continue

            # --- IR-010 Rule 3: Quantity must be valid integer > 0 ---
            qty_val = validate_strict_qty(raw_qty) if raw_qty else (1 if qty_idx is None else None)
            if qty_val is None:
                rows_rejected_count += 1
                rejected_rows_log.append({
                    "line_number": idx,
                    "raw_content": line[:150],
                    "reason": f"Số lượng không hợp lệ hoặc <= 0 ('{raw_qty or 'NULL'}')"
                })
                continue

            # --- IR-010 Rule 4: Revenue / Price & Cost check ---
            price_val = parse_decimal(raw_price)
            cost_val = parse_decimal(raw_cost)
            if price_val <= 0 and cost_val <= 0:
                rows_rejected_count += 1
                rejected_rows_log.append({
                    "line_number": idx,
                    "raw_content": line[:150],
                    "reason": "Thiếu cả giá bán và giá vốn (không thể xác định doanh thu)"
                })
                continue

            sku_val = raw_sku.upper()
            name_val = get_col(name_idx) or sku_val
            stock_val = parse_int(get_col(stock_idx)) if stock_idx is not None else None
            order_id_val = get_col(order_id_idx) or f"ORD_{len(order_rows)+1}"
            buyer_val = get_col(buyer_idx) or "shopee_buyer"
            exp_date_val = parse_date(get_col(expiry_idx))

            incoming_dates.append(date_val)

            # Business Natural Key for Order line item: (order_id, sku)
            natural_key = (order_id_val, sku_val)
            row_sig = (sku_val, order_id_val, date_val.strftime("%Y-%m-%d %H:%M"), str(price_val), qty_val)

            # --- IR-007 & IR-008: Check against DB existing natural key ---
            if is_incremental and natural_key in existing_items_map:
                existing_item = existing_items_map[natural_key]
                is_same_price = (existing_item.price == price_val)
                is_same_qty = (existing_item.quantity == qty_val)
                is_same_cost = (cost_val == Decimal('0.00') or existing_item.cost == cost_val)

                if is_same_price and is_same_qty and is_same_cost:
                    # IR-007: Exact Duplicate Re-import
                    duplicate_rows_count += 1
                    continue
                else:
                    # IR-008: Data Correction / Upsert (Option B Canonical Upsert + Option C Versioned Audit Trail)
                    old_price = existing_item.price
                    old_cost = existing_item.cost
                    old_qty = existing_item.quantity
                    old_line_total = old_price * Decimal(old_qty)
                    new_line_total = price_val * Decimal(qty_val)

                    # Update OrderItem in DB
                    existing_item.price = price_val
                    if cost_val > 0:
                        existing_item.cost = cost_val
                    existing_item.quantity = qty_val
                    existing_item.save()

                    # Recalculate parent Order amount
                    o_obj = existing_orders_map.get(order_id_val) or getattr(existing_item, 'order', None)
                    if o_obj:
                        o_obj.amount = (o_obj.amount or Decimal('0')) - old_line_total + new_line_total
                        o_obj.updated_at = datetime.now()
                        o_obj.save()

                    # Record versioned audit log entry
                    audit_entry = {
                        "order_id": order_id_val,
                        "sku": sku_val,
                        "action": "CANONICAL_UPSERT",
                        "timestamp": datetime.now().isoformat(),
                        "old_values": {
                            "price": float(old_price),
                            "cost": float(old_cost),
                            "quantity": old_qty,
                            "revenue": float(old_line_total)
                        },
                        "new_values": {
                            "price": float(price_val),
                            "cost": float(cost_val if cost_val > 0 else old_cost),
                            "quantity": qty_val,
                            "revenue": float(new_line_total)
                        }
                    }
                    data_corrections_log.append(audit_entry)
                    updated_rows_count += 1

                    # Sync product catalog price/cost if updated
                    existing_p = Product.objects.filter(user_id=user_id, item_sku=sku_val).first()
                    if existing_p:
                        if price_val > 0: existing_p.price = price_val
                        if cost_val > 0: existing_p.cost = cost_val
                        existing_p.updated_at = datetime.now()
                        existing_p.save()

                    continue

            # Batch deduplication check within current CSV file
            if row_sig in seen_row_signatures or natural_key in seen_row_signatures:
                duplicate_rows_count += 1
                continue

            seen_row_signatures.add(row_sig)
            seen_row_signatures.add(natural_key)

            # Price / Cost fallback estimations
            if price_val == 0 and cost_val > 0:
                price_val = cost_val * Decimal('1.35')
                warnings_count += 1
            elif cost_val == 0 and price_val > 0:
                cost_val = price_val * Decimal('0.65')
                warnings_count += 1

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

        # IR-006: Partial Temporal Overlap Detection
        inc_start = min(incoming_dates) if incoming_dates else None
        inc_end = max(incoming_dates) if incoming_dates else None
        overlap_detected = False
        overlap_start = None
        overlap_end = None

        def to_date(dt):
            if dt is None: return None
            if getattr(dt, 'tzinfo', None) is not None:
                try:
                    from django.utils import timezone
                    return timezone.localtime(dt).date()
                except Exception:
                    return dt.date()
            if isinstance(dt, datetime):
                return dt.date()
            return dt

        e_start_d = to_date(e_start)
        e_end_d = to_date(e_end)
        inc_start_d = to_date(inc_start)
        inc_end_d = to_date(inc_end)

        if is_incremental and e_start_d and e_end_d and inc_start_d and inc_end_d:
            if inc_start_d <= e_end_d and inc_end_d >= e_start_d:
                overlap_detected = True
                overlap_start = max(inc_start_d, e_start_d)
                overlap_end = min(inc_end_d, e_end_d)

        # --- Stage 7: Persist (Atomic Append or Merge + Lineage Metadata IR-017) ---
        session_obj = None
        if session_id:
            try:
                from supplyforge.models import IngestionSession
                session_obj = IngestionSession.objects.filter(id=session_id).first()
            except Exception:
                session_obj = None

        import_id_str = (
            session_obj.ingestion_id if (session_obj and session_obj.ingestion_id)
            else (f"IMP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}")
        )
        file_name_str = session_obj.original_filename if session_obj else "uploaded_file.csv"
        uploaded_at_str = (
            session_obj.created_at.strftime("%Y-%m-%d %H:%M") if (session_obj and session_obj.created_at)
            else datetime.now().strftime("%Y-%m-%d %H:%M")
        )

        base_lineage_meta = {
            "import_id": import_id_str,
            "session_id": str(session_id) if session_id else None,
            "file": file_name_str,
            "merchant": str(user_id),
            "uploaded": uploaded_at_str,
            "timestamp": datetime.now().isoformat()
        }

        products_to_create = []
        for sku_val, cat in sku_catalog.items():
            existing_p = Product.objects.filter(user_id=user_id, item_sku=sku_val).first()
            calculated_stock = cat['stock'] if (cat.get('stock') is not None and cat['stock'] > 0) else max(1, int(cat['total_qty'] * 0.08))

            prod_lineage = {**base_lineage_meta, "record_id": sku_val, "record_type": "product"}

            if existing_p:
                # Update existing product price, cost, stock, and lineage history
                if cat['price'] > 0: existing_p.price = cat['price']
                if cat['cost'] > 0: existing_p.cost = cat['cost']
                if calculated_stock > 0: existing_p.stock = (existing_p.stock or 0) + calculated_stock
                existing_p.updated_at = datetime.now()

                p_data = existing_p.data or {}
                hist = p_data.get("import_history", [])
                hist.append({**prod_lineage, "action": "UPDATE"})
                p_data["lineage"] = prod_lineage
                p_data["import_history"] = hist
                existing_p.data = p_data
                existing_p.save()
            else:
                prod_id = uuid.uuid4().hex[:24]
                p_data = {
                    "lineage": prod_lineage,
                    "import_history": [prod_lineage]
                }
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
                    active_on_web=True,
                    data=p_data
                )
                products_to_create.append(p)

        if products_to_create:
            Product.objects.bulk_create(products_to_create)

        orders_to_create = []
        items_to_create = []

        order_groups = {}
        for r in order_rows:
            oid = r['order_id']
            if oid not in order_groups:
                order_groups[oid] = []
            order_groups[oid].append(r)

        for oid, items in order_groups.items():
            first_item = items[0]
            total_amount = sum(it['price'] * Decimal(it['quantity']) for it in items)
            ord_lineage = {**base_lineage_meta, "record_id": oid, "record_type": "order"}

            if oid in existing_orders_map:
                o = existing_orders_map[oid]
                o.amount = (o.amount or Decimal('0')) + total_amount
                o.updated_at = datetime.now()
                o_data = o.data or {}
                o_hist = o_data.get("import_history", [])
                o_hist.append({**ord_lineage, "action": "UPDATE"})
                o_data["lineage"] = ord_lineage
                o_data["import_history"] = o_hist
                o.data = o_data
                o.save()
            else:
                o_pk = uuid.uuid4().hex[:24]
                o_data = {
                    "lineage": ord_lineage,
                    "import_history": [ord_lineage]
                }
                o = Order(
                    id=o_pk,
                    user_id=user_id,
                    order_id=oid,
                    platform='shopee',
                    amount=total_amount,
                    buyer_user_name=first_item['buyer'],
                    cancelled_after_packaged=False,
                    created_at=first_item['date'],
                    updated_at=datetime.now(),
                    data=o_data
                )
                orders_to_create.append(o)
                existing_orders_map[oid] = o

            for it in items:
                item_obj = OrderItem(
                    order=o,
                    sku=it['sku'],
                    product_name=it['product_name'],
                    price=it['price'],
                    cost=it['cost'],
                    quantity=it['quantity']
                )
                items_to_create.append(item_obj)

        if orders_to_create:
            Order.objects.bulk_create(orders_to_create, batch_size=2000)
        if items_to_create:
            OrderItem.objects.bulk_create(items_to_create, batch_size=2000)

        # IR-016: Export processed canonical snapshot to /processed directory
        try:
            from supplyforge.services.csv_profiler import StreamingCSVProfiler
            processed_dir = StreamingCSVProfiler.get_processed_upload_dir()
            processed_filename = f"{session_id or uuid.uuid4().hex}_processed.json"
            processed_filepath = os.path.join(processed_dir, processed_filename)

            processed_payload = {
                "import_id": import_id_str,
                "session_id": str(session_id) if session_id else None,
                "original_filename": file_name_str,
                "processed_at": datetime.now().isoformat(),
                "summary": {
                    "total_products_created": len(products_to_create),
                    "total_orders_created": len(orders_to_create),
                    "total_order_items": len(items_to_create),
                    "duplicate_rows": duplicate_rows_count,
                    "updated_rows": updated_rows_count,
                    "rejected_rows": rows_rejected_count
                },
                "canonical_skus": list(sku_catalog.keys()),
                "data_corrections": data_corrections_log
            }

            with open(processed_filepath, 'w', encoding='utf-8') as pf:
                json.dump(processed_payload, pf, ensure_ascii=False, indent=2)

            if session_obj:
                session_obj.processed_storage_path = processed_filepath
        except Exception as proc_err:
            print(f"[Import Pipeline] Processed storage dump warning: {proc_err}")

        # Update IngestionSession history if session_id is provided or session exists
        if session_obj:
            try:
                session_obj.incremental_merge_json = {
                    "duplicate_rows": duplicate_rows_count,
                    "updated_rows": updated_rows_count,
                    "new_rows": len(items_to_create),
                    "data_corrections": data_corrections_log,
                    "rejected_rows": rejected_rows_log
                }
                hist = session_obj.ingestion_history_json or {}
                hist['audit_trail'] = hist.get('audit_trail', []) + data_corrections_log
                hist['rejected_rows'] = hist.get('rejected_rows', []) + rejected_rows_log
                session_obj.ingestion_history_json = hist
                if updated_rows_count > 0:
                    session_obj.dataset_version = f"v{1.0 + updated_rows_count * 0.1:.1f}"
                session_obj.save()
            except Exception as exc:
                print(f"[Import Pipeline] IngestionSession audit update warning: {exc}")

        # IR-019: Perform Post-Import Dataset Consistency Validation
        new_rows_count = len(items_to_create)
        rows_valid_count = new_rows_count

        from supplyforge.services.dataset_consistency import DatasetConsistencyValidator
        import_stats = {
            'total_rows': rows_received,
            'processed_rows': new_rows_count,
            'new_sku_count': len(products_to_create),
            'updated_sku_count': updated_rows_count,
            'duplicate_rows': duplicate_rows_count,
            'rejected_rows': rows_rejected_count,
            'min_date': inc_start_d,
            'max_date': inc_end_d
        }
        consistency_report = DatasetConsistencyValidator.validate_post_import(
            user_id, session_obj, before_sku_count, import_stats
        )

        # IR-018: Dequeue next session if available for workspace
        if session_obj and session_obj.workspace:
            try:
                from supplyforge.services.concurrency_manager import ImportConcurrencyManager
                ImportConcurrencyManager.dequeue_next_session(session_obj.workspace.id)
            except Exception as dq_err:
                print(f"[Import Pipeline] Dequeue warning: {dq_err}")

        # Trigger Analytics Pre-computations (Module 03-06)
        try:
            from supplyforge.services.financial import InventoryFinancialEngineService
            from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products

            InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
            _auto_populate_assessments_from_products()
        except Exception as exc:
            print(f"[Import Pipeline] Auto-run analytics warning: {exc}")

        temporal_range = {
            "existing_start": e_start_d.strftime("%Y-%m-%d") if (is_incremental and e_start_d) else None,
            "existing_end": e_end_d.strftime("%Y-%m-%d") if (is_incremental and e_end_d) else None,
            "incoming_start": inc_start_d.strftime("%Y-%m-%d") if inc_start_d else None,
            "incoming_end": inc_end_d.strftime("%Y-%m-%d") if inc_end_d else None,
            "overlap_detected": overlap_detected,
            "overlap_start": overlap_start.strftime("%Y-%m-%d") if overlap_start else None,
            "overlap_end": overlap_end.strftime("%Y-%m-%d") if overlap_end else None,
        }

        return {
            "status": "DATA_READY",
            "import_type": "INCREMENTAL" if is_incremental else "INITIAL",
            "schema_matched": True,
            "overlap_detected": overlap_detected,
            "temporal_range": temporal_range,
            "rows_received": rows_received,
            "new_rows": new_rows_count,
            "rows_valid": rows_valid_count,
            "rows_rejected": rows_rejected_count,
            "rejected_rows": rejected_rows_log,
            "rows_appended": new_rows_count,
            "duplicate_rows": duplicate_rows_count,
            "updated_rows": updated_rows_count,
            "data_corrections": data_corrections_log,
            "dataset_consistency": consistency_report,
            "warnings": warnings_count,
            "products_count": Product.objects.filter(user_id=user_id).count(),
            "orders_count": Order.objects.filter(user_id=user_id).count(),
            "order_items_count": OrderItem.objects.filter(order__user_id=user_id).count()
        }

    @staticmethod
    @transaction.atomic
    def clear_data(user_id):
        """Soft-delete / Archival Backup mechanism for merchant data reset.
        Preserves active products and orders in ArchivedDataSet snapshot for future AI model training.
        """
        active_products = list(Product.objects.filter(user_id=user_id).values())
        active_orders = list(Order.objects.filter(user_id=user_id).values())

        if active_products or active_orders:
            ArchivedDataSet.objects.create(
                user_id=user_id,
                reason='MERCHANT_CLEAR_DATA',
                product_count=len(active_products),
                order_count=len(active_orders),
                snapshot_json={
                    "products": [
                        {k: str(v) if isinstance(v, (datetime, Decimal)) else v for k, v in p.items()}
                        for p in active_products
                    ],
                    "orders": [
                        {k: str(v) if isinstance(v, (datetime, Decimal)) else v for k, v in o.items()}
                        for o in active_orders
                    ]
                }
            )

        # Delete all products, orders, and order items unconditionally
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Product.objects.all().delete()

        # Clear all derived risk assessments, exposure, decision records & sessions
        try:
            from supplyforge.models import (
                SlowMovingRiskAssessment, CapitalExposureAnalysisRecord,
                CapitalExposureItemRecord, DecisionRecord, RiskExplanationRecord,
                RiskMonitoringRun, IngestionSession, Sku, InventoryRecord
            )
            from supplyforge.models.decision import (
                DecisionExplanationRecord, DecisionEvidenceRecord, DecisionAuditEventRecord
            )
            SlowMovingRiskAssessment.objects.all().delete()
            CapitalExposureItemRecord.objects.all().delete()
            CapitalExposureAnalysisRecord.objects.all().delete()
            DecisionExplanationRecord.objects.all().delete()
            DecisionEvidenceRecord.objects.all().delete()
            DecisionAuditEventRecord.objects.all().delete()
            DecisionRecord.objects.all().delete()
            RiskExplanationRecord.objects.all().delete()
            RiskMonitoringRun.objects.all().delete()
            IngestionSession.objects.all().delete()
            Sku.objects.all().delete()
            InventoryRecord.objects.all().delete()
        except Exception as exc:
            print(f"[Clear Data] Warning clearing derived models: {exc}")

    @staticmethod
    def read_csv_in_chunks(file_path_or_stream, chunk_size=50000):
        """
        Requirement #24 Memory Streaming Engine:
        Reads CSV file/stream line-by-line using Python generator.
        Yields (header_line, chunk_lines) without reading entire file into RAM.
        """
        import io
        if isinstance(file_path_or_stream, str):
            f = io.open(file_path_or_stream, 'r', encoding='utf-8', errors='replace')
        elif hasattr(file_path_or_stream, 'read'):
            f = io.TextIOWrapper(file_path_or_stream, encoding='utf-8', errors='replace')
        else:
            f = file_path_or_stream

        try:
            header_line = f.readline()
            if not header_line:
                return

            chunk_lines = []
            for line in f:
                chunk_lines.append(line)
                if len(chunk_lines) >= chunk_size:
                    yield header_line, chunk_lines
                    chunk_lines = []
            if chunk_lines:
                yield header_line, chunk_lines
        finally:
            if isinstance(file_path_or_stream, str):
                f.close()

    @staticmethod
    def process_file_in_chunks(file_path, mapping_rule, user_id, session_type='INITIAL', force_reset=False, session_id=None, chunk_size=50000):
        """
        Requirement #24 & NFR-IMP-002: Bounded memory chunked streaming processing engine.
        Processes large CSV files in 50,000 row batches (CHUNK_ROW_SIZE), garbage collecting
        memory after each batch to prevent RAM exhaustion and application crashes.
        """
        import io
        from supplyforge.services.nfr_manager import NFRManager

        total_result = None
        for idx, (header_line, chunk_lines) in enumerate(DynamicFileImportService.read_csv_in_chunks(file_path, chunk_size=chunk_size)):
            chunk_csv = header_line + "".join(chunk_lines)
            chunk_io = io.BytesIO(chunk_csv.encode('utf-8'))

            chunk_session_type = session_type if idx == 0 else 'INCREMENTAL'
            chunk_force_reset = force_reset if idx == 0 else False

            res = DynamicFileImportService.process_batch_import(
                chunk_io, mapping_rule, user_id,
                session_type=chunk_session_type,
                force_reset=chunk_force_reset,
                session_id=session_id
            )
            total_result = res

            del chunk_csv, chunk_io, chunk_lines
            NFRManager.release_chunk_memory()

        return total_result or {"status": "REJECT", "error": "ERR_EMPTY_FILE"}

