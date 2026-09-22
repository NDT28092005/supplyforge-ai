"""
SKU Normalization & Identity Resolution Engine — Module 01 Data Ingestion (DAT-06)
===================================================================================
Standardizes product identities across heterogeneous merchant records without
overwriting raw original SKU attributes.

Outputs standard reports to:
  - reports/normalized_dataset.parquet (.csv fallback)
  - reports/sku_master.json
  - reports/sku_mapping.json
  - reports/sku_match_candidates.json
  - reports/sku_merge_audit_log.json
"""

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class SkuNormalizer:
    """SKU Normalization & Product Identity Resolution Engine (DAT-06)."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'
        self.audit_logs: List[Dict[str, Any]] = []

    # ── 1. String Normalization Pipeline ──────────────────────────────

    @staticmethod
    def normalize_text(text: str) -> str:
        """Clean and normalize string (case, NFC unicode, unit contractions, whitespace)."""
        if not text or pd.isna(text):
            return ""

        s = str(text).strip()
        # Unicode NFC normalization
        s = unicodedata.normalize('NFC', s)
        # Lowercase
        s = s.lower()

        # Unit standardization (e.g. 250ml -> 250 ml, 1kg -> 1 kg)
        s = re.sub(r'(\d+)\s*(ml|l|g|kg|oz|cm|mm|m)\b', r'\1 \2', s)

        # Replace non-alphanumeric punctuation (except space & numbers) with single space
        s = re.sub(r'[^\w\s]', ' ', s)

        # Collapse multiple spaces
        s = re.sub(r'\s+', ' ', s).strip()

        return s

    @staticmethod
    def strip_vietnamese_accents(text: str) -> str:
        """Strip Vietnamese accents for fuzzy string similarity comparison."""
        s = SkuNormalizer.normalize_text(text)
        s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
        s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
        s = re.sub(r'[ìíịỉĩ]', 'i', s)
        s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
        s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
        s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
        s = re.sub(r'[đ]', 'd', s)
        return s

    # ── 2. Variant Token Extraction & Safety Check ────────────────────

    @staticmethod
    def extract_variant_tokens(text: str) -> Dict[str, str]:
        """Extract volume, weight, size, or color tokens to prevent false merges."""
        tokens = {}
        s = SkuNormalizer.normalize_text(text)

        # Volume / Weight regex
        vol_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(ml|l|g|kg|oz)\b', s)
        if vol_match:
            tokens['volume_weight'] = f"{vol_match.group(1)}{vol_match.group(2)}"

        # Size regex (Size S, M, L, XL, 36, 37, 38, etc.)
        size_match = re.search(r'\b(?:size|sz)\s*([a-z0-9]+)\b', s)
        if size_match:
            tokens['size'] = size_match.group(1)

        return tokens

    @staticmethod
    def has_variant_conflict(tokens_a: Dict[str, str], tokens_b: Dict[str, str]) -> bool:
        """Return True if variant tokens (volume/weight/size) explicitly disagree."""
        for key in ('volume_weight', 'size'):
            val_a = tokens_a.get(key)
            val_b = tokens_b.get(key)
            if val_a and val_b and val_a != val_b:
                return True
        return False

    # ── 3. Similarity Calculation ─────────────────────────────────────

    @staticmethod
    def calculate_similarity(str_a: str, str_b: str) -> float:
        """Calculate string similarity score (0.0 - 1.0) using normalized SequenceMatcher."""
        norm_a = SkuNormalizer.strip_vietnamese_accents(str_a)
        norm_b = SkuNormalizer.strip_vietnamese_accents(str_b)

        if norm_a == norm_b:
            return 1.0

        # Levenshtein sequence ratio
        ratio = SequenceMatcher(None, norm_a, norm_b).ratio()

        # Token set similarity
        words_a = set(norm_a.split())
        words_b = set(norm_b.split())
        jaccard = len(words_a & words_b) / max(1, len(words_a | words_b))

        return float(round((ratio * 0.6) + (jaccard * 0.4), 4))

    # ── 4. Main Dataset Normalization Pipeline ───────────────────────

    def normalize_dataset(
        self,
        df: pd.DataFrame,
        mapping_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run complete DAT-06 SKU Normalization pipeline on dataset."""
        df_copy = df.copy()

        # Identify source columns
        sku_col, name_col, price_col, qty_col = self._extract_columns(df_copy, mapping_result)

        # 1. Group distinct original SKUs / product names
        df_copy['_orig_sku'] = df_copy[sku_col].astype(str).str.strip() if sku_col else 'SKU_UNKNOWN'
        df_copy['_orig_name'] = df_copy[name_col].astype(str).str.strip() if name_col else df_copy['_orig_sku']

        distinct_skus = df_copy.groupby(['_orig_sku', '_orig_name']).size().reset_index(name='record_count')
        if qty_col and qty_col in df_copy:
            sales_agg = df_copy.groupby(['_orig_sku', '_orig_name'])[qty_col].apply(
                lambda x: pd.to_numeric(x, errors='coerce').fillna(0).sum()
            ).reset_index(name='total_sales')
            distinct_skus = pd.merge(distinct_skus, sales_agg, on=['_orig_sku', '_orig_name'], how='left')
        else:
            distinct_skus['total_sales'] = 0.0

        # Prepare normalized strings & tokens
        distinct_skus['norm_name'] = distinct_skus['_orig_name'].apply(self.normalize_text)
        distinct_skus['unaccent_name'] = distinct_skus['_orig_name'].apply(self.strip_vietnamese_accents)
        distinct_skus['variant_tokens'] = distinct_skus['_orig_name'].apply(self.extract_variant_tokens)

        # 2. Match & Assign Canonical SKU Identity
        n_items = len(distinct_skus)
        canonical_assignments: Dict[int, str] = {}
        match_candidates: List[Dict[str, Any]] = []
        cluster_map: Dict[str, List[int]] = {}

        # First pass: Exact match clustering on norm_name
        for idx, row in distinct_skus.iterrows():
            norm_key = row['norm_name'] or row['_orig_sku']
            if norm_key not in cluster_map:
                cluster_map[norm_key] = []
            cluster_map[norm_key].append(idx)

        # Generate canonical SKU IDs per cluster
        canonical_sku_counter = 1
        for norm_key, idx_list in cluster_map.items():
            csku_id = f"CSKU_{canonical_sku_counter:04d}"
            canonical_sku_counter += 1
            for idx in idx_list:
                canonical_assignments[idx] = csku_id

        # Second pass: Fuzzy matching across distinct cluster representatives
        cluster_keys = list(cluster_map.keys())
        for i in range(len(cluster_keys)):
            for j in range(i + 1, len(cluster_keys)):
                key_i = cluster_keys[i]
                key_j = cluster_keys[j]

                idx_i = cluster_map[key_i][0]
                idx_j = cluster_map[key_j][0]

                item_i = distinct_skus.loc[idx_i]
                item_j = distinct_skus.loc[idx_j]

                # Variant safety check
                if self.has_variant_conflict(item_i['variant_tokens'], item_j['variant_tokens']):
                    continue  # Skip merging distinct variants

                sim_score = self.calculate_similarity(item_i['_orig_name'], item_j['_orig_name'])

                if sim_score >= 0.90:
                    # HIGH_CONFIDENCE_MATCH -> Auto Merge under item_i's CSKU
                    csku_target = canonical_assignments[idx_i]
                    for idx_to_reassign in cluster_map[key_j]:
                        canonical_assignments[idx_to_reassign] = csku_target

                    self.audit_logs.append({
                        'timestamp': datetime.now().isoformat(),
                        'action': 'AUTO_MERGE_HIGH_CONFIDENCE',
                        'canonicalSkuId': csku_target,
                        'originalSkuA': item_i['_orig_sku'],
                        'originalSkuB': item_j['_orig_sku'],
                        'productNameA': item_i['_orig_name'],
                        'productNameB': item_j['_orig_name'],
                        'similarityScore': sim_score,
                    })

                elif sim_score >= 0.75:
                    # REVIEW_REQUIRED -> Flag for Merchant Review
                    match_candidates.append({
                        'candidatePairId': f"PAIR_{idx_i}_{idx_j}",
                        'canonicalSkuIdA': canonical_assignments[idx_i],
                        'canonicalSkuIdB': canonical_assignments[idx_j],
                        'originalSkuA': item_i['_orig_sku'],
                        'originalSkuB': item_j['_orig_sku'],
                        'productNameA': item_i['_orig_name'],
                        'productNameB': item_j['_orig_name'],
                        'similarityScore': sim_score,
                        'matchType': 'REVIEW_REQUIRED',
                        'status': 'PENDING_REVIEW',
                    })

        distinct_skus['canonical_sku_id'] = [canonical_assignments[i] for i in range(n_items)]

        # 3. Link Canonical SKU ID back to raw dataset (preserving raw original_sku)
        mapping_lookup = dict(zip(zip(distinct_skus['_orig_sku'], distinct_skus['_orig_name']), distinct_skus['canonical_sku_id']))
        df_copy['canonical_sku_id'] = [mapping_lookup.get((r['_orig_sku'], r['_orig_name']), 'CSKU_0000') for _, r in df_copy.iterrows()]
        df_copy['normalized_product_name'] = df_copy['_orig_name'].apply(self.normalize_text)

        # 4. Build Master Catalog (sku_master)
        sku_master = self._build_sku_master(df_copy, distinct_skus, qty_col, price_col)

        # 5. Build Lookup Mapping (sku_mapping)
        sku_mapping = distinct_skus[['_orig_sku', '_orig_name', 'canonical_sku_id', 'norm_name']].to_dict(orient='records')

        summary = {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'totalOriginalRecords': len(df_copy),
            'totalOriginalSkus': int(distinct_skus['_orig_sku'].nunique()),
            'totalCanonicalSkus': int(distinct_skus['canonical_sku_id'].nunique()),
            'autoMergedCount': int(n_items - distinct_skus['canonical_sku_id'].nunique()),
            'pendingReviewCandidatesCount': len(match_candidates),
            'candidates': match_candidates,
            'skuMaster': sku_master,
            'skuMapping': sku_mapping,
        }

        # Store internal state for exporter
        self._last_normalized_df = df_copy
        self._last_summary = summary
        self._last_candidates = match_candidates

        return summary

    # ── Merchant Decision Handlers ────────────────────────────────────

    def handle_merchant_merge(
        self, canonical_sku_id: str, child_sku_id: str, candidate_pair_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Merchant confirms merging child_sku_id into canonical_sku_id."""
        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': 'MERCHANT_MERGE_CONFIRMED',
            'canonicalSkuId': canonical_sku_id,
            'mergedChildSkuId': child_sku_id,
            'candidatePairId': candidate_pair_id,
            'status': 'MERGED',
        }
        self.audit_logs.append(audit_entry)
        return audit_entry

    def handle_merchant_undo(
        self, canonical_sku_id: str, child_sku_id: str
    ) -> Dict[str, Any]:
        """Merchant undoes a previous merge decision."""
        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': 'MERCHANT_MERGE_UNDONE',
            'canonicalSkuId': canonical_sku_id,
            'unmergedChildSkuId': child_sku_id,
            'status': 'SEPARATED',
        }
        self.audit_logs.append(audit_entry)
        return audit_entry

    # ── Exporter: Save Reports ────────────────────────────────────────

    def export_artifacts(self, summary_result: Dict[str, Any], output_dir: str = 'reports/') -> Dict[str, str]:
        """Export all 5 standard DAT-06 artifacts to reports/."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. normalized_dataset (Parquet + CSV)
        norm_df = getattr(self, '_last_normalized_df', pd.DataFrame())
        norm_csv_path = os.path.join(output_dir, 'normalized_dataset.csv')
        norm_parquet_path = os.path.join(output_dir, 'normalized_dataset.parquet')
        if not norm_df.empty:
            norm_df.to_csv(norm_csv_path, index=False, encoding='utf-8-sig')
            try:
                norm_df.to_parquet(norm_parquet_path, index=False)
            except Exception:
                pass

        # 2. sku_master.json
        sku_master_path = os.path.join(output_dir, 'sku_master.json')
        with open(sku_master_path, 'w', encoding='utf-8') as f:
            json.dump(summary_result.get('skuMaster', []), f, indent=2, ensure_ascii=False)

        # 3. sku_mapping.json
        sku_mapping_path = os.path.join(output_dir, 'sku_mapping.json')
        with open(sku_mapping_path, 'w', encoding='utf-8') as f:
            json.dump(summary_result.get('skuMapping', []), f, indent=2, ensure_ascii=False)

        # 4. sku_match_candidates.json
        candidates_path = os.path.join(output_dir, 'sku_match_candidates.json')
        with open(candidates_path, 'w', encoding='utf-8') as f:
            json.dump(summary_result.get('candidates', []), f, indent=2, ensure_ascii=False)

        # 5. sku_merge_audit_log.json
        audit_log_path = os.path.join(output_dir, 'sku_merge_audit_log.json')
        with open(audit_log_path, 'w', encoding='utf-8') as f:
            json.dump(self.audit_logs, f, indent=2, ensure_ascii=False)

        return {
            'normalized_dataset_csv': norm_csv_path,
            'normalized_dataset_parquet': norm_parquet_path,
            'sku_master': sku_master_path,
            'sku_mapping': sku_mapping_path,
            'sku_match_candidates': candidates_path,
            'sku_merge_audit_log': audit_log_path,
        }

    # ── Internal Helpers ──────────────────────────────────────────────

    def _build_sku_master(
        self, df: pd.DataFrame, distinct_skus: pd.DataFrame, qty_col: Optional[str], price_col: Optional[str]
    ) -> List[Dict[str, Any]]:
        sku_master_records = []
        grouped = df.groupby('canonical_sku_id')

        for csku_id, group in grouped:
            orig_skus = list(group['_orig_sku'].unique())
            orig_names = list(group['_orig_name'].unique())

            tot_qty = float(pd.to_numeric(group[qty_col], errors='coerce').fillna(0).sum()) if qty_col and qty_col in group.columns else 0.0
            avg_price = float(pd.to_numeric(group[price_col], errors='coerce').dropna().mean()) if price_col and price_col in group.columns else 0.0

            sku_master_records.append({
                'canonicalSkuId': csku_id,
                'canonicalName': orig_names[0] if orig_names else csku_id,
                'originalSkuVariantsCount': len(orig_skus),
                'originalSkuList': orig_skus,
                'originalProductNameList': orig_names,
                'totalSalesQuantity': tot_qty,
                'averagePrice': round(avg_price, 2),
                'recordCount': len(group),
            })

        return sku_master_records

    def _extract_columns(
        self, df: pd.DataFrame, mapping_result: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        sku_col = None
        name_col = None
        price_col = None
        qty_col = None

        if mapping_result and 'mappings' in mapping_result:
            for item in mapping_result['mappings']:
                src = item.get('source_column')
                can = item.get('canonical_field')
                if src and src in df.columns:
                    if can == 'sku':
                        sku_col = src
                    elif can == 'product_name':
                        name_col = src
                    elif can == 'price':
                        price_col = src
                    elif can == 'quantity':
                        qty_col = src

        # Fallback inspection
        for col in df.columns:
            cl = col.lower().strip()
            if not sku_col and any(k in cl for k in ('sku', 'item_id', 'product_id', 'mã_sp', 'mã sku', 'code')):
                sku_col = col
            elif not name_col and any(k in cl for k in ('product_name', 'item_name', 'name', 'tên', 'product', 'p_name')):
                name_col = col
            elif not price_col and any(k in cl for k in ('price', 'selling_price', 'giá bán', 'giá')):
                price_col = col
            elif not qty_col and any(k in cl for k in ('quantity', 'qty', 'stock', 'số lượng', 'sl')):
                qty_col = col

        return sku_col, name_col, price_col, qty_col
