"""
CSV Format Validator — Module 01 Ingestion (IR-001)
===================================================
Enforces structural, encoding, header, quote, and row-level validation
for CSV files before entering the processing pipeline.
"""

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple


class ValidationStatus:
    VALIDATED = "VALIDATED"
    WARNING = "WARNING"
    REJECT = "REJECT"


class CSVValidationResult:
    """Container holding validation status and detailed findings."""

    def __init__(self):
        self.status: str = ValidationStatus.VALIDATED
        self.encoding: str = "utf-8"
        self.delimiter: str = ","
        self.headers: List[str] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.corrupted_rows: List[Dict[str, Any]] = []
        self.empty_rows_count: int = 0
        self.total_rows: int = 0
        self.valid_rows_count: int = 0

    def add_error(self, message: str):
        self.errors.append(message)
        self.status = ValidationStatus.REJECT

    def add_warning(self, message: str):
        self.warnings.append(message)
        if self.status != ValidationStatus.REJECT:
            self.status = ValidationStatus.WARNING

    def add_corrupted_row(self, line_number: int, raw_content: str, reason: str):
        self.corrupted_rows.append({
            "line_number": line_number,
            "raw_content": raw_content[:200],  # truncate long raw lines for safety
            "reason": reason
        })
        self.add_warning(f"Dòng {line_number} bị lỗi cấu trúc: {reason}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "headers": self.headers,
            "errors": self.errors,
            "warnings": self.warnings,
            "corruptedRows": self.corrupted_rows,
            "emptyRowsCount": self.empty_rows_count,
            "totalRows": self.total_rows,
            "validRowsCount": self.valid_rows_count,
        }


