"""
Streaming CSV Profiler — Module 01 Data Ingestion
===================================================
Profiles CSV files using line-by-line streaming.
Never loads the entire file into memory.
"""

import csv
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime
from io import TextIOWrapper
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings


# ── Date format candidates (Vietnamese / ISO / common ecommerce) ──────
DATE_FORMATS = [
    '%Y-%m-%d %H:%M:%S',   # 2025-05-14 22:08:00
    '%Y-%m-%d %H:%M',      # 2025-05-14 22:08
    '%Y-%m-%d',             # 2025-05-14
    '%d/%m/%Y %H:%M:%S',   # 14/05/2025 22:08:00
    '%d/%m/%Y %H:%M',      # 14/05/2025 22:08
    '%d/%m/%Y',             # 14/05/2025
    '%m/%d/%Y',             # 05/14/2025
    '%Y/%m/%d',             # 2025/05/14
    '%d-%m-%Y',             # 14-05-2025
    '%Y%m%d',               # 20250514
]

# ── Heuristic keywords for column detection ───────────────────────────
SKU_KEYWORDS = re.compile(
    r'(sku|item_id|item_code|product_id|product_code|mã\b|ma_sp|barcode|model_id)',
    re.IGNORECASE
)
DATE_KEYWORDS = re.compile(
    r'(date|time|ngày|ngay|created|updated|order_date|thời gian|timestamp)',
    re.IGNORECASE
)
QUANTITY_KEYWORDS = re.compile(
    r'(quantity|qty|số lượng|so_luong|sl\b|purchased)',
    re.IGNORECASE
)

# Max rows to sample for type inference
TYPE_INFERENCE_SAMPLE_SIZE = 1000
PREVIEW_ROW_COUNT = 10


from supplyforge.services.csv_validator import CSVFormatValidator, ValidationStatus


class ProfileResult:
    """Container for CSV profiling results."""

    def __init__(self):
        self.total_rows: int = 0
        self.total_columns: int = 0
        self.headers: List[str] = []
        self.column_types: Dict[str, str] = {}
        self.date_range_start: Optional[str] = None
        self.date_range_end: Optional[str] = None
        self.date_column_detected: Optional[str] = None
        self.unique_sku_count: int = 0
        self.sku_column_detected: Optional[str] = None
        self.missing_values: Dict[str, Dict[str, Any]] = {}
        self.preview_rows: List[List[str]] = []
        self.validation: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            'totalRows': self.total_rows,
            'totalColumns': self.total_columns,
            'headers': self.headers,
            'columnTypes': self.column_types,
            'dateRange': {
                'start': self.date_range_start,
                'end': self.date_range_end,
                'spanDays': self._span_days(),
            },
            'dateColumnDetected': self.date_column_detected,
            'uniqueSkuCount': self.unique_sku_count,
            'skuColumnDetected': self.sku_column_detected,
            'missingValues': self.missing_values,
            'previewRows': self.preview_rows,
            'validation': self.validation,
        }

    def _span_days(self) -> Optional[int]:
        if self.date_range_start and self.date_range_end:
            try:
                d0 = datetime.strptime(self.date_range_start, '%Y-%m-%d')
                d1 = datetime.strptime(self.date_range_end, '%Y-%m-%d')
                return (d1 - d0).days
            except Exception:
                pass
        return None


