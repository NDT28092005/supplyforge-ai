"""
Data Quality Validation Engine — Module 01 Data Ingestion (DAT-05)
===================================================================
Evaluates actual dataset cleanliness, consistency, and reliability for
Slow-Moving Product Risk Detection without using LLMs or altering raw data.

Outputs standard reports to:
  - reports/data_quality_report.json
  - reports/data_quality_summary.json
  - reports/sku_quality_profile.parquet (.csv fallback)
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class DataQualityValidator:
    """Deterministic Data Quality Validation Engine (DAT-05)."""

    MISSING_THRESHOLDS = {
        'sku': 0.00,        # 0% missing allowed for required fields
        'date': 0.00,
        'quantity': 0.01,
        'price': 0.05,
        'cost': 0.10,
        'product_name': 0.05,
        'category': 0.10,
        'brand': 0.10,
    }

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def validate_quality(
        self,
        df: pd.DataFrame,
        mapping_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute full 13-dimension deterministic data quality evaluation."""
        total_records = len(df)
        if total_records == 0:
            return self._empty_report()

        # Map canonical names to source column names
        source_to_canonical, canonical_to_source = self._extract_column_mappings(df, mapping_result)

        # ── 1. Data Completeness Validation ───────────────────────────
        completeness = self._validate_completeness(df, canonical_to_source, total_records)

        # ── 2. Duplicate Detection ────────────────────────────────────
        duplicates = self._detect_duplicates(df, canonical_to_source, total_records)

        # ── 3. Invalid Value Detection ────────────────────────────────
        invalid_values = self._detect_invalid_values(df, canonical_to_source, total_records)

        # ── 4. Outlier & Anomaly Detection ────────────────────────────
        anomalies = self._detect_anomalies(df, canonical_to_source)

        # ── 5. Temporal Consistency Validation ────────────────────────
        temporal = self._validate_temporal_consistency(df, canonical_to_source)

        # ── 6. SKU Consistency Validation ─────────────────────────────
        sku_consistency = self._validate_sku_consistency(df, canonical_to_source)

        # ── 7. Numerical Consistency Validation ───────────────────────
        numerical_consistency = self._validate_numerical_consistency(df, canonical_to_source, total_records)

        # ── 8. Demand Data Quality Validation ─────────────────────────
        demand_quality = self._validate_demand_quality(df, canonical_to_source)

        # ── 9. SKU-Level Quality Profile ──────────────────────────────
        sku_profile_df = self._generate_sku_quality_profile(df, canonical_to_source, temporal)

        # ── 10. Deterministic Data Quality Score (0 - 100) ────────────
        scores = self._calculate_deterministic_score(
            completeness=completeness,
            duplicates=duplicates,
            invalid_values=invalid_values,
            temporal=temporal,
            numerical_consistency=numerical_consistency,
            freshness_days=1,
            is_schema_valid=bool(mapping_result and mapping_result.get('mappings'))
        )
        overall_score = scores['overallScore']

        # ── 11. Quality Status Classification ──────────────────────────
        if overall_score >= 95.0:
            quality_status = 'EXCELLENT'
        elif overall_score >= 85.0:
            quality_status = 'GOOD'
        elif overall_score >= 70.0:
            quality_status = 'WARNING'
        else:
            quality_status = 'CRITICAL'

        # ── 12 & 13. Slow-Moving Readiness & Capability Boundaries ────
        has_sku = 'sku' in canonical_to_source and canonical_to_source['sku'] in df.columns
        has_date = 'date' in canonical_to_source and canonical_to_source['date'] in df.columns
        has_qty = 'quantity' in canonical_to_source and canonical_to_source['quantity'] in df.columns
        has_cost = 'cost' in canonical_to_source and canonical_to_source['cost'] in df.columns
        has_inv = 'inventory' in canonical_to_source and canonical_to_source['inventory'] in df.columns

        obs_days = temporal.get('observationPeriodDays', 0)

        ready_reasons = []
        unready_reasons = []

        if has_sku:
            ready_reasons.append("Trường Mã SKU hợp lệ")
        else:
            unready_reasons.append("Thiếu trường Mã SKU")

        if has_date:
            ready_reasons.append("Trường Ngày giao dịch hợp lệ")
        else:
            unready_reasons.append("Thiếu trường Ngày giao dịch")

        if has_qty:
            ready_reasons.append("Trường Số lượng hợp lệ (bao gồm zero-sales)")
        else:
            unready_reasons.append("Thiếu trường Số lượng")

        if obs_days >= 14:
            ready_reasons.append(f"Khoảng thời gian quan sát đủ ({obs_days} ngày >= 14 ngày)")
        else:
            unready_reasons.append(f"Khoảng thời gian quan sát quá ngắn ({obs_days} ngày < 14 ngày)")

        slow_moving_ready = has_sku and has_date and has_qty and (obs_days >= 14 or obs_days == 0)

        # Inventory Risk capability assessment
        inventory_notice = None
        if not has_inv:
            inventory_notice = (
                "Dữ liệu không bao gồm trường Tồn kho thực tế (Inventory Snapshot). "
                "Hệ thống tự động phân tích Rủi ro Hàng bán chậm dựa trên hành vi bán hàng lịch sử, "
                "nhưng không thể xác nhận trực tiếp số lượng tồn kho vật lý thực tế."
            )

        report = {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'totalRecords': total_records,
            'totalSkus': int(sku_profile_df['sku'].nunique()) if not sku_profile_df.empty else 0,
            'datasetQualityScore': overall_score,
            'qualityStatus': quality_status,
            'scoreBreakdown': scores,
            'completeness': completeness,
            'duplicates': duplicates,
            'invalidValues': invalid_values,
            'anomalies': anomalies,
            'temporalConsistency': temporal,
            'skuConsistency': sku_consistency,
            'numericalConsistency': numerical_consistency,
            'demandQuality': demand_quality,
            'slowMovingDetectionReady': slow_moving_ready,
            'readinessReasons': ready_reasons if slow_moving_ready else unready_reasons,
            'physicalInventoryRiskReady': has_inv,
            'financialValuationReady': has_cost,
            'inventoryNotice': inventory_notice,
            'skuQualityProfileSummary': {
                'totalSkusProfiled': len(sku_profile_df),
                'goodQualitySkus': int((sku_profile_df['quality_status'] == 'GOOD').sum()) if not sku_profile_df.empty else 0,
                'warningQualitySkus': int((sku_profile_df['quality_status'] == 'WARNING').sum()) if not sku_profile_df.empty else 0,
                'criticalQualitySkus': int((sku_profile_df['quality_status'] == 'CRITICAL').sum()) if not sku_profile_df.empty else 0,
            },
        }

        # Store sku_profile_df internally for export
        self._last_sku_profile_df = sku_profile_df
        return report

    # ── Helper: Column Mapping Extractor ──────────────────────────────

    def _extract_column_mappings(
        self, df: pd.DataFrame, mapping_result: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        src_to_can = {}
        can_to_src = {}

        if mapping_result and 'mappings' in mapping_result:
            for item in mapping_result['mappings']:
                src = item.get('source_column')
                can = item.get('canonical_field')
                if src and can and src in df.columns:
                    src_to_can[src] = can
                    if can not in can_to_src:
                        can_to_src[can] = src

        # Heuristic fallbacks for common names if not explicitly mapped
        for col in df.columns:
            col_l = col.lower().strip()
            if col not in src_to_can:
                if col_l in ('sku', 'item_id', 'product_id', 'mã_sp', 'mã sku'):
                    can_to_src.setdefault('sku', col)
                elif col_l in ('date', 'order_date', 'record_date', 'ngày', 'thời gian'):
                    can_to_src.setdefault('date', col)
                elif col_l in ('quantity', 'qty', 'stock', 'số lượng', 'sl'):
                    can_to_src.setdefault('quantity', col)
                elif col_l in ('price', 'selling_price', 'giá', 'giá bán'):
                    can_to_src.setdefault('price', col)
                elif col_l in ('cost', 'cost_price', 'giá vốn'):
                    can_to_src.setdefault('cost', col)

        return src_to_can, can_to_src

    # ── 1. Completeness ───────────────────────────────────────────────

    def _validate_completeness(
        self, df: pd.DataFrame, can_to_src: Dict[str, str], total_records: int
    ) -> Dict[str, Any]:
        completeness_details = {}
        total_missing_rate = 0.0
        count_fields = 0

        canonical_fields = ['sku', 'date', 'quantity', 'price', 'cost', 'product_name', 'category', 'brand']

        for field in canonical_fields:
            if field in can_to_src and can_to_src[field] in df.columns:
                col_name = can_to_src[field]
                series = df[col_name]
                null_count = int(series.isna().sum())
                null_rate = round(null_count / total_records, 4)

                zero_count = int((series == 0).sum()) if pd.api.types.is_numeric_dtype(series) else 0
                zero_rate = round(zero_count / total_records, 4)

                threshold = self.MISSING_THRESHOLDS.get(field, 0.05)
                if null_rate == 0:
                    status = 'COMPLETE'
                elif null_rate <= threshold:
                    status = 'ACCEPTABLE'
                else:
                    status = 'WARNING' if null_rate <= 0.20 else 'CRITICAL'

                completeness_details[field] = {
                    'sourceColumn': col_name,
                    'nullCount': null_count,
                    'nullRate': null_rate,
                    'zeroCount': zero_count,
                    'zeroRate': zero_rate,
                    'nonNullCount': total_records - null_count,
                    'status': status,
                }
                total_missing_rate += null_rate
                count_fields += 1
            else:
                completeness_details[field] = {
                    'sourceColumn': None,
                    'nullCount': total_records,
                    'nullRate': 1.0,
                    'zeroCount': 0,
                    'zeroRate': 0.0,
                    'nonNullCount': 0,
                    'status': 'MISSING',
                }

        avg_missing_rate = round(total_missing_rate / max(1, count_fields), 4)
        return {
            'fields': completeness_details,
            'averageMissingRate': avg_missing_rate,
            'completenessPct': round((1.0 - avg_missing_rate) * 100, 2),
        }

    # ── 2. Duplicate Detection ────────────────────────────────────────

    def _detect_duplicates(
        self, df: pd.DataFrame, can_to_src: Dict[str, str], total_records: int
    ) -> Dict[str, Any]:
        # Exact duplicate
        exact_dup_count = int(df.duplicated().sum())
        exact_dup_rate = round(exact_dup_count / total_records, 4)

        # Business key duplicate
        bk_columns = []
        if 'order_id' in can_to_src and can_to_src['order_id'] in df.columns:
            bk_columns.append(can_to_src['order_id'])
        if 'sku' in can_to_src and can_to_src['sku'] in df.columns:
            bk_columns.append(can_to_src['sku'])
        if 'date' in can_to_src and can_to_src['date'] in df.columns and len(bk_columns) < 2:
            bk_columns.append(can_to_src['date'])

        business_dup_count = 0
        if len(bk_columns) >= 2:
            business_dup_count = int(df.duplicated(subset=bk_columns).sum())

        business_dup_rate = round(business_dup_count / total_records, 4)

        return {
            'exactDuplicateCount': exact_dup_count,
            'exactDuplicateRate': exact_dup_rate,
            'businessKeyColumns': bk_columns,
            'businessDuplicateCount': business_dup_count,
            'businessDuplicateRate': business_dup_rate,
            'uniquenessPct': round((1.0 - max(exact_dup_rate, business_dup_rate)) * 100, 2),
        }

    # ── 3. Invalid Values ─────────────────────────────────────────────

    def _detect_invalid_values(
        self, df: pd.DataFrame, can_to_src: Dict[str, str], total_records: int
    ) -> Dict[str, Any]:
        results = {}

        # Quantity
        if 'quantity' in can_to_src and can_to_src['quantity'] in df.columns:
            qty_col = can_to_src['quantity']
            qty = pd.to_numeric(df[qty_col], errors='coerce')
            neg_count = int((qty < 0).sum())
            zero_count = int((qty == 0).sum())  # quantity = 0 is VALID DATA
            null_count = int(qty.isna().sum())

            results['quantity'] = {
                'sourceColumn': qty_col,
                'negativeCount': neg_count,
                'negativeRate': round(neg_count / total_records, 4),
                'zeroSalesCount': zero_count,  # Preserved as valid
                'zeroSalesIsValid': True,
                'nullCount': null_count,
                'status': 'WARNING' if neg_count > 0 else 'VALID',
            }

        # Price
        if 'price' in can_to_src and can_to_src['price'] in df.columns:
            pr_col = can_to_src['price']
            price = pd.to_numeric(df[pr_col], errors='coerce')
            invalid_price_count = int((price <= 0).sum())
            results['price'] = {
                'sourceColumn': pr_col,
                'invalidOrZeroCount': invalid_price_count,
                'invalidRate': round(invalid_price_count / total_records, 4),
                'status': 'WARNING' if invalid_price_count > 0 else 'VALID',
            }

        # Cost
        if 'cost' in can_to_src and can_to_src['cost'] in df.columns:
            cost_col = can_to_src['cost']
            cost = pd.to_numeric(df[cost_col], errors='coerce')
            invalid_cost_count = int((cost <= 0).sum())
            results['cost'] = {
                'sourceColumn': cost_col,
                'invalidOrZeroCount': invalid_cost_count,
                'invalidRate': round(invalid_cost_count / total_records, 4),
                'status': 'WARNING' if invalid_cost_count > 0 else 'VALID',
            }

        # Date
        if 'date' in can_to_src and can_to_src['date'] in df.columns:
            date_col = can_to_src['date']
            parsed_dates = pd.to_datetime(df[date_col], errors='coerce')
            unparseable_count = int(parsed_dates.isna().sum())
            future_date_count = int((parsed_dates > pd.Timestamp.now()).sum())

            results['date'] = {
                'sourceColumn': date_col,
                'unparseableCount': unparseable_count,
                'futureDateCount': future_date_count,
                'status': 'WARNING' if (unparseable_count > 0 or future_date_count > 0) else 'VALID',
            }

        valid_score = 100.0
        if 'quantity' in results and results['quantity']['negativeCount'] > 0:
            valid_score -= (results['quantity']['negativeRate'] * 50)
        if 'price' in results and results['price']['invalidOrZeroCount'] > 0:
            valid_score -= (results['price']['invalidRate'] * 30)

        return {
            'details': results,
            'validityPct': max(0.0, round(valid_score, 2)),
        }

    # ── 4. Outliers & Anomalies ───────────────────────────────────────

    def _detect_anomalies(self, df: pd.DataFrame, can_to_src: Dict[str, str]) -> Dict[str, Any]:
        if 'quantity' not in can_to_src or can_to_src['quantity'] not in df.columns:
            return {'outlierCount': 0, 'outlierRate': 0.0, 'status': 'NORMAL'}

        qty_col = can_to_src['quantity']
        qty = pd.to_numeric(df[qty_col], errors='coerce').dropna()

        if len(qty) < 5:
            return {'outlierCount': 0, 'outlierRate': 0.0, 'status': 'NORMAL'}

        q25, q75 = qty.quantile(0.25), qty.quantile(0.75)
        iqr = q75 - q25
        upper_bound = q75 + (3.0 * iqr)  # Extreme upper threshold

        outliers = qty[qty > upper_bound]
        outlier_count = int(len(outliers))
        outlier_rate = round(outlier_count / len(qty), 4)

        return {
            'sourceColumn': qty_col,
            'iqrUpperThreshold': float(upper_bound),
            'outlierCount': outlier_count,
            'outlierRate': outlier_rate,
            'label': 'ANOMALY',  # Labeled ANOMALY to prevent auto-deletion of flash sales
            'status': 'WARNING' if outlier_count > 0 else 'NORMAL',
        }

    # ── 5. Temporal Consistency ───────────────────────────────────────

    def _validate_temporal_consistency(
        self, df: pd.DataFrame, can_to_src: Dict[str, str]
    ) -> Dict[str, Any]:
        if 'date' not in can_to_src or can_to_src['date'] not in df.columns:
            return {'observationPeriodDays': 0, 'temporalGapsCount': 0, 'temporalIntegrityPct': 0.0}

        date_col = can_to_src['date']
        dates = pd.to_datetime(df[date_col], errors='coerce').dropna().sort_values()

        if dates.empty:
            return {'observationPeriodDays': 0, 'temporalGapsCount': 0, 'temporalIntegrityPct': 0.0}

        min_date = dates.min()
        max_date = dates.max()
        obs_days = max(1, (max_date - min_date).days + 1)

        # Detect gaps > 7 days across sorted dates
        unique_dates = dates.unique()
        date_diffs = np.diff(unique_dates) / np.timedelta64(1, 'D')
        gaps_over_7d = int((date_diffs > 7).sum())
        gaps_over_30d = int((date_diffs > 30).sum())

        temporal_score = 100.0
        if obs_days < 14:
            temporal_score -= 30.0
        elif obs_days < 90:
            temporal_score -= 10.0

        if gaps_over_30d > 0:
            temporal_score -= (gaps_over_30d * 15.0)
        elif gaps_over_7d > 0:
            temporal_score -= (gaps_over_7d * 5.0)

        return {
            'sourceColumn': date_col,
            'minDate': min_date.strftime('%Y-%m-%d'),
            'maxDate': max_date.strftime('%Y-%m-%d'),
            'observationPeriodDays': obs_days,
            'gapsOver7Days': gaps_over_7d,
            'gapsOver30Days': gaps_over_30d,
            'temporalIntegrityPct': max(0.0, round(temporal_score, 2)),
        }

    # ── 6. SKU Consistency ────────────────────────────────────────────

    def _validate_sku_consistency(
        self, df: pd.DataFrame, can_to_src: Dict[str, str]
    ) -> Dict[str, Any]:
        if 'sku' not in can_to_src or can_to_src['sku'] not in df.columns:
            return {'multiNameSkuCount': 0, 'categoryInconsistencyCount': 0}

        sku_col = can_to_src['sku']
        name_col = can_to_src.get('product_name')
        cat_col = can_to_src.get('category')
        brand_col = can_to_src.get('brand')

        multi_name_skus = 0
        if name_col and name_col in df.columns:
            name_counts = df.groupby(sku_col)[name_col].nunique()
            multi_name_skus = int((name_counts > 1).sum())

        multi_cat_skus = 0
        if cat_col and cat_col in df.columns:
            cat_counts = df.groupby(sku_col)[cat_col].nunique()
            multi_cat_skus = int((cat_counts > 1).sum())

        multi_brand_skus = 0
        if brand_col and brand_col in df.columns:
            brand_counts = df.groupby(sku_col)[brand_col].nunique()
            multi_brand_skus = int((brand_counts > 1).sum())

        return {
            'multiNameSkuCount': multi_name_skus,
            'categoryInconsistencyCount': multi_cat_skus,
            'brandInconsistencyCount': multi_brand_skus,
            'status': 'WARNING' if (multi_name_skus > 0 or multi_cat_skus > 0) else 'VALID',
        }

    # ── 7. Numerical Consistency ──────────────────────────────────────

    def _validate_numerical_consistency(
        self, df: pd.DataFrame, can_to_src: Dict[str, str], total_records: int
    ) -> Dict[str, Any]:
        cost_greater_price_count = 0
        price_zero_count = 0

        has_price = 'price' in can_to_src and can_to_src['price'] in df.columns
        has_cost = 'cost' in can_to_src and can_to_src['cost'] in df.columns

        if has_price:
            p_ser = pd.to_numeric(df[can_to_src['price']], errors='coerce')
            price_zero_count = int((p_ser == 0).sum())

        if has_price and has_cost:
            p_ser = pd.to_numeric(df[can_to_src['price']], errors='coerce')
            c_ser = pd.to_numeric(df[can_to_src['cost']], errors='coerce')
            cost_greater_price_count = int((c_ser > p_ser).sum())

        score = 100.0
        if cost_greater_price_count > 0:
            score -= (cost_greater_price_count / total_records) * 30.0

        return {
            'costGreaterThanPriceCount': cost_greater_price_count,
            'priceZeroCount': price_zero_count,
            'consistencyPct': max(0.0, round(score, 2)),
        }

    # ── 8. Demand Quality ─────────────────────────────────────────────

    def _validate_demand_quality(
        self, df: pd.DataFrame, can_to_src: Dict[str, str]
    ) -> Dict[str, Any]:
        if 'quantity' not in can_to_src or can_to_src['quantity'] not in df.columns:
            return {'zeroSalesRate': 0.0, 'highSalesConcentrationDetected': False}

        qty_col = can_to_src['quantity']
        qty_ser = pd.to_numeric(df[qty_col], errors='coerce').fillna(0)

        total_obs = len(qty_ser)
        zero_sales_count = int((qty_ser == 0).sum())
        zero_sales_rate = round(zero_sales_count / max(1, total_obs), 4)

        # Sales concentration check: % sales in top 3 days
        high_concentration = False
        if 'date' in can_to_src and can_to_src['date'] in df.columns:
            date_col = can_to_src['date']
            daily_sales = df.groupby(date_col)[qty_col].sum().sort_values(ascending=False)
            total_qty_sold = qty_ser.sum()
            if total_qty_sold > 0 and len(daily_sales) >= 3:
                top3_sales = daily_sales.iloc[:3].sum()
                top3_pct = top3_sales / total_qty_sold
                if top3_pct >= 0.90:
                    high_concentration = True

        return {
            'zeroSalesCount': zero_sales_count,
            'zeroSalesRate': zero_sales_rate,
            'activeSalesCount': total_obs - zero_sales_count,
            'highSalesConcentrationDetected': high_concentration,
        }

    # ── 9. SKU Quality Profile Table Generator ────────────────────────

    def _generate_sku_quality_profile(
        self, df: pd.DataFrame, can_to_src: Dict[str, str], temporal_info: Dict[str, Any]
    ) -> pd.DataFrame:
        if 'sku' not in can_to_src or can_to_src['sku'] not in df.columns:
            return pd.DataFrame(columns=[
                'sku', 'record_count', 'missing_rate', 'duplicate_rate',
                'zero_sales_rate', 'negative_quantity_count', 'outlier_count',
                'date_gap_count', 'quality_status'
            ])

        sku_col = can_to_src['sku']
        qty_col = can_to_src.get('quantity')
        date_col = can_to_src.get('date')

        records = []
        grouped = df.groupby(sku_col)

        for sku_val, group in grouped:
            rec_count = len(group)
            miss_count = int(group.isna().sum().sum())
            miss_rate = round(miss_count / max(1, rec_count * len(group.columns)), 4)
            dup_rate = round(int(group.duplicated().sum()) / max(1, rec_count), 4)

            zero_rate = 0.0
            neg_qty_count = 0
            outlier_count = 0
            if qty_col and qty_col in group.columns:
                q_ser = pd.to_numeric(group[qty_col], errors='coerce').fillna(0)
                zero_rate = round(int((q_ser == 0).sum()) / max(1, rec_count), 4)
                neg_qty_count = int((q_ser < 0).sum())

                q75, q25 = q_ser.quantile(0.75), q_ser.quantile(0.25)
                upper_b = q75 + (3.0 * (q75 - q25))
                if upper_b > 0:
                    outlier_count = int((q_ser > upper_b).sum())

            gap_count = 0
            if date_col and date_col in group.columns:
                dates = pd.to_datetime(group[date_col], errors='coerce').dropna().sort_values().unique()
                if len(dates) > 1:
                    diffs = np.diff(dates) / np.timedelta64(1, 'D')
                    gap_count = int((diffs > 7).sum())

            if miss_rate > 0.10 or neg_qty_count > 5:
                status = 'CRITICAL'
            elif miss_rate > 0.02 or gap_count > 0 or outlier_count > 0:
                status = 'WARNING'
            else:
                status = 'GOOD'

            records.append({
                'sku': str(sku_val),
                'record_count': rec_count,
                'missing_rate': miss_rate,
                'duplicate_rate': dup_rate,
                'zero_sales_rate': zero_rate,
                'negative_quantity_count': neg_qty_count,
                'outlier_count': outlier_count,
                'date_gap_count': gap_count,
                'quality_status': status,
            })

        return pd.DataFrame(records)

    # ── 10. Deterministic Quality Score (DQ-001: 6 Dimensions) ──────────

    def _calculate_deterministic_score(
        self,
        completeness: Dict[str, Any],
        duplicates: Dict[str, Any],
        invalid_values: Dict[str, Any],
        temporal: Dict[str, Any],
        numerical_consistency: Dict[str, Any],
        freshness_days: int = 1,
        is_schema_valid: bool = True
    ) -> Dict[str, Any]:
        comp_score = float(completeness.get('completenessPct', 100.0))
        uniq_score = float(duplicates.get('uniquenessPct', 100.0))
        val_score = float(invalid_values.get('validityPct', 100.0))
        temp_score = float(temporal.get('temporalIntegrityPct', 100.0))
        cons_score = float(numerical_consistency.get('consistencyPct', 100.0))

        # Freshness dimension (100 if <=3d, 85 if <=7d, 50 if <=30d, 20 if >30d)
        if freshness_days <= 3:
            freshness_score = 100.0
        elif freshness_days <= 7:
            freshness_score = 85.0
        elif freshness_days <= 30:
            freshness_score = 50.0
        else:
            freshness_score = 20.0

        schema_score = 100.0 if is_schema_valid else 60.0

        overall = (
            (comp_score * 0.20) +
            (val_score * 0.20) +
            (cons_score * 0.15) +
            (uniq_score * 0.15) +
            (freshness_score * 0.15) +
            (schema_score * 0.15)
        )
        final_score = int(round(overall))

        return {
            'completenessScore': round(comp_score, 1),
            'validityScore': round(val_score, 1),
            'consistencyScore': round(cons_score, 1),
            'uniquenessScore': round(uniq_score, 1),
            'freshnessScore': round(freshness_score, 1),
            'schemaCompatibilityScore': round(schema_score, 1),
            'overallScore': final_score,
            'dataHealthScoreDisplay': f"{final_score} / 100",
            'dq001_dimensions': {
                'completeness': {'score': round(comp_score, 1), 'display': f"{int(comp_score)}/100"},
                'validity': {'score': round(val_score, 1), 'display': f"{int(val_score)}/100"},
                'consistency': {'score': round(cons_score, 1), 'display': f"{int(cons_score)}/100"},
                'uniqueness': {'score': round(uniq_score, 1), 'display': f"{int(uniq_score)}/100"},
                'freshness': {'score': round(freshness_score, 1), 'display': f"{int(freshness_score)}/100"},
                'schema_compatibility': {'score': round(schema_score, 1), 'display': f"{int(schema_score)}/100"}
            }
        }

    # ── Exporter: Write Reports ───────────────────────────────────────

    def export_reports(self, report_result: Dict[str, Any], output_dir: str = 'reports/') -> Dict[str, str]:
        """Export data_quality_report.json, data_quality_summary.json, sku_quality_profile.parquet/csv."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. Full report JSON
        full_report_path = os.path.join(output_dir, 'data_quality_report.json')
        with open(full_report_path, 'w', encoding='utf-8') as f:
            json.dump(report_result, f, indent=2, ensure_ascii=False)

        # 2. Executive summary JSON
        summary_payload = {
            'dataset_quality_score': report_result['datasetQualityScore'],
            'status': report_result['qualityStatus'],
            'total_records': report_result['totalRecords'],
            'total_skus': report_result['totalSkus'],
            'missing_rate': report_result['completeness']['averageMissingRate'],
            'duplicate_rate': report_result['duplicates']['exactDuplicateRate'],
            'anomaly_rate': report_result['anomalies']['outlierRate'],
            'slow_moving_detection_ready': report_result['slowMovingDetectionReady'],
            'inventory_risk_detection_ready': report_result['physicalInventoryRiskReady'],
        }
        summary_path = os.path.join(output_dir, 'data_quality_summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # 3. SKU Quality Profile (Parquet + CSV fallback)
        sku_df = getattr(self, '_last_sku_profile_df', pd.DataFrame())
        sku_csv_path = os.path.join(output_dir, 'sku_quality_profile.csv')
        sku_parquet_path = os.path.join(output_dir, 'sku_quality_profile.parquet')

        if not sku_df.empty:
            sku_df.to_csv(sku_csv_path, index=False, encoding='utf-8-sig')
            try:
                sku_df.to_parquet(sku_parquet_path, index=False)
            except Exception:
                pass  # Fallback to CSV if pyarrow missing

        return {
            'data_quality_report': full_report_path,
            'data_quality_summary': summary_path,
            'sku_quality_profile_csv': sku_csv_path,
            'sku_quality_profile_parquet': sku_parquet_path,
        }

    def _empty_report(self) -> Dict[str, Any]:
        return {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'totalRecords': 0,
            'totalSkus': 0,
            'datasetQualityScore': 0.0,
            'qualityStatus': 'CRITICAL',
            'slowMovingDetectionReady': False,
            'physicalInventoryRiskReady': False,
            'readinessReasons': ['File dữ liệu rỗng'],
        }
