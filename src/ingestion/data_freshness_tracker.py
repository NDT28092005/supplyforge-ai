"""
Data Freshness & Coverage Tracking Engine — Module 01 Data Ingestion (DAT-08)
================================================================================
Evaluates business data recency (freshness_days = current_date - data_max_date)
and dataset coverage gaps. Strictly distinguishes Upload Freshness from Data Freshness
and acts as a Decision Safety Guard for downstream DSS analytics.

Outputs standard reports to:
  - reports/data_freshness_status.json
  - reports/dataset_coverage_report.json
  - reports/freshness_alerts.json
  - reports/sku_freshness_report.parquet (.csv fallback)
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class DataFreshnessTracker:
    """Data Freshness & Coverage Tracking Engine (DAT-08)."""

    DEFAULT_THRESHOLDS = {
        'fresh_threshold_days': 3,     # <= 3 days: FRESH
        'aging_threshold_days': 7,     # 4 - 7 days: AGING
        'stale_threshold_days': 30,    # 8 - 30 days: STALE
    }

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    # ── Main Freshness Evaluation Pipeline ────────────────────────────

    def evaluate_freshness(
        self,
        df: pd.DataFrame,
        mapping_result: Optional[Dict[str, Any]] = None,
        custom_thresholds: Optional[Dict[str, int]] = None,
        current_date: Optional[Union[str, datetime]] = None,
        last_upload_at: Optional[Union[str, datetime]] = None,
    ) -> Dict[str, Any]:
        """Run full dataset & SKU-level freshness tracking evaluation."""
        thresholds = {**self.DEFAULT_THRESHOLDS, **(custom_thresholds or {})}

        # Parse reference dates
        if current_date is None:
            curr_dt = datetime.now()
        elif isinstance(current_date, str):
            curr_dt = pd.to_datetime(current_date).to_pydatetime()
        else:
            curr_dt = current_date

        if last_upload_at is None:
            upload_dt = datetime.now()
        elif isinstance(last_upload_at, str):
            upload_dt = pd.to_datetime(last_upload_at).to_pydatetime()
        else:
            upload_dt = last_upload_at

        # Identify date & sku columns
        date_col, sku_col = self._extract_columns(df, mapping_result)

        if not date_col or date_col not in df.columns:
            return self._empty_freshness_report("Không tìm thấy trường ngày giao dịch trong dataset.")

        parsed_dates = pd.to_datetime(df[date_col], errors='coerce').dropna().sort_values()

        if parsed_dates.empty:
            return self._empty_freshness_report("Dataset không chứa dữ liệu ngày giao dịch hợp lệ.")

        data_min_dt = parsed_dates.min().to_pydatetime()
        data_max_dt = parsed_dates.max().to_pydatetime()

        # 1. Calculate Data Freshness Days
        freshness_days = max(0, (curr_dt.date() - data_max_dt.date()).days)

        # 2. Classify Data Freshness Status
        data_status = self.classify_status(freshness_days, thresholds)

        # 3. Distinguish Upload Freshness vs Business Data Freshness
        upload_days = max(0, (curr_dt.date() - upload_dt.date()).days)
        upload_status = 'RECENT' if upload_days <= 1 else 'OLDER'

        freshness_mismatch = (upload_status == 'RECENT' and data_status in ('STALE', 'OUTDATED'))

        # 4. Dataset Coverage & Missing Gap Monitoring
        coverage_report = self._analyze_coverage(parsed_dates, data_min_dt, data_max_dt)

        # 5. SKU-Level Freshness Profiling
        sku_freshness_df = self._analyze_sku_freshness(df, sku_col, date_col, curr_dt, thresholds)

        # 6. Decision Safety Guard Evaluation
        can_run_analysis = data_status in ('FRESH', 'AGING')
        guard_reason = None
        if not can_run_analysis:
            guard_reason = (
                f"Dữ liệu kinh doanh đã quá hạn ({freshness_days} ngày, trạng thái {data_status}). "
                "Yêu cầu Merchant upload dữ liệu mới nhất trước khi đưa ra quyết định giải phóng vốn."
            )

        # 7. Generate Freshness Alerts
        alerts = self._generate_alerts(
            data_status=data_status,
            freshness_days=freshness_days,
            data_max_dt=data_max_dt,
            curr_dt=curr_dt,
            freshness_mismatch=freshness_mismatch,
            coverage_report=coverage_report
        )

        status_result = {
            'sessionId': self.session_id,
            'timestamp': datetime.now().isoformat(),
            'currentDate': curr_dt.strftime('%Y-%m-%d'),
            'lastUploadAt': upload_dt.isoformat(),
            'uploadFreshnessStatus': upload_status,
            'dataMinDate': data_min_dt.strftime('%Y-%m-%d'),
            'dataMaxDate': data_max_dt.strftime('%Y-%m-%d'),
            'freshnessDays': freshness_days,
            'freshnessStatus': data_status,
            'freshnessMismatch': freshness_mismatch,
            'thresholdsUsed': thresholds,
            'decisionGuard': {
                'canRunCurrentAnalysis': can_run_analysis,
                'guardReason': guard_reason,
            },
            'alerts': alerts,
            'coverageReport': coverage_report,
            'skuFreshnessSummary': {
                'totalSkusProfiled': len(sku_freshness_df),
                'freshSkus': int((sku_freshness_df['freshness_status'] == 'FRESH').sum()) if not sku_freshness_df.empty else 0,
                'agingSkus': int((sku_freshness_df['freshness_status'] == 'AGING').sum()) if not sku_freshness_df.empty else 0,
                'staleSkus': int((sku_freshness_df['freshness_status'] == 'STALE').sum()) if not sku_freshness_df.empty else 0,
                'outdatedSkus': int((sku_freshness_df['freshness_status'] == 'OUTDATED').sum()) if not sku_freshness_df.empty else 0,
            }
        }

        # Store internal state for exporter
        self._last_sku_df = sku_freshness_df
        self._last_status_result = status_result
        self._last_coverage_report = coverage_report
        self._last_alerts = alerts

        return status_result

    # ── Helper: Classify Status by Threshold ──────────────────────────

    @staticmethod
    def classify_status(freshness_days: int, thresholds: Dict[str, int]) -> str:
        """Classify freshness_days into FRESH, AGING, STALE, or OUTDATED."""
        f_thresh = thresholds.get('fresh_threshold_days', 3)
        a_thresh = thresholds.get('aging_threshold_days', 7)
        s_thresh = thresholds.get('stale_threshold_days', 30)

        if freshness_days <= f_thresh:
            return 'FRESH'
        elif freshness_days <= a_thresh:
            return 'AGING'
        elif freshness_days <= s_thresh:
            return 'STALE'
        else:
            return 'OUTDATED'

    # ── Exporter: Save 4 Reports ──────────────────────────────────────

    def export_artifacts(self, status_result: Dict[str, Any], output_dir: str = 'reports/') -> Dict[str, str]:
        """Export all 4 standard DAT-08 artifacts to reports/."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. data_freshness_status.json
        status_path = os.path.join(output_dir, 'data_freshness_status.json')
        with open(status_path, 'w', encoding='utf-8') as f:
            json.dump(status_result, f, indent=2, ensure_ascii=False)

        # 2. dataset_coverage_report.json
        cov_path = os.path.join(output_dir, 'dataset_coverage_report.json')
        with open(cov_path, 'w', encoding='utf-8') as f:
            json.dump(status_result.get('coverageReport', {}), f, indent=2, ensure_ascii=False)

        # 3. freshness_alerts.json
        alert_path = os.path.join(output_dir, 'freshness_alerts.json')
        with open(alert_path, 'w', encoding='utf-8') as f:
            json.dump(status_result.get('alerts', []), f, indent=2, ensure_ascii=False)

        # 4. sku_freshness_report (Parquet + CSV)
        sku_df = getattr(self, '_last_sku_df', pd.DataFrame())
        sku_csv_path = os.path.join(output_dir, 'sku_freshness_report.csv')
        sku_parquet_path = os.path.join(output_dir, 'sku_freshness_report.parquet')

        if not sku_df.empty:
            sku_df.to_csv(sku_csv_path, index=False, encoding='utf-8-sig')
            try:
                parquet_df = sku_df.copy()
                for c in parquet_df.select_dtypes(include=['object']).columns:
                    parquet_df[c] = parquet_df[c].astype(str)
                parquet_df.to_parquet(sku_parquet_path, index=False)
            except Exception:
                sku_df.to_csv(sku_parquet_path, index=False, encoding='utf-8-sig')

        return {
            'data_freshness_status': status_path,
            'dataset_coverage_report': cov_path,
            'freshness_alerts': alert_path,
            'sku_freshness_report_csv': sku_csv_path,
            'sku_freshness_report_parquet': sku_parquet_path,
        }

    # ── Internal Helpers ──────────────────────────────────────────────

    def _analyze_coverage(
        self, parsed_dates: pd.Series, min_dt: datetime, max_dt: datetime
    ) -> Dict[str, Any]:
        unique_dates = parsed_dates.dt.date.unique()
        coverage_days = len(unique_dates)

        # Generate full expected date range
        full_date_range = pd.date_range(min_dt.date(), max_dt.date(), freq='D').date
        expected_days = len(full_date_range)

        present_set = set(unique_dates)
        missing_dates = [d.strftime('%Y-%m-%d') for d in full_date_range if d not in present_set]

        return {
            'dataMinDate': min_dt.strftime('%Y-%m-%d'),
            'dataMaxDate': max_dt.strftime('%Y-%m-%d'),
            'totalSpanDays': expected_days,
            'activeCoverageDays': coverage_days,
            'missingDaysCount': len(missing_dates),
            'missingDates': missing_dates[:50],  # Limit to 50 missing dates in summary
            'hasDisruptionGaps': len(missing_dates) > 0,
        }

    def _analyze_sku_freshness(
        self,
        df: pd.DataFrame,
        sku_col: Optional[str],
        date_col: str,
        curr_dt: datetime,
        thresholds: Dict[str, int]
    ) -> pd.DataFrame:
        if not sku_col or sku_col not in df.columns:
            return pd.DataFrame(columns=['sku', 'latest_data_date', 'freshness_days', 'freshness_status'])

        records = []
        df_valid = df.dropna(subset=[date_col]).copy()
        df_valid['_parsed_dt'] = pd.to_datetime(df_valid[date_col], errors='coerce')
        grouped = df_valid.dropna(subset=['_parsed_dt']).groupby(sku_col)

        for sku_val, group in grouped:
            max_sku_dt = group['_parsed_dt'].max().to_pydatetime()
            f_days = max(0, (curr_dt.date() - max_sku_dt.date()).days)
            f_status = self.classify_status(f_days, thresholds)

            records.append({
                'sku': str(sku_val),
                'latest_data_date': max_sku_dt.strftime('%Y-%m-%d'),
                'freshness_days': f_days,
                'freshness_status': f_status,
            })

        return pd.DataFrame(records)

    def _generate_alerts(
        self,
        data_status: str,
        freshness_days: int,
        data_max_dt: datetime,
        curr_dt: datetime,
        freshness_mismatch: bool,
        coverage_report: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        alerts = []

        if data_status in ('STALE', 'OUTDATED'):
            alerts.append({
                'alertId': f"ALT_FRESH_{data_status}",
                'severity': 'CRITICAL' if data_status == 'OUTDATED' else 'WARNING',
                'title': f"⚠ Dữ liệu kinh doanh đã quá cũ ({freshness_days} ngày)",
                'message': (
                    f"Dữ liệu kinh doanh gần nhất là {data_max_dt.strftime('%Y-%m-%d')} "
                    f"(hôm nay là {curr_dt.strftime('%Y-%m-%d')}, độ cũ {freshness_days} ngày). "
                    "Kết quả phân tích Hàng bán chậm có thể không phản ánh chính xác thực tế kinh doanh."
                ),
                'recommendation': "Upload dữ liệu giao dịch mới trước khi đưa ra quyết định giải phóng vốn.",
            })

        if freshness_mismatch:
            alerts.append({
                'alertId': "ALT_UPLOAD_MISMATCH",
                'severity': 'WARNING',
                'title': "⚠ File upload mới nhưng chứa dữ liệu nghiệp vụ cũ",
                'message': (
                    "Hệ thống ghi nhận bạn vừa upload file gần đây, nhưng dữ liệu bán hàng bên trong "
                    f"chỉ dừng lại ở ngày {data_max_dt.strftime('%Y-%m-%d')}."
                ),
                'recommendation': "Kiểm tra lại khoảng thời gian xuất file báo cáo từ Shopee/Lazada.",
            })

        if coverage_report.get('hasDisruptionGaps'):
            alerts.append({
                'alertId': "ALT_COVERAGE_GAP",
                'severity': 'INFO',
                'title': f"ℹ Phát hiện {coverage_report['missingDaysCount']} ngày bị ngắt quãng dữ liệu",
                'message': f"Trong khoảng thời gian từ {coverage_report['dataMinDate']} đến {coverage_report['dataMaxDate']} có một số ngày không phát sinh giao dịch.",
                'recommendation': "Xác nhận merchant không bị sót file giao dịch của các ngày trên.",
            })

        return alerts

    def _extract_columns(
        self, df: pd.DataFrame, mapping_result: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[str]]:
        date_col = None
        sku_col = None

        if mapping_result and 'mappings' in mapping_result:
            for item in mapping_result['mappings']:
                src = item.get('source_column')
                can = item.get('canonical_field')
                if src and src in df.columns:
                    if can == 'date':
                        date_col = src
                    elif can == 'sku':
                        sku_col = src

        for col in df.columns:
            cl = col.lower().strip()
            if not date_col and any(k in cl for k in ('date', 'time', 'ngày', 'trans_date')):
                date_col = col
            elif not sku_col and any(k in cl for k in ('sku', 'item_id', 'product_id', 'code')):
                sku_col = col

        return date_col, sku_col

    def _empty_freshness_report(self, reason: str) -> Dict[str, Any]:
        return {
            'sessionId': self.session_id,
            'freshnessStatus': 'OUTDATED',
            'freshnessDays': 999,
            'decisionGuard': {
                'canRunCurrentAnalysis': False,
                'guardReason': reason,
            },
            'alerts': [{
                'alertId': 'ALT_EMPTY_DATASET',
                'severity': 'CRITICAL',
                'title': '⚠ Dữ liệu không hợp lệ',
                'message': reason,
                'recommendation': 'Upload file dữ liệu giao dịch đúng định dạng.',
            }],
            'coverageReport': {'activeCoverageDays': 0, 'missingDaysCount': 0},
            'skuFreshnessSummary': {'totalSkusProfiled': 0},
        }
