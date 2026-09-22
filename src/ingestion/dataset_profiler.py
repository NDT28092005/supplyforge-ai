"""
Dataset Profiling Engine — Module 01 Data Ingestion (TASK 02)
================================================================
Inspects, calculates statistics, and evaluates dataset quality post-ingestion.
Does NOT mutate raw data. Preserves zero-sales rows for demand pattern analysis.

Outputs standard report files to reports/:
  - reports/dataset_profile.json
  - reports/dataset_quality_report.json
  - reports/sku_profile.parquet (and .csv / .json fallbacks)
  - reports/data_quality_summary.json
"""

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class DatasetProfiler:
    """Comprehensive dataset profiler for e-commerce sales & inventory data."""

    def __init__(
        self,
        df: pd.DataFrame,
        column_mapping: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None,
    ):
        """Initialize DatasetProfiler with a DataFrame and optional column mapping.

        column_mapping example:
            {
                'itemSku': 'sku',
                'productName': 'product_name',
                'orderDate': 'order_date',
                'stock': 'quantity',
                'price': 'selling_price',
                'cost': 'cost'
            }
        """
        self.df = df.copy()
        self.raw_mapping = column_mapping or {}
        self.session_id = session_id or 'default_session'
        self.normalized_cols: Dict[str, str] = {}
        self._resolve_column_mapping()

    # ── 1. Column Mapping Resolver ────────────────────────────────────

    def _resolve_column_mapping(self):
        """Identify key business columns using mapping or heuristic regex."""
        headers = list(self.df.columns)
        h_lower = [str(col).lower() for col in headers]

        def find_col(db_key: str, keywords: List[str]) -> Optional[str]:
            # 1. Check user-provided mapping first
            mapped_val = self.raw_mapping.get(db_key)
            if mapped_val and mapped_val in headers:
                return mapped_val

            # 2. Check keywords in columns
            for i, h in enumerate(h_lower):
                for kw in keywords:
                    if kw in h:
                        return headers[i]
            return None

        self.normalized_cols['sku'] = find_col(
            'itemSku', ['sku', 'item_id', 'product_id', 'itemid', 'mã_sp', 'code']
        )
        self.normalized_cols['product_name'] = find_col(
            'productName', ['product_name', 'name', 'tên_sản_phẩm', 'tên', 'title', 'item_name']
        )
        self.normalized_cols['order_date'] = find_col(
            'orderDate', ['date', 'time', 'order_date', 'ngày', 'created_at', 'record_date']
        )
        self.normalized_cols['quantity'] = find_col(
            'stock', ['quantity', 'qty', 'số_lượng', 'sl', 'stock', 'model_quantity_purchased']
        )
        self.normalized_cols['price'] = find_col(
            'price', ['selling_price', 'price', 'giá_bán', 'giá', 'amount', 'unit_price']
        )
        self.normalized_cols['cost'] = find_col(
            'cost', ['cost_price', 'cost', 'giá_vốn', 'vốn', 'cost_imputed']
        )

    # ── 2. Dataset Overview ───────────────────────────────────────────

    def run_full_profile(self) -> Dict[str, Any]:
        """Execute full 7-step profiling suite and return consolidated profile dict."""
        overview = self._profile_overview()
        schema = self._profile_schema()
        quality = self._profile_quality()
        sku_df, sparsity = self._profile_demand_sparsity(overview)
        coverage = self._profile_time_coverage(overview)
        readiness = self._assess_readiness(overview, quality, coverage, sparsity)

        profile_data = {
            'sessionId': self.session_id,
            'overview': overview,
            'schema': schema,
            'quality': quality,
            'sparsity': sparsity,
            'coverage': coverage,
            'readiness': readiness,
            'sku_profile_count': len(sku_df),
        }

        self._last_sku_df = sku_df
        self._last_profile_data = profile_data
        return profile_data

    # ── Step 1: Overview & Classification ─────────────────────────────

    def _profile_overview(self) -> Dict[str, Any]:
        total_records = len(self.df)
        total_columns = len(self.df.columns)
        dataset_size_bytes = int(self.df.memory_usage(deep=True).sum())

        sku_col = self.normalized_cols.get('sku')
        date_col = self.normalized_cols.get('order_date')

        # SKU stats
        if sku_col and sku_col in self.df.columns:
            unique_skus = int(self.df[sku_col].dropna().nunique())
        else:
            unique_skus = 0

        # Date stats
        min_date, max_date, obs_days = None, None, 0
        records_by_day = {}
        records_by_month = {}

        if date_col and date_col in self.df.columns:
            dates = pd.to_datetime(self.df[date_col], errors='coerce').dropna()
            if not dates.empty:
                min_dt = dates.min()
                max_dt = dates.max()
                min_date = min_dt.strftime('%Y-%m-%d')
                max_date = max_dt.strftime('%Y-%m-%d')
                obs_days = max(1, (max_dt - min_dt).days + 1)

                # Distribution by month
                month_counts = dates.dt.strftime('%Y-%m').value_counts().sort_index()
                records_by_month = {str(k): int(v) for k, v in month_counts.items()}

                # Distribution by day (top 30 days sample for JSON)
                day_counts = dates.dt.strftime('%Y-%m-%d').value_counts().sort_index()
                records_by_day = {str(k): int(v) for k, v in day_counts.items()}

        # Dataset Classification
        dataset_type = self._classify_dataset_type(total_records, unique_skus, obs_days, date_col)

        return {
            'totalRecords': total_records,
            'totalColumns': total_columns,
            'uniqueSkus': unique_skus,
            'minTransactionDate': min_date,
            'maxTransactionDate': max_date,
            'observationPeriodDays': obs_days,
            'datasetSizeBytes': dataset_size_bytes,
            'datasetType': dataset_type,
            'recordsByMonth': records_by_month,
            'recordsByDay': records_by_day,
            'mappedColumns': self.normalized_cols,
        }

    def _classify_dataset_type(
        self, records: int, skus: int, obs_days: int, date_col: Optional[str]
    ) -> str:
        if not date_col or obs_days == 0:
            return 'Unknown Structure'
        if skus > 0 and records > 0:
            ratio = records / (skus * max(1, obs_days))
            if ratio >= 0.9 and 'stock' in [str(c).lower() for c in self.df.columns]:
                return 'Inventory Snapshot'
            if records > skus * 1.5:
                return 'Transaction-level Data'
            return 'Daily Aggregated Data'
        return 'Transaction-level Data'

    # ── Step 2: Schema & Column Profiling ──────────────────────────────

    def _profile_schema(self) -> Dict[str, Dict[str, Any]]:
        schema_profile = {}
        total_rows = len(self.df)

        for col in self.df.columns:
            series = self.df[col]
            missing_count = int(series.isna().sum())
            missing_rate = round(missing_count / total_rows * 100, 2) if total_rows > 0 else 0.0

            # Zero count (for numeric)
            is_numeric = pd.api.types.is_numeric_dtype(series)
            zero_count = int((series == 0).sum()) if is_numeric else 0
            zero_rate = round(zero_count / total_rows * 100, 2) if total_rows > 0 else 0.0

            unique_vals = int(series.nunique(dropna=True))

            # Cardinality classification
            if unique_vals == 0:
                cardinality = 'Empty'
            elif unique_vals == 1:
                cardinality = 'Single Value'
            elif unique_vals < 20:
                cardinality = 'Low'
            elif unique_vals < 500:
                cardinality = 'Medium'
            else:
                cardinality = 'High'

            # Numeric statistics
            min_val, max_val, mean_val, median_val = None, None, None, None
            if is_numeric:
                clean_num = series.dropna()
                if not clean_num.empty:
                    min_val = float(clean_num.min())
                    max_val = float(clean_num.max())
                    mean_val = round(float(clean_num.mean()), 4)
                    median_val = float(clean_num.median())

            # Sample values (up to 5 non-null)
            samples = [str(x) for x in series.dropna().unique()[:5]]

            schema_profile[str(col)] = {
                'dataType': str(series.dtype),
                'uniqueValues': unique_vals,
                'missingCount': missing_count,
                'missingRate': missing_rate,
                'zeroCount': zero_count,
                'zeroRate': zero_rate,
                'min': min_val,
                'max': max_val,
                'mean': mean_val,
                'median': median_val,
                'sampleValues': samples,
                'cardinality': cardinality,
            }

        return schema_profile

    # ── Step 3: Missing Value & Quality Analysis ───────────────────────

    def _profile_quality(self) -> Dict[str, Any]:
        total_rows = len(self.df)
        sku_col = self.normalized_cols.get('sku')
        name_col = self.normalized_cols.get('product_name')
        date_col = self.normalized_cols.get('order_date')
        qty_col = self.normalized_cols.get('quantity')
        price_col = self.normalized_cols.get('price')
        cost_col = self.normalized_cols.get('cost')

        missing_sku = int(self.df[sku_col].isna().sum()) if sku_col else total_rows
        missing_name = int(self.df[name_col].isna().sum()) if name_col else total_rows
        missing_date = int(self.df[date_col].isna().sum()) if date_col else total_rows
        missing_qty = int(self.df[qty_col].isna().sum()) if qty_col else total_rows
        missing_cost = int(self.df[cost_col].isna().sum()) if cost_col else total_rows

        # Abnormal quantities (negative)
        negative_qty = 0
        if qty_col and qty_col in self.df.columns and pd.api.types.is_numeric_dtype(self.df[qty_col]):
            negative_qty = int((self.df[qty_col] < 0).sum())

        # Invalid prices (<= 0)
        invalid_price = 0
        if price_col and price_col in self.df.columns and pd.api.types.is_numeric_dtype(self.df[price_col]):
            invalid_price = int((self.df[price_col] <= 0).sum())

        # Duplicate records
        duplicate_count = int(self.df.duplicated().sum())
        duplicate_rate = round(duplicate_count / total_rows * 100, 2) if total_rows > 0 else 0.0

        # SKU multi-name inconsistency (same SKU mapping to multiple distinct names)
        inconsistent_skus = {}
        if sku_col and name_col and sku_col in self.df.columns and name_col in self.df.columns:
            grouped = self.df.dropna(subset=[sku_col, name_col]).groupby(sku_col)[name_col].unique()
            for sku_val, names in grouped.items():
                if len(names) > 1:
                    inconsistent_skus[str(sku_val)] = [str(n) for n in names[:5]]

        # Data time gaps (> 7 days without any record)
        time_gaps = []
        if date_col and date_col in self.df.columns:
            dates = pd.to_datetime(self.df[date_col], errors='coerce').dropna().sort_values().unique()
            if len(dates) > 1:
                diffs = np.diff(dates) / np.timedelta64(1, 'D')
                gap_indices = np.where(diffs > 7)[0]
                for idx in gap_indices[:10]:  # limit to top 10 gaps
                    d1 = pd.to_datetime(dates[idx]).strftime('%Y-%m-%d')
                    d2 = pd.to_datetime(dates[idx + 1]).strftime('%Y-%m-%d')
                    gap_days = int(diffs[idx])
                    time_gaps.append({'startDate': d1, 'endDate': d2, 'gapDays': gap_days})

        return {
            'missingSkuCount': missing_sku,
            'missingProductNameCount': missing_name,
            'missingDateCount': missing_date,
            'missingQuantityCount': missing_qty,
            'missingCostCount': missing_cost,
            'negativeQuantityCount': negative_qty,
            'invalidPriceCount': invalid_price,
            'duplicateRecordCount': duplicate_count,
            'duplicateRecordRate': duplicate_rate,
            'inconsistentSkuNames': inconsistent_skus,
            'inconsistentSkuCount': len(inconsistent_skus),
            'dataTimeGaps': time_gaps,
        }

    # ── Step 4: Sales & Demand Sparsity Profiling (SKU Level) ──────────

    def _profile_demand_sparsity(
        self, overview: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        sku_col = self.normalized_cols.get('sku')
        name_col = self.normalized_cols.get('product_name')
        date_col = self.normalized_cols.get('order_date')
        qty_col = self.normalized_cols.get('quantity')
        price_col = self.normalized_cols.get('price')

        obs_days = overview['observationPeriodDays'] or 1
        max_date_str = overview['maxTransactionDate']
        max_dt = datetime.strptime(max_date_str, '%Y-%m-%d') if max_date_str else datetime.now()

        sku_profiles = []

        if sku_col and sku_col in self.df.columns:
            # Group by SKU
            df_working = self.df.copy()
            if date_col and date_col in df_working.columns:
                df_working['_parsed_date'] = pd.to_datetime(df_working[date_col], errors='coerce')
            else:
                df_working['_parsed_date'] = datetime.now()

            grouped = df_working.groupby(sku_col)

            for sku_val, group in grouped:
                sku_str = str(sku_val)
                name_str = str(group[name_col].dropna().iloc[0]) if (name_col and name_col in group.columns and not group[name_col].dropna().empty) else sku_str

                # Sales calculations
                if qty_col and qty_col in group.columns:
                    total_sales = float(pd.to_numeric(group[qty_col], errors='coerce').fillna(0).sum())
                else:
                    total_sales = len(group)

                # Active sales days (distinct dates with sale > 0)
                valid_sales = group[pd.to_numeric(group[qty_col], errors='coerce') > 0] if qty_col and qty_col in group.columns else group
                active_days = int(valid_sales['_parsed_date'].dt.date.nunique())

                # SKU specific observation period
                min_sku_dt = group['_parsed_date'].min()
                max_sku_dt = group['_parsed_date'].max()
                sku_obs_days = max(1, (max_sku_dt - min_sku_dt).days + 1) if (pd.notna(min_sku_dt) and pd.notna(max_sku_dt)) else obs_days

                zero_days = max(0, sku_obs_days - active_days)
                zero_rate = round(zero_days / sku_obs_days, 4) if sku_obs_days > 0 else 0.0
                velocity = round(total_sales / sku_obs_days, 4) if sku_obs_days > 0 else 0.0

                # Days Since Last Sale (DSLS)
                if not valid_sales.empty and pd.notna(valid_sales['_parsed_date'].max()):
                    last_sale_dt = valid_sales['_parsed_date'].max().to_pydatetime()
                    dsls = max(0, (max_dt - last_sale_dt).days)
                else:
                    dsls = sku_obs_days

                # Avg inter-purchase interval
                sale_dates = valid_sales['_parsed_date'].dt.date.drop_duplicates().sort_values()
                if len(sale_dates) > 1:
                    intervals = np.diff(sale_dates) / np.timedelta64(1, 'D')
                    avg_interval = round(float(np.mean(intervals)), 2)
                else:
                    avg_interval = float(sku_obs_days)

                # Quality status per SKU
                if sku_obs_days < 30:
                    status = 'WARNING_SHORT_HISTORY'
                elif total_sales == 0:
                    status = 'ZERO_SALES'
                else:
                    status = 'VALID'

                sku_profiles.append({
                    'sku': sku_str,
                    'product_name': name_str,
                    'observation_days': sku_obs_days,
                    'total_sales': total_sales,
                    'active_sales_days': active_days,
                    'zero_sales_days': zero_days,
                    'zero_sales_rate': zero_rate,
                    'sales_velocity': velocity,
                    'days_since_last_sale': dsls,
                    'avg_inter_purchase_interval': avg_interval,
                    'transaction_count': len(group),
                    'data_quality_status': status,
                })

        sku_df = pd.DataFrame(sku_profiles)

        # Sparsity summary across entire dataset
        if not sku_df.empty:
            avg_zero_rate = round(float(sku_df['zero_sales_rate'].mean() * 100), 2)
            avg_velocity = round(float(sku_df['sales_velocity'].mean()), 4)
            avg_dsls = round(float(sku_df['days_since_last_sale'].mean()), 1)

            # Categorize sparsity based on zero rate & velocity
            intermittent_count = int((sku_df['zero_sales_rate'] >= 0.75).sum())
            smooth_count = int((sku_df['zero_sales_rate'] < 0.50).sum())
            lumpy_count = len(sku_df) - intermittent_count - smooth_count
        else:
            avg_zero_rate = 0.0
            avg_velocity = 0.0
            avg_dsls = 0.0
            intermittent_count = 0
            lumpy_count = 0
            smooth_count = 0

        sparsity_summary = {
            'avgZeroSalesRatePct': avg_zero_rate,
            'avgSalesVelocity': avg_velocity,
            'avgDaysSinceLastSale': avg_dsls,
            'intermittentSkuCount': intermittent_count,
            'lumpySkuCount': lumpy_count,
            'smoothSkuCount': smooth_count,
        }

        return sku_df, sparsity_summary

    # ── Step 5: Time Coverage & Continuity ─────────────────────────────

    def _profile_time_coverage(self, overview: Dict[str, Any]) -> Dict[str, Any]:
        obs_days = overview['observationPeriodDays']

        coverage = {
            'hasRecommended90d': obs_days >= 90,
            'hasRecommended180d': obs_days >= 180,
            'hasRecommended365d': obs_days >= 365,
            'observationPeriodDays': obs_days,
            'warnings': [],
        }

        if obs_days < 90:
            coverage['warnings'].append(
                f"Dữ liệu chỉ có {obs_days} ngày lịch sử. Khuyến nghị tối thiểu 90 ngày để đánh giá hàng bán chậm chính xác."
            )
        if obs_days < 30:
            coverage['warnings'].append(
                "Khoảng thời gian dữ liệu quá ngắn (< 30 ngày). Rủi ro cao dẫn đến đánh giá sai lệch cold-start SKU."
            )

        return coverage

    # ── Step 6: Readiness Assessment ──────────────────────────────────

    def _assess_readiness(
        self,
        overview: Dict[str, Any],
        quality: Dict[str, Any],
        coverage: Dict[str, Any],
        sparsity: Dict[str, Any],
    ) -> Dict[str, Any]:
        warnings = []
        critical_errors = []

        # Required fields check
        if not self.normalized_cols.get('sku'):
            critical_errors.append("Không nhận diện được cột mã SKU.")
        if not self.normalized_cols.get('order_date'):
            critical_errors.append("Không nhận diện được cột Ngày giao dịch.")

        # Data quantity check
        if overview['totalRecords'] == 0:
            critical_errors.append("Dataset rỗng (0 dòng).")
        if overview['observationPeriodDays'] < 14:
            critical_errors.append("Dữ liệu quá ít (< 14 ngày lịch sử).")

        # Warnings
        if quality.get('missingCostCount', 0) > 0:
            pct = round(quality['missingCostCount'] / max(1, overview['totalRecords']) * 100, 1)
            warnings.append(f"Thiếu giá vốn (Cost missing): {pct}% dòng.")
        if quality.get('duplicateRecordRate', 0) > 2.0:
            warnings.append(f"Tỷ lệ trùng lặp bản ghi cao: {quality['duplicateRecordRate']}%.")
        if quality.get('inconsistentSkuCount', 0) > 0:
            warnings.append(f"Có {quality['inconsistentSkuCount']} SKU có nhiều tên sản phẩm khác nhau.")
        if coverage.get('warnings'):
            warnings.extend(coverage['warnings'])

        # Readiness status classification
        if critical_errors:
            status = 'INSUFFICIENT_DATA'
            score = 20.0
        elif quality.get('missingSkuCount', 0) > overview['totalRecords'] * 0.3:
            status = 'NEEDS_CLEANING'
            score = 50.0
        elif warnings:
            status = 'READY_WITH_WARNING'
            score = 85.0
        else:
            status = 'READY'
            score = 98.0

        return {
            'status': status,
            'readinessScore': score,
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'checksPassed': [
                'SKU identifier detected' if self.normalized_cols.get('sku') else None,
                'Transaction date detected' if self.normalized_cols.get('order_date') else None,
                f"{overview['observationPeriodDays']} days observation period",
                f"{overview['uniqueSkus']} unique SKUs profiled",
            ],
        }

    # ── Step 7: Export Reports to reports/ ────────────────────────────

    def export_reports(self, output_dir: str = 'reports/') -> Dict[str, str]:
        """Export the 4 standard dataset profiling report artifacts to output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        if not hasattr(self, '_last_profile_data'):
            self.run_full_profile()

        profile_data = self._last_profile_data
        sku_df = getattr(self, '_last_sku_df', pd.DataFrame())

        file_paths = {}

        # 1. reports/dataset_profile.json
        p1 = os.path.join(output_dir, 'dataset_profile.json')
        with open(p1, 'w', encoding='utf-8') as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)
        file_paths['dataset_profile'] = p1

        # 2. reports/dataset_quality_report.json
        p2 = os.path.join(output_dir, 'dataset_quality_report.json')
        quality_report = {
            'sessionId': self.session_id,
            'readiness': profile_data['readiness'],
            'qualityMetrics': profile_data['quality'],
            'schemaSummary': profile_data['schema'],
        }
        with open(p2, 'w', encoding='utf-8') as f:
            json.dump(quality_report, f, indent=2, ensure_ascii=False)
        file_paths['dataset_quality_report'] = p2

        # 3. reports/sku_profile.parquet (and .csv fallback)
        p3_parquet = os.path.join(output_dir, 'sku_profile.parquet')
        p3_csv = os.path.join(output_dir, 'sku_profile.csv')
        try:
            sku_df.to_parquet(p3_parquet, index=False)
            file_paths['sku_profile_parquet'] = p3_parquet
        except Exception as e:
            # Fallback to CSV if pyarrow not installed
            sku_df.to_csv(p3_csv, index=False, encoding='utf-8')
            file_paths['sku_profile_csv'] = p3_csv

        # 4. reports/data_quality_summary.json
        p4 = os.path.join(output_dir, 'data_quality_summary.json')
        summary = {
            'sessionId': self.session_id,
            'status': profile_data['readiness']['status'],
            'readinessScore': profile_data['readiness']['readinessScore'],
            'totalRecords': profile_data['overview']['totalRecords'],
            'totalSkus': profile_data['overview']['uniqueSkus'],
            'observationDays': profile_data['overview']['observationPeriodDays'],
            'avgZeroSalesRatePct': profile_data['sparsity']['avgZeroSalesRatePct'],
            'warningsCount': len(profile_data['readiness']['warnings']),
        }
        with open(p4, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        file_paths['data_quality_summary'] = p4

        return file_paths