class CSVFormatValidator:
    """Validator enforcing IR-001 CSV File Format Validation requirements."""

    SUPPORTED_ENCODINGS = ["utf-8", "utf-8-sig", "ascii", "iso-8859-1", "cp1252", "latin-1"]
    
    # Core domain columns required for SupplyForge AI ingestion
    DEFAULT_REQUIRED_KEYWORD_GROUPS = [
        # At least one SKU / product identifier
        ["sku", "item_code", "product_id", "product_code", "mã", "ma_sp", "barcode", "model_id", "item_id", "tên", "product", "name", "item_sku", "product_name"],
    ]

    # Standard expected columns for SupplyForge AI
    STANDARD_EXPECTED_KEYWORDS = re.compile(
        r'(sku|item|product|name|tên|mã|code|quantity|qty|số lượng|so_luong|sl|price|giá|cost|vốn|date|ngày|time|timestamp|order|expire|hsd|tồn)',
        re.IGNORECASE
    )

    @classmethod
    def validate_file(
        self,
        file_path_or_obj: Any,
        required_columns: Optional[List[str]] = None,
        custom_delimiter: Optional[str] = None
    ) -> CSVValidationResult:
        """Validate a CSV file path or file-like object against IR-001 rules."""
        result = CSVValidationResult()

        # 1. Read byte sample for encoding and non-empty check
        byte_sample, is_file_path = self._read_initial_bytes(file_path_or_obj)

        if not byte_sample or len(byte_sample.strip()) == 0:
            result.add_error("File rỗng (0 bytes).")
            return result

        # Check for binary file / null bytes
        if b'\x00' in byte_sample[:1024]:
            result.add_error("File không phải CSV hợp lệ (phát hiện dữ liệu nhị phân).")
            return result

        # 2. Detect & validate encoding
        detected_encoding, decode_error = self._detect_encoding(byte_sample)
        if decode_error or not detected_encoding:
            result.add_error(f"Encoding không được hỗ trợ hoặc file bị hỏng: {decode_error}")
            return result
        result.encoding = detected_encoding

        # 3. Detect delimiter & quotation syntax
        text_content = self._get_text_stream(file_path_or_obj, is_file_path, detected_encoding)
        if text_content is None:
            result.add_error("Không thể đọc dữ liệu văn bản từ file.")
            return result

        first_lines = []
        text_stream = io.StringIO(text_content)
        for _ in range(20):
            line = text_stream.readline()
            if not line:
                break
            first_lines.append(line)

        if not first_lines:
            result.add_error("File rỗng (không có dòng dữ liệu).")
            return result

        sample_str = "".join(first_lines)
        delimiter = custom_delimiter or self._detect_delimiter(sample_str)
        result.delimiter = delimiter

        # 4. Header Validation
        text_stream.seek(0)
        reader = None
        try:
            reader = csv.reader(text_stream, delimiter=delimiter)
            first_row = next(reader, None)
        except Exception as e:
            result.add_error(f"Không thể parse header CSV với delimiter '{delimiter}': {str(e)}")
            return result

        if not first_row or len(first_row) == 0 or all(not str(cell).strip() for cell in first_row):
            result.add_error("Không có header hợp lệ.")
            return result

        raw_headers = [str(col).strip() for col in first_row]
        
        # Check duplicate headers
        seen_headers = set()
        duplicates = set()
        for idx, h in enumerate(raw_headers):
            h_clean = h.lower()
            if not h_clean:
                h_clean = f"unnamed_{idx}"
            if h_clean in seen_headers:
                duplicates.add(h)
            seen_headers.add(h_clean)

        if duplicates:
            dup_str = ", ".join([f"'{d}'" for d in sorted(list(duplicates))])
            result.add_error(f"Phát hiện cột trùng lặp trong header: {dup_str}.")
            return result

        result.headers = raw_headers
        expected_col_count = len(raw_headers)

        # 5. Missing Required Columns check
        if required_columns:
            # Explicit required columns supplied
            headers_lower = [h.lower() for h in raw_headers]
            missing_cols = [req for req in required_columns if req.lower() not in headers_lower]
            if missing_cols:
                result.add_error(f"Thiếu các cột bắt buộc: {', '.join(missing_cols)}.")
                return result
        else:
            # Keyword heuristic required group check
            headers_concat = " ".join(raw_headers).lower()
            has_sku = False
            for group in self.DEFAULT_REQUIRED_KEYWORD_GROUPS:
                if any(re.search(r'\b' + re.escape(kw) + r'\b', headers_concat) for kw in group):
                    has_sku = True
                    break
            if not has_sku:
                result.add_error("Thiếu required column: Không tìm thấy cột định danh sản phẩm (SKU/Tên sản phẩm/Mã SP).")
                return result

        # Check for unexpected extra columns
        extra_cols = [
            col for col in raw_headers 
            if col and not self.STANDARD_EXPECTED_KEYWORDS.search(col)
        ]
        if extra_cols and len(extra_cols) > 3:
            result.add_warning(f"Có extra columns trong header: {', '.join(extra_cols[:5])}.")

        # 6. Row-by-row parsing and malformed row detection
        line_num = 1  # Header was line 1
        valid_rows = 0
        total_data_rows = 0

        while True:
            try:
                row = next(reader, None)
                if row is None:
                    break
                line_num += 1
                total_data_rows += 1

                # Check empty row
                if len(row) == 0 or all(not str(cell).strip() for cell in row):
                    result.empty_rows_count += 1
                    continue

                # Check column count mismatch
                if len(row) != expected_col_count:
                    result.add_corrupted_row(
                        line_number=line_num,
                        raw_content=",".join(row),
                        reason=f"Số lượng column không khớp (kỳ vọng {expected_col_count}, thực tế {len(row)})"
                    )
                    continue

                valid_rows += 1

            except csv.Error as e:
                line_num += 1
                total_data_rows += 1
                result.add_corrupted_row(
                    line_number=line_num,
                    raw_content="<malformed quotation/csv row>",
                    reason=f"Lỗi quotation / cú pháp CSV: {str(e)}"
                )
            except Exception as e:
                line_num += 1
                total_data_rows += 1
                result.add_corrupted_row(
                    line_number=line_num,
                    raw_content="<corrupted row>",
                    reason=f"Dòng dữ liệu bị hỏng: {str(e)}"
                )

        result.total_rows = total_data_rows
        result.valid_rows_count = valid_rows

        if total_data_rows == 0:
            result.add_error("File rỗng (chỉ có header, không có dòng dữ liệu).")

        return result

    @classmethod
    def _read_initial_bytes(cls, file_path_or_obj: Any) -> Tuple[bytes, bool]:
        """Read up to 64KB sample bytes from file path or object."""
        if isinstance(file_path_or_obj, str):
            try:
                with open(file_path_or_obj, 'rb') as f:
                    return f.read(65536), True
            except Exception:
                return b"", True
        else:
            if hasattr(file_path_or_obj, 'seek'):
                file_path_or_obj.seek(0)
            sample = file_path_or_obj.read(65536)
            if hasattr(file_path_or_obj, 'seek'):
                file_path_or_obj.seek(0)
            if isinstance(sample, str):
                return sample.encode('utf-8'), False
            return sample, False

    @classmethod
    def _detect_encoding(cls, byte_sample: bytes) -> Tuple[Optional[str], Optional[str]]:
        """Probe sample bytes against supported encodings."""
        for enc in cls.SUPPORTED_ENCODINGS:
            try:
                byte_sample.decode(enc)
                return enc, None
            except (UnicodeDecodeError, LookupError):
                continue
        return None, "File không khớp với các encoding hỗ trợ (UTF-8, ASCII, ISO-8859-1, CP1252)."

    @classmethod
    def _get_text_stream(cls, file_path_or_obj: Any, is_file_path: bool, encoding: str) -> Optional[str]:
        """Retrieve full text content decoded with the confirmed encoding."""
        try:
            if is_file_path:
                with open(file_path_or_obj, 'r', encoding=encoding, errors='replace') as f:
                    return f.read()
            else:
                if hasattr(file_path_or_obj, 'seek'):
                    file_path_or_obj.seek(0)
                raw = file_path_or_obj.read()
                if hasattr(file_path_or_obj, 'seek'):
                    file_path_or_obj.seek(0)
                if isinstance(raw, bytes):
                    return raw.decode(encoding, errors='replace')
                return raw
        except Exception:
            return None

    @classmethod
    def _detect_delimiter(cls, sample_str: str) -> str:
        """Sniff delimiter from sample string, fallback to comma."""
        delimiters = [',', ';', '\t', '|']
        counts = {d: 0 for d in delimiters}

        for line in sample_str.splitlines()[:5]:
            for d in delimiters:
                counts[d] += line.count(d)

        best_delimiter = max(counts, key=counts.get)
        if counts[best_delimiter] == 0:
            return ','
        return best_delimiter