class StreamingCSVProfiler:
    """Streaming CSV profiler that never loads the full file into RAM."""

    # ── File I/O ──────────────────────────────────────────────────────

    @staticmethod
    def get_upload_dir() -> str:
        """Return (and ensure exists) the base ingestion upload directory."""
        upload_dir = getattr(
            settings, 'INGESTION_UPLOAD_DIR',
            os.path.join(settings.BASE_DIR, 'uploads', 'ingestion')
        )
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir

    @staticmethod
    def get_raw_upload_dir() -> str:
        """Return (and ensure exists) the raw upload directory (IR-016)."""
        raw_dir = os.path.join(StreamingCSVProfiler.get_upload_dir(), 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        return raw_dir

    @staticmethod
    def get_processed_upload_dir() -> str:
        """Return (and ensure exists) the processed output directory (IR-016)."""
        processed_dir = os.path.join(StreamingCSVProfiler.get_upload_dir(), 'processed')
        os.makedirs(processed_dir, exist_ok=True)
        return processed_dir

    @staticmethod
    def save_uploaded_file(file_obj) -> Tuple[str, int]:
        """Save an uploaded file to raw disk storage in 8 KB chunks (IR-016 Raw Preservation).

        Returns:
            (raw_storage_path, file_size_bytes)
        """
        raw_dir = StreamingCSVProfiler.get_raw_upload_dir()
        ext = os.path.splitext(file_obj.name)[1] or '.csv'
        unique_name = f"{uuid.uuid4().hex}{ext}"
        storage_path = os.path.join(raw_dir, unique_name)

        total_bytes = 0
        with open(storage_path, 'wb') as dest:
            for chunk in file_obj.chunks(chunk_size=8192):
                dest.write(chunk)
                total_bytes += len(chunk)

        return storage_path, total_bytes

    # ── Main profiling entry ──────────────────────────────────────────

    @staticmethod
    def profile_csv(storage_path: str) -> ProfileResult:
        """Full streaming profile of a CSV file on disk."""
        result = ProfileResult()

        # Run IR-001 format validation
        validation_res = CSVFormatValidator.validate_file(storage_path)
        result.validation = validation_res.to_dict()

        if validation_res.status == ValidationStatus.REJECT:
            result.headers = validation_res.headers
            result.total_columns = len(validation_res.headers)
            result.total_rows = validation_res.total_rows
            return result

        # Detect encoding
        encoding = validation_res.encoding

        # Detect the best date / SKU columns from the header
        headers = validation_res.headers if validation_res.headers else StreamingCSVProfiler._read_headers(storage_path, encoding)
        result.headers = headers
        result.total_columns = len(headers)

        date_col_idx = StreamingCSVProfiler._detect_column(headers, DATE_KEYWORDS)
        sku_col_idx = StreamingCSVProfiler._detect_column(headers, SKU_KEYWORDS)

        if date_col_idx is not None:
            result.date_column_detected = headers[date_col_idx]
        if sku_col_idx is not None:
            result.sku_column_detected = headers[sku_col_idx]

        # ── Single-pass streaming scan ────────────────────────────────
        row_count = 0
        missing_counts: Dict[int, int] = defaultdict(int)
        type_samples: Dict[int, List[str]] = defaultdict(list)
        date_values: List[str] = []
        sku_values: set = set()
        date_format_cache: Optional[str] = None

        with open(storage_path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.reader(f)
            _header_row = next(reader, None)  # skip header

            for row in reader:
                row_count += 1

                # Preview rows
                if row_count <= PREVIEW_ROW_COUNT:
                    result.preview_rows.append(row)

                # Per-column analysis
                for col_idx in range(len(headers)):
                    cell = row[col_idx].strip() if col_idx < len(row) else ''

                    # Missing value tracking
                    if cell == '' or cell.lower() in ('null', 'none', 'n/a', 'na', '-'):
                        missing_counts[col_idx] += 1

                    # Type inference sampling (first N non-empty values)
                    if cell and len(type_samples[col_idx]) < TYPE_INFERENCE_SAMPLE_SIZE:
                        type_samples[col_idx].append(cell)

                # Date column extraction
                if date_col_idx is not None and date_col_idx < len(row):
                    val = row[date_col_idx].strip()
                    if val:
                        date_values.append(val)

                # SKU column extraction
                if sku_col_idx is not None and sku_col_idx < len(row):
                    val = row[sku_col_idx].strip()
                    if val:
                        sku_values.add(val)

        result.total_rows = row_count

        # Quantified SLA Check for IR-011: Maximum 5,000,000 rows
        MAX_ROWS_LIMIT = 5_000_000
        if row_count > MAX_ROWS_LIMIT:
            validation_res.add_error(f"Số lượng bản ghi quá lớn ({row_count:,} dòng, vượt quá giới hạn 5.000.000 dòng). Vui lòng chia nhỏ tệp CSV.")
            result.validation = validation_res.to_dict()
            return result

        # ── Post-scan analysis ────────────────────────────────────────

        # Column types
        for col_idx, col_name in enumerate(headers):
            samples = type_samples.get(col_idx, [])
            result.column_types[col_name] = StreamingCSVProfiler._infer_type(samples)

        # Missing values
        for col_idx, col_name in enumerate(headers):
            count = missing_counts.get(col_idx, 0)
            if count > 0:
                pct = round((count / row_count) * 100, 2) if row_count > 0 else 0
                result.missing_values[col_name] = {'count': count, 'pct': pct}

        # Date range
        if date_values:
            date_format_cache = StreamingCSVProfiler._detect_date_format(date_values[:50])
            if date_format_cache:
                parsed_dates = []
                for dv in date_values:
                    d = StreamingCSVProfiler._try_parse_date(dv, date_format_cache)
                    if d:
                        parsed_dates.append(d)
                if parsed_dates:
                    result.date_range_start = min(parsed_dates).strftime('%Y-%m-%d')
                    result.date_range_end = max(parsed_dates).strftime('%Y-%m-%d')

        # SKU count
        result.unique_sku_count = len(sku_values)

        # If no SKU column was detected by keyword, try heuristic:
        # find the text column with the highest unique ratio
        if sku_col_idx is None and row_count > 0:
            best_col, best_name = StreamingCSVProfiler._heuristic_sku_column(
                storage_path, encoding, headers, row_count
            )
            if best_col is not None:
                result.sku_column_detected = best_name
                # Re-scan for unique count on that column
                result.unique_sku_count = StreamingCSVProfiler._count_unique_column(
                    storage_path, encoding, best_col
                )

        return result

    # ── Helper: encoding detection ────────────────────────────────────

    @staticmethod
    def _detect_encoding(path: str) -> str:
        """Try UTF-8 with BOM, then UTF-8, then fallback to latin-1."""
        for enc in ('utf-8-sig', 'utf-8'):
            try:
                with open(path, 'r', encoding=enc) as f:
                    f.readline()
                return enc
            except (UnicodeDecodeError, UnicodeError):
                continue
        return 'latin-1'

    # ── Helper: read headers ──────────────────────────────────────────

    @staticmethod
    def _read_headers(path: str, encoding: str) -> List[str]:
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.reader(f)
            header_row = next(reader, None)
        return [h.strip() for h in (header_row or [])]

    # ── Helper: detect column by keyword ──────────────────────────────

    @staticmethod
    def _detect_column(headers: List[str], pattern: re.Pattern) -> Optional[int]:
        """Return index of the first header matching the keyword pattern."""
        for idx, h in enumerate(headers):
            if pattern.search(h):
                return idx
        return None

    # ── Helper: type inference ────────────────────────────────────────

    @staticmethod
    def _infer_type(samples: List[str]) -> str:
        """Infer column type from a sample of non-empty string values."""
        if not samples:
            return 'unknown'

        int_count = 0
        float_count = 0
        date_count = 0

        for s in samples[:200]:  # cap analysis to 200 samples
            clean = s.strip()

            # Integer check
            if re.match(r'^-?\d+$', clean):
                int_count += 1
                continue

            # Decimal / currency check
            cleaned_num = re.sub(r'[₫$,\s]', '', clean)
            if re.match(r'^-?\d+\.?\d*$', cleaned_num):
                float_count += 1
                continue

            # Date check
            if StreamingCSVProfiler._try_parse_date(clean) is not None:
                date_count += 1
                continue

        total = len(samples[:200])
        threshold = total * 0.6  # 60% majority

        if int_count >= threshold:
            return 'integer'
        if float_count >= threshold:
            return 'decimal'
        if date_count >= threshold:
            return 'datetime'
        return 'string'

    # ── Helper: date parsing ──────────────────────────────────────────

    @staticmethod
    def _detect_date_format(sample_values: List[str]) -> Optional[str]:
        """Detect the most common date format from a sample."""
        format_votes: Dict[str, int] = defaultdict(int)
        for val in sample_values:
            for fmt in DATE_FORMATS:
                try:
                    datetime.strptime(val.strip(), fmt)
                    format_votes[fmt] += 1
                    break
                except ValueError:
                    continue
        if format_votes:
            return max(format_votes, key=format_votes.get)
        return None

    @staticmethod
    def _try_parse_date(value: str, fmt: Optional[str] = None) -> Optional[datetime]:
        """Try to parse a string into a datetime."""
        clean = value.strip()
        if not clean:
            return None

        if fmt:
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                pass

        for f in DATE_FORMATS:
            try:
                return datetime.strptime(clean, f)
            except ValueError:
                continue
        return None

    # ── Helper: heuristic SKU detection ───────────────────────────────

    @staticmethod
    def _heuristic_sku_column(
        path: str, encoding: str, headers: List[str], total_rows: int
    ) -> Tuple[Optional[int], Optional[str]]:
        """Find the string column with the highest unique-value ratio as SKU candidate."""
        if total_rows == 0:
            return None, None

        uniques: Dict[int, set] = {i: set() for i in range(len(headers))}
        sample_limit = min(total_rows, 2000)

        with open(path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for count, row in enumerate(reader, 1):
                if count > sample_limit:
                    break
                for i in range(min(len(row), len(headers))):
                    val = row[i].strip()
                    if val:
                        uniques[i].add(val)

        best_idx = None
        best_ratio = 0.0
        for i, vals in uniques.items():
            ratio = len(vals) / sample_limit if sample_limit > 0 else 0
            # SKU-like columns have moderate-to-high uniqueness (> 1% but < 95%)
            # and should be string-type
            if 0.01 < ratio < 0.95 and len(vals) > 1:
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = i

        if best_idx is not None:
            return best_idx, headers[best_idx]
        return None, None

    @staticmethod
    def _count_unique_column(path: str, encoding: str, col_idx: int) -> int:
        """Stream-count unique values in a specific column."""
        unique_vals: set = set()
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    if val:
                        unique_vals.add(val)
        return len(unique_vals)


def humanize_bytes(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
