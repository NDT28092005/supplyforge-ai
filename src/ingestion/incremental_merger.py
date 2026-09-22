"""
Incremental Upload & Dataset Merge Engine — Module 01 Data Ingestion (DAT-07)
================================================================================
Merges periodic sales/inventory batch updates with historical datasets without
requiring complete re-uploads. Guarantees deduplication, historical data preservation,
SKU mapping continuity, audit logging, and downstream recalculation signaling.

Outputs standard reports to:
  - reports/incremental_dataset.parquet (.csv fallback)
  - reports/dataset_version.json
  - reports/upload_metadata.json
  - reports/merge_report.json
  - reports/duplicate_records.json
  - reports/updated_records.json
  - reports/rejected_records.json
  - reports/dataset_audit_log.json
"""

import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.data_quality_validator import DataQualityValidator
from src.ingestion.sku_normalizer import SkuNormalizer


class IncrementalMerger:
    """Incremental Upload & Dataset Merge Engine (DAT-07)."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'
        self.upload_id = f"UPL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # ── 1. Time Range & Overlap Classification ────────────────────────

    @staticmethod
    def detect_time_range_and_overlap(
        new_dates: pd.Series, existing_dates: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """Determine min/max dates and classify overlap period."""
        p_new = pd.to_datetime(new_dates, errors='coerce').dropna().sort_values()
        if p_new.empty:
            return {
                'newMinDate': None,
                'newMaxDate': None,
                'overlapStatus': 'INVALID_DATES',
                'overlapDays': 0,
            }

        new_min = p_new.min()
        new_max = p_new.max()

        if existing_dates is None or len(existing_dates) == 0:
            return {
                'newMinDate': new_min.strftime('%Y-%m-%d'),
                'newMaxDate': new_max.strftime('%Y-%m-%d'),
                'overlapStatus': 'INITIAL_DATASET',
                'existingMinDate': None,
                'existingMaxDate': None,
                'overlapDays': 0,
            }

        p_ext = pd.to_datetime(existing_dates, errors='coerce').dropna().sort_values()
        ext_min = p_ext.min()
        ext_max = p_ext.max()

        if new_min > ext_max:
            overlap_status = 'NEW_PERIOD'
            overlap_days = 0
            if (new_min - ext_max).days > 7:
                overlap_status = 'MISSING_PERIOD'
        elif new_max < ext_min:
            overlap_status = 'HISTORICAL_BACKFILL'
            overlap_days = 0
        elif new_min >= ext_min and new_max <= ext_max:
            overlap_status = 'FULL_OVERLAP'
            overlap_days = (new_max - new_min).days + 1
        else:
            overlap_status = 'PARTIAL_OVERLAP'
            overlap_days = (min(new_max, ext_max) - max(new_min, ext_min)).days + 1

        return {
            'newMinDate': new_min.strftime('%Y-%m-%d'),
            'newMaxDate': new_max.strftime('%Y-%m-%d'),
            'existingMinDate': ext_min.strftime('%Y-%m-%d'),
            'existingMaxDate': ext_max.strftime('%Y-%m-%d'),
            'overlapStatus': overlap_status,
            'overlapDays': max(0, int(overlap_days)),
        }

    # ── 2. Incremental Merge Core Pipeline ────────────────────────────

    def merge_incremental_upload(
        self,
        new_df: pd.DataFrame,
        existing_df: Optional[pd.DataFrame] = None,
        mapping_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run complete incremental merge with deduplication, quality check, and SKU continuity."""
        new_df_copy = new_df.copy()

        # 1. Identify key columns
        sku_col, date_col, qty_col, price_col, order_id_col = self._extract_columns(new_df_copy, mapping_result)

        # 2. DAT-05 Data Quality Re-validation & Quarantine
        valid_df, rejected_records = self._revalidate_quality(new_df_copy, date_col, qty_col)

        if valid_df.empty:
            return self._empty_merge_report("File upload chứa 100% dữ liệu không hợp lệ.", quarantined_count=len(rejected_records), rejected_records=rejected_records)

        # 3. DAT-06 SKU Normalization Continuity
        normalizer = SkuNormalizer(session_id=self.session_id)
        norm_summary = normalizer.normalize_dataset(valid_df, mapping_result)
        valid_df = normalizer._last_normalized_df

        # 4. Generate Composite Business Keys
        valid_df['_record_key'] = self._generate_business_keys(valid_df, order_id_col, date_col)

        # Time range inspection
        time_info = self.detect_time_range_and_overlap(
            valid_df[date_col] if date_col and date_col in valid_df else valid_df.index,
            existing_df[date_col] if (existing_df is not None and date_col and date_col in existing_df) else None
        )

        inserted_records = []
        updated_records = []
        duplicate_records = []
        audit_log = []

        if existing_df is None or len(existing_df) == 0:
            # Initial dataset creation
            final_df = valid_df.copy()
            inserted_count = len(final_df)
            updated_count = 0
            duplicate_count = 0
            dataset_version = 'v1.0'
        else:
            ext_copy = existing_df.copy()

            # Ensure existing_df has business keys & canonical_sku_id
            if 'canonical_sku_id' not in ext_copy:
                ext_norm = normalizer.normalize_dataset(ext_copy, mapping_result)
                ext_copy = normalizer._last_normalized_df

            if '_record_key' not in ext_copy:
                ext_copy['_record_key'] = self._generate_business_keys(ext_copy, order_id_col, date_col)

            existing_key_map = {}
            for idx, r in ext_copy.iterrows():
                existing_key_map[r['_record_key']] = r

            new_record_rows = []

            for idx, row in valid_df.iterrows():
                rkey = row['_record_key']
                if rkey not in existing_key_map:
                    # New Record -> INSERT
                    new_record_rows.append(row)
                    inserted_records.append(row.to_dict())
                else:
                    # Record Key Exists -> Compare Values
                    ext_row = existing_key_map[rkey]
                    val_diffs = self._compare_record_values(row, ext_row, qty_col, price_col)

                    if not val_diffs:
                        # Identical -> SKIP (Duplicate)
                        duplicate_records.append(row.to_dict())
                    else:
                        # Value Changed -> UPDATE & Audit Log Mutation
                        new_record_rows.append(row)
                        updated_records.append({
                            'recordKey': rkey,
                            'uploadId': self.upload_id,
                            'timestamp': datetime.now().isoformat(),
                            'changes': val_diffs,
                        })
                        audit_log.append({
                            'uploadId': self.upload_id,
                            'timestamp': datetime.now().isoformat(),
                            'action': 'HISTORICAL_RECORD_UPDATED',
                            'recordKey': rkey,
                            'canonicalSkuId': str(row.get('canonical_sku_id', '')),
                            'changes': val_diffs,
                        })

            # Retain all existing historical records not updated
            updated_keys = {u['recordKey'] for u in updated_records}
            unchanged_ext_df = ext_copy[~ext_copy['_record_key'].isin(updated_keys)]

            new_insert_df = pd.DataFrame(new_record_rows) if new_record_rows else pd.DataFrame(columns=ext_copy.columns)

            # Combine unchanged historical + new inserts/updates
            final_df = pd.concat([unchanged_ext_df, new_insert_df], ignore_index=True)

            inserted_count = len(inserted_records)
            updated_count = len(updated_records)
            duplicate_count = len(duplicate_records)

            # Version increment
            dataset_version = 'v1.1'

        # 5. Build Recalculation Trigger Signal
        recalc_signal = {
            'recalculateSalesVelocity': True,
            'recalculateDSLS': True,
            'recalculateDemandPatterns': True,
            'recalculateSlowMovingRisk': True,
            'recalculateCapitalExposure': True,
            'affectedDateRange': {
                'startDate': time_info.get('newMinDate'),
                'endDate': time_info.get('newMaxDate'),
            },
            'affectedCanonicalSkus': list(valid_df['canonical_sku_id'].unique()) if 'canonical_sku_id' in valid_df else [],
        }

        # 6. Build Version & Metadata Objects
        upload_metadata = {
            'uploadId': self.upload_id,
            'filename': getattr(self, 'original_filename', 'incremental_upload.csv'),
            'uploadedAt': datetime.now().isoformat(),
            'dataMinDate': time_info.get('newMinDate'),
            'dataMaxDate': time_info.get('newMaxDate'),
            'totalUploadedRecords': len(new_df),
            'validRecords': len(valid_df),
            'newRecordsInserted': inserted_count,
            'historicalRecordsUpdated': updated_count,
            'duplicateRecordsSkipped': duplicate_count,
            'rejectedRecordsQuarantined': len(rejected_records),
            'overlapStatus': time_info.get('overlapStatus'),
            'datasetVersion': dataset_version,
            'status': 'SUCCESS',
        }

        version_info = {
            'currentVersion': dataset_version,
            'latestUploadId': self.upload_id,
            'totalCanonicalRecords': len(final_df),
            'totalCanonicalSkus': int(final_df['canonical_sku_id'].nunique()) if 'canonical_sku_id' in final_df else 0,
            'datasetMinDate': str(final_df[date_col].min()) if date_col and date_col in final_df else time_info.get('newMinDate'),
            'datasetMaxDate': str(final_df[date_col].max()) if date_col and date_col in final_df else time_info.get('newMaxDate'),
        }

        merge_report = {
            'sessionId': self.session_id,
            'uploadMetadata': upload_metadata,
            'versionInfo': version_info,
            'timeInfo': time_info,
            'recalculationTrigger': recalc_signal,
            'summary': {
                'inserted': inserted_count,
                'updated': updated_count,
                'duplicatesSkipped': duplicate_count,
                'quarantined': len(rejected_records),
            }
        }

        # Internal state for export
        self._last_final_df = final_df
        self._last_upload_metadata = upload_metadata
        self._last_version_info = version_info
        self._last_merge_report = merge_report
        self._last_duplicates = duplicate_records
        self._last_updates = updated_records
        self._last_rejected = rejected_records
        self._last_audit_log = audit_log

        return merge_report

    # ── Exporter: Save 8 Reports ──────────────────────────────────────

    def export_artifacts(self, merge_report: Dict[str, Any], output_dir: str = 'reports/') -> Dict[str, str]:
        """Export all 8 standard DAT-07 artifacts to reports/."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. incremental_dataset (Parquet + CSV)
        final_df = getattr(self, '_last_final_df', pd.DataFrame())
        df_csv_path = os.path.join(output_dir, 'incremental_dataset.csv')
        df_parquet_path = os.path.join(output_dir, 'incremental_dataset.parquet')
        if not final_df.empty:
            final_df.to_csv(df_csv_path, index=False, encoding='utf-8-sig')
            try:
                parquet_df = final_df.copy()
                for c in parquet_df.select_dtypes(include=['object']).columns:
                    parquet_df[c] = parquet_df[c].astype(str)
                parquet_df.to_parquet(df_parquet_path, index=False)
            except Exception as pe:
                # If pyarrow isn't installed or fails, write CSV duplicate as parquet extension fallback
                final_df.to_csv(df_parquet_path, index=False, encoding='utf-8-sig')

        # 2. dataset_version.json
        ver_path = os.path.join(output_dir, 'dataset_version.json')
        with open(ver_path, 'w', encoding='utf-8') as f:
            json.dump(merge_report.get('versionInfo', {}), f, indent=2, ensure_ascii=False)

        # 3. upload_metadata.json
        meta_path = os.path.join(output_dir, 'upload_metadata.json')
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(merge_report.get('uploadMetadata', {}), f, indent=2, ensure_ascii=False)

        # 4. merge_report.json
        report_path = os.path.join(output_dir, 'merge_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(merge_report, f, indent=2, ensure_ascii=False)

        # 5. duplicate_records.json
        dup_path = os.path.join(output_dir, 'duplicate_records.json')
        with open(dup_path, 'w', encoding='utf-8') as f:
            json.dump(getattr(self, '_last_duplicates', []), f, indent=2, ensure_ascii=False)

        # 6. updated_records.json
        upd_path = os.path.join(output_dir, 'updated_records.json')
        with open(upd_path, 'w', encoding='utf-8') as f:
            json.dump(getattr(self, '_last_updates', []), f, indent=2, ensure_ascii=False)

        # 7. rejected_records.json
        rej_path = os.path.join(output_dir, 'rejected_records.json')
        with open(rej_path, 'w', encoding='utf-8') as f:
            json.dump(getattr(self, '_last_rejected', []), f, indent=2, ensure_ascii=False)

        # 8. dataset_audit_log.json
        audit_path = os.path.join(output_dir, 'dataset_audit_log.json')
        with open(audit_path, 'w', encoding='utf-8') as f:
            json.dump(getattr(self, '_last_audit_log', []), f, indent=2, ensure_ascii=False)

        return {
            'incremental_dataset_csv': df_csv_path,
            'incremental_dataset_parquet': df_parquet_path,
            'dataset_version': ver_path,
            'upload_metadata': meta_path,
            'merge_report': report_path,
            'duplicate_records': dup_path,
            'updated_records': upd_path,
            'rejected_records': rej_path,
            'dataset_audit_log': audit_path,
        }

    # ── Internal Helpers ──────────────────────────────────────────────

    def _revalidate_quality(
        self, df: pd.DataFrame, date_col: Optional[str], qty_col: Optional[str]
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        valid_mask = pd.Series(True, index=df.index)
        rejected = []

        if date_col and date_col in df.columns:
            parsed_dates = pd.to_datetime(df[date_col], errors='coerce')
            invalid_dates = parsed_dates.isna()
            for idx in df[invalid_dates].index:
                valid_mask.loc[idx] = False
                rejected.append({
                    'rowIndex': int(idx),
                    'reason': 'Unparseable/Missing Date',
                    'rawRow': df.loc[idx].to_dict(),
                })

        if qty_col and qty_col in df.columns:
            qtys = pd.to_numeric(df[qty_col], errors='coerce')
            invalid_qtys = qtys.isna() | (qtys < 0)
            for idx in df[invalid_qtys].index:
                if valid_mask.loc[idx]:
                    valid_mask.loc[idx] = False
                    rejected.append({
                        'rowIndex': int(idx),
                        'reason': 'Invalid/Negative Quantity',
                        'rawRow': df.loc[idx].to_dict(),
                    })

        return df[valid_mask].copy(), rejected

    def _generate_business_keys(
        self, df: pd.DataFrame, order_id_col: Optional[str], date_col: Optional[str]
    ) -> pd.Series:
        keys = []
        for idx, row in df.iterrows():
            csku = str(row.get('canonical_sku_id', row.get('sku', 'SKU_UNK')))
            oid = str(row.get(order_id_col, 'ORD_AUTO')) if order_id_col and order_id_col in df.columns else f"ROW_{idx}"
            dt = str(row.get(date_col, 'DATE_UNK')) if date_col and date_col in df.columns else 'DATE_UNK'

            keys.append(f"{dt}_{oid}_{csku}")

        return pd.Series(keys, index=df.index)

    def _compare_record_values(
        self, new_row: pd.Series, ext_row: pd.Series, qty_col: Optional[str], price_col: Optional[str]
    ) -> Dict[str, Any]:
        diffs = {}
        for col in [qty_col, price_col]:
            if col and col in new_row and col in ext_row:
                new_v = new_row[col]
                ext_v = ext_row[col]
                if pd.notna(new_v) and pd.notna(ext_v) and str(new_v) != str(ext_v):
                    diffs[col] = {'oldValue': str(ext_v), 'newValue': str(new_v)}
        return diffs

    def _extract_columns(
        self, df: pd.DataFrame, mapping_result: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        sku_col = None
        date_col = None
        qty_col = None
        price_col = None
        order_id_col = None

        if mapping_result and 'mappings' in mapping_result:
            for item in mapping_result['mappings']:
                src = item.get('source_column')
                can = item.get('canonical_field')
                if src and src in df.columns:
                    if can == 'sku':
                        sku_col = src
                    elif can == 'date':
                        date_col = src
                    elif can == 'quantity':
                        qty_col = src
                    elif can == 'price':
                        price_col = src
                    elif can == 'order_id':
                        order_id_col = src

        for col in df.columns:
            cl = col.lower().strip()
            if not sku_col and any(k in cl for k in ('sku', 'item_id', 'product_id', 'code')):
                sku_col = col
            elif not date_col and any(k in cl for k in ('date', 'time', 'ngày')):
                date_col = col
            elif not qty_col and any(k in cl for k in ('quantity', 'qty', 'stock', 'sl')):
                qty_col = col
            elif not price_col and any(k in cl for k in ('price', 'giá')):
                price_col = col
            elif not order_id_col and any(k in cl for k in ('order_id', 'trans_id', 'mã_đơn')):
                order_id_col = col

        return sku_col, date_col, qty_col, price_col, order_id_col

    def _empty_merge_report(self, reason: str, quarantined_count: int = 0, rejected_records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        self._last_rejected = rejected_records or []
        return {
            'sessionId': self.session_id,
            'status': 'FAILED',
            'reason': reason,
            'summary': {'inserted': 0, 'updated': 0, 'duplicatesSkipped': 0, 'quarantined': quarantined_count},
        }
