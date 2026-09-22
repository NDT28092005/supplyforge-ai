"""
Automatic Column Mapping Engine — Module 01 Data Ingestion (TASK 03)
======================================================================
Multi-strategy detection pipeline:
  Level 1: Exact / Alias Dictionary Matching
  Level 2: Fuzzy String Similarity Matching
  Level 3: Gemini Semantic LLM Mapping
+ Context-Aware Verification via Sample Values
+ Required Field Validation & Audit Logging to reports/column_mapping.json
"""

import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from django.conf import settings


class ColumnMapper:
    """Multi-strategy column mapping engine for e-commerce datasets."""

    # ── Canonical Schema Definition ────────────────────────────────────
    CANONICAL_SCHEMA = {
        'sku': {
            'label': 'Mã SKU / Product ID',
            'required': True,
            'description': 'Ký tự hoặc mã số định danh duy nhất của sản phẩm/SKU',
        },
        'date': {
            'label': 'Ngày giao dịch',
            'required': True,
            'description': 'Ngày phát sinh đơn hàng, giao dịch hoặc ghi nhận tồn kho',
        },
        'quantity': {
            'label': 'Số lượng',
            'required': True,
            'description': 'Số lượng sản phẩm bán ra hoặc tồn kho trong giao dịch',
        },
        'product_name': {
            'label': 'Tên sản phẩm',
            'required': False,
            'description': 'Tên, tiêu đề hoặc mô tả đầy đủ của sản phẩm',
        },
        'price': {
            'label': 'Giá bán',
            'required': False,
            'description': 'Giá bán niêm yết hoặc giá đã giảm cho người mua',
        },
        'cost': {
            'label': 'Giá vốn',
            'required': False,
            'description': 'Giá nhập kho hoặc giá vốn của sản phẩm',
        },
        'category': {
            'label': 'Ngành hàng',
            'required': False,
            'description': 'Danh mục hoặc phân loại ngành hàng sản phẩm',
        },
        'brand': {
            'label': 'Thương hiệu',
            'required': False,
            'description': 'Nhãn hiệu hoặc nhà sản xuất',
        },
        'order_id': {
            'label': 'Mã đơn hàng',
            'required': False,
            'description': 'Mã định danh đơn hàng hoặc mã giao dịch',
        },
    }

    # ── Level 1 Alias Dictionary ──────────────────────────────────────
    ALIAS_DICT = {
        'sku': [
            'sku', 'item_id', 'itemid', 'product_id', 'productid', 'mã_sku', 'mã sku',
            'mã sp', 'mã_sp', 'mã hàng', 'mã_hàng', 'barcode', 'model_id', 'item_code', 'code'
        ],
        'date': [
            'date', 'order_date', 'orderdate', 'record_date', 'time', 'ngay', 'ngày',
            'ngày bán', 'ngày đặt hàng', 'ngày phát sinh', 'created_at', 'timestamp', 'thời gian'
        ],
        'quantity': [
            'quantity', 'qty', 'stock', 'so_luong', 'số lượng', 'sl', 'slb', 'slbh',
            'qty_sold', 'model_quantity_purchased', 'purchased_qty', 'tồn', 'tồn kho'
        ],
        'product_name': [
            'product_name', 'productname', 'item_name', 'name', 'tên sản phẩm', 'tên sp',
            'tên_sp', 'tên hàng', 'sản phẩm', 'title', 'model_name'
        ],
        'price': [
            'price', 'selling_price', 'sellingprice', 'giá bán', 'giá_bán', 'giá niêm yết',
            'unit_price', 'amount', 'model_discounted_price', 'giá'
        ],
        'cost': [
            'cost', 'cost_price', 'costprice', 'giá vốn', 'giá_vốn', 'vốn', 'gianhap',
            'cost_imputed', 'giá nhập'
        ],
        'category': [
            'category', 'ngành hàng', 'nganh_hang', 'nhóm hàng', 'danh mục', 'category_name'
        ],
        'brand': [
            'brand', 'thương hiệu', 'thuong_hieu', 'nhãn hiệu', 'brand_name'
        ],
        'order_id': [
            'order_id', 'orderid', 'mã đơn hàng', 'mã đơn', 'order_sn', '_id', 'transaction_id'
        ],
    }

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'
        self.user_overrides: Dict[str, str] = {}

    def map_columns(
        self,
        headers: List[str],
        sample_rows: Optional[List[List[str]]] = None,
        user_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute 3-level automatic column mapping pipeline + context verification."""

        if user_overrides:
            self.user_overrides.update(user_overrides)

        sample_rows = sample_rows or []
        column_mappings: List[Dict[str, Any]] = []

        mapped_canonical_fields: set = set()

        for idx, col in enumerate(headers):
            clean_col = str(col).strip()
            samples = [row[idx] for row in sample_rows if idx < len(row)]

            # Check user override first
            if clean_col in self.user_overrides or col in self.user_overrides:
                override_canonical = self.user_overrides.get(clean_col) or self.user_overrides.get(col)
                mapping_item = {
                    'source_column': clean_col,
                    'canonical_field': override_canonical,
                    'method': 'user_override',
                    'confidence': 1.0,
                    'status': 'AUTO_ACCEPTED',
                    'user_override': True,
                    'reasoning': 'Ánh xạ được người dùng chỉ định thủ công',
                }
                column_mappings.append(mapping_item)
                if override_canonical:
                    mapped_canonical_fields.add(override_canonical)
                continue

            # ── Level 1: Exact / Alias Dictionary Matching ────────────
            l1_canonical, l1_score = self._match_level1_alias(clean_col)
            if l1_canonical and l1_score >= 0.95:
                mapping_item = {
                    'source_column': clean_col,
                    'canonical_field': l1_canonical,
                    'method': 'exact_alias',
                    'confidence': l1_score,
                    'status': 'AUTO_ACCEPTED',
                    'user_override': False,
                    'reasoning': f'Khớp chính xác với từ điển chuẩn ({l1_canonical})',
                }
                # Context check
                mapping_item = self._verify_context(mapping_item, samples)
                column_mappings.append(mapping_item)
                if mapping_item['canonical_field']:
                    mapped_canonical_fields.add(mapping_item['canonical_field'])
                continue

            # ── Level 2: Fuzzy Similarity Matching ────────────────────
            l2_canonical, l2_score = self._match_level2_fuzzy(clean_col)
            if l2_canonical and l2_score >= 0.70:
                status_val = 'AUTO_ACCEPTED' if l2_score >= 0.90 else 'NEEDS_REVIEW'
                mapping_item = {
                    'source_column': clean_col,
                    'canonical_field': l2_canonical,
                    'method': 'fuzzy_matching',
                    'confidence': round(l2_score, 2),
                    'status': status_val,
                    'user_override': False,
                    'reasoning': f'Độ tương đồng chuỗi cao ({round(l2_score * 100, 1)}%) với từ điển',
                }
                mapping_item = self._verify_context(mapping_item, samples)
                column_mappings.append(mapping_item)
                if mapping_item['canonical_field']:
                    mapped_canonical_fields.add(mapping_item['canonical_field'])
                continue

            # ── Level 3: Gemini Semantic LLM Mapping ──────────────────
            l3_canonical, l3_score, l3_reason = self._match_level3_gemini(clean_col, samples)
            if l3_canonical:
                status_val = 'AUTO_ACCEPTED' if l3_score >= 0.90 else 'NEEDS_REVIEW'
                mapping_item = {
                    'source_column': clean_col,
                    'canonical_field': l3_canonical,
                    'method': 'semantic_llm',
                    'confidence': round(l3_score, 2),
                    'status': status_val,
                    'user_override': False,
                    'reasoning': l3_reason or 'Phân tích ngữ nghĩa bằng Trí tuệ nhân tạo (Gemini AI)',
                }
                mapping_item = self._verify_context(mapping_item, samples)
                column_mappings.append(mapping_item)
                if mapping_item['canonical_field']:
                    mapped_canonical_fields.add(mapping_item['canonical_field'])
                continue

            # ── Unresolved Column ─────────────────────────────────────
            column_mappings.append({
                'source_column': clean_col,
                'canonical_field': None,
                'method': 'unresolved',
                'confidence': 0.0,
                'status': 'UNRESOLVED',
                'user_override': False,
                'reasoning': 'Chưa xác định được ánh xạ phù hợp',
            })

        # ── Required Fields Check ──────────────────────────────────────
        required_fields = ['sku', 'date', 'quantity']
        missing_required = [f for f in required_fields if f not in mapped_canonical_fields]

        required_check = {
            'sku': 'sku' in mapped_canonical_fields,
            'date': 'date' in mapped_canonical_fields,
            'quantity': 'quantity' in mapped_canonical_fields,
            'missingRequiredFields': missing_required,
            'allPassed': len(missing_required) == 0,
        }

        # Overall Status Determination
        if missing_required:
            overall_status = 'BLOCKED'
            blocking_reason = f"Thiếu các trường bắt buộc cho phân tích: {', '.join(missing_required)}"
        elif any(m['status'] == 'UNRESOLVED' for m in column_mappings):
            overall_status = 'NEEDS_REVIEW'
            blocking_reason = None
        elif any(m['status'] == 'NEEDS_REVIEW' for m in column_mappings):
            overall_status = 'NEEDS_REVIEW'
            blocking_reason = None
        else:
            overall_status = 'AUTO_ACCEPTED'
            blocking_reason = None

        result_payload = {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'mappingStatus': overall_status,
            'blockingReason': blocking_reason,
            'requiredFieldsCheck': required_check,
            'mappings': column_mappings,
            'canonicalSchema': self.CANONICAL_SCHEMA,
        }

        return result_payload

    # ── Helper Level 1: Alias Dictionary Matching ─────────────────────

    def _match_level1_alias(self, col: str) -> Tuple[Optional[str], float]:
        col_clean = re.sub(r'[^\w\s]', '', col.lower()).strip()

        for canonical_field, aliases in self.ALIAS_DICT.items():
            for alias in aliases:
                alias_clean = re.sub(r'[^\w\s]', '', alias.lower()).strip()
                if col_clean == alias_clean:
                    return canonical_field, 0.98
                if alias_clean in col_clean or col_clean in alias_clean:
                    if len(col_clean) > 2 and len(alias_clean) > 2:
                        return canonical_field, 0.92
        return None, 0.0

    # ── Helper Level 2: Fuzzy Matching ────────────────────────────────

    def _match_level2_fuzzy(self, col: str) -> Tuple[Optional[str], float]:
        col_clean = col.lower().strip()
        best_canonical = None
        best_ratio = 0.0

        for canonical_field, aliases in self.ALIAS_DICT.items():
            for alias in aliases:
                ratio = SequenceMatcher(None, col_clean, alias.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_canonical = canonical_field

        return (best_canonical, best_ratio) if best_ratio >= 0.70 else (None, 0.0)

    # ── Helper Level 3: Gemini Semantic Mapping ───────────────────────

    def _match_level3_gemini(
        self, col: str, samples: List[str]
    ) -> Tuple[Optional[str], float, str]:
        api_key = getattr(settings, 'SUPPLYFORGE', {}).get('gemini', {}).get('api_key', '')
        if not api_key:
            return None, 0.0, 'No Gemini API Key available'

        model = getattr(settings, 'SUPPLYFORGE', {}).get('gemini', {}).get('model', 'gemini-1.5-flash')
        base_url = getattr(settings, 'SUPPLYFORGE', {}).get('gemini', {}).get('base_url', 'https://generativelanguage.googleapis.com')

        prompt = f"""Bạn là chuyên gia dữ liệu E-commerce. Hãy xác định cột dữ liệu sau đây tương ứng với trường chuẩn nào trong danh sách:
Danh sách các trường chuẩn (canonical fields):
- sku: Mã SKU / Product ID
- date: Ngày giao dịch / ngày bán
- quantity: Số lượng bán / tồn kho
- product_name: Tên sản phẩm
- price: Giá bán
- cost: Giá vốn
- category: Ngành hàng
- brand: Thương hiệu
- order_id: Mã đơn hàng

Tên cột cần phân tích: "{col}"
Các giá trị mẫu từ cột này: {json.dumps(samples[:5], ensure_ascii=False)}

Hãy trả về DUY NHẤT một JSON object định dạng:
{{
  "canonical_field": "tên_trường_chuẩn_hoặc_null",
  "confidence": 0.85,
  "reasoning": "Giải thích lý do nhận diện ngắn gọn bằng tiếng Việt"
}}"""

        try:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1}
            }
            url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
            headers_http = {"Content-Type": "application/json"}

            resp = requests.post(url, json=payload, headers=headers_http, timeout=15)
            if resp.status_code == 200:
                res_data = resp.json()
                if "candidates" in res_data:
                    text_content = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    json_match = re.search(r'\{.*\}', text_content, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        field = parsed.get("canonical_field")
                        conf = float(parsed.get("confidence", 0.8))
                        reason = parsed.get("reasoning", "Semantic matching via Gemini AI")
                        if field in self.CANONICAL_SCHEMA:
                            return field, conf, reason
        except Exception as e:
            pass

        return None, 0.0, 'Gemini call unfulfilled'

    # ── Helper: Context Verification with Sample Values ───────────────

    def _verify_context(self, mapping_item: Dict[str, Any], samples: List[str]) -> Dict[str, Any]:
        """Validate mapped canonical field against data types of sample values."""
        canonical = mapping_item.get('canonical_field')
        if not canonical or not samples:
            return mapping_item

        clean_samples = [str(s).strip() for s in samples if str(s).strip() != '']
        if not clean_samples:
            return mapping_item

        # Date validation
        if canonical == 'date':
            date_matches = 0
            for s in clean_samples[:5]:
                if re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}', s):
                    date_matches += 1
            if date_matches == 0:
                # Penalty if non-date sample
                mapping_item['confidence'] = max(0.50, mapping_item['confidence'] - 0.25)
                mapping_item['status'] = 'NEEDS_REVIEW'
                mapping_item['reasoning'] += ' (Cảnh báo context: Mẫu giá trị không khớp định dạng ngày tháng)'

        # Quantity / Price / Cost numeric validation
        elif canonical in ('quantity', 'price', 'cost'):
            num_matches = 0
            for s in clean_samples[:5]:
                clean_num = re.sub(r'[^\d.]', '', s)
                if clean_num:
                    num_matches += 1
            if num_matches == 0:
                mapping_item['confidence'] = max(0.50, mapping_item['confidence'] - 0.25)
                mapping_item['status'] = 'NEEDS_REVIEW'
                mapping_item['reasoning'] += ' (Cảnh báo context: Mẫu giá trị không khớp kiểu số)'

        return mapping_item

    # ── Export Audit Log ──────────────────────────────────────────────

    def export_audit_log(self, mapping_result: Dict[str, Any], output_dir: str = 'reports/') -> str:
        """Export column_mapping.json audit log to output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, 'column_mapping.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(mapping_result, f, indent=2, ensure_ascii=False)
        return file_path
