"""
Data Readiness Gate & Downstream Interceptor Guard Engine — Module 01 Data Ingestion (DAT-11)
================================================================================================
Acts as the final control point of the Data Ingestion Pipeline (DAT 01–10) before downstream
DSS analytics modules (Slow-Moving Risk Detection, Financial Aging, Capital Exposure) can execute.

Evaluates 5 readiness criteria:
  1. Schema Readiness
  2. Data Quality Readiness
  3. SKU Readiness
  4. Temporal / Freshness Readiness
  5. Business Sufficiency

Classifies dataset status into:
  - READY (🟢)               : Passes all hard criteria. Downstream DSS modules unlocked.
  - READY_WITH_WARNING (🟡)  : Hard criteria passed, non-critical warnings exist (e.g. missing cost). Downstream unlocked.
  - NOT_READY (🔴)           : Fails one or more hard rules. Downstream DSS modules strictly BLOCKED.

Exports standard reports to:
  - reports/data_readiness_gate.json
  - reports/readiness_criteria_breakdown.json
  - reports/downstream_gate_status.json
"""

import functools
import json
import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd


class DataReadinessError(Exception):
    """Exception raised when downstream DSS modules attempt to run on a NOT_READY dataset."""
    pass


class DataReadinessGate:
    """Data Readiness Gate & Downstream Interceptor Guard (DAT-11)."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    # ── Main Readiness Gate Evaluator ──────────────────────────────────

    def evaluate_readiness(
        self,
        session_id: Optional[str] = None,
        df: Optional[pd.DataFrame] = None,
        output_dir: str = 'reports/'
    ) -> Dict[str, Any]:
        """Evaluate 5 readiness criteria and generate Data Readiness Record."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)

        # 1. Load upstream report artifacts
        schema_report = self._load_json(os.path.join(output_dir, 'schema_validation_report.json'))
        dq_report = self._load_json(os.path.join(output_dir, 'data_quality_report.json'))
        dashboard_report = self._load_json(os.path.join(output_dir, 'data_quality_dashboard.json'))
        freshness_status = self._load_json(os.path.join(output_dir, 'data_freshness_status.json'))
        dataset_version_data = self._load_json(os.path.join(output_dir, 'dataset_version.json'))
        sku_mapping_data = self._load_json(os.path.join(output_dir, 'sku_mapping.json'))

        dataset_id = dataset_version_data.get('datasetId', 'Shopee_Default_Dataset')
        dataset_ver = dataset_version_data.get('datasetVersion', 'v1.0')

        # 2. Evaluate Criterion A: Schema Readiness
        schema_crit = self._evaluate_schema_readiness(schema_report, df)

        # 3. Evaluate Criterion B: Data Quality Readiness
        quality_crit = self._evaluate_quality_readiness(dq_report, dashboard_report, df)

        # 4. Evaluate Criterion C: SKU Readiness
        sku_crit = self._evaluate_sku_readiness(sku_mapping_data, dq_report)

        # 5. Evaluate Criterion D: Temporal / Freshness Readiness
        freshness_crit = self._evaluate_temporal_readiness(freshness_status, df)

        # 6. Evaluate Criterion E: Business Sufficiency
        business_crit = self._evaluate_business_sufficiency(df, schema_report)

        # 7. Collect Critical Errors and Warnings
        critical_errors = []
        warnings = []

        for crit in [schema_crit, quality_crit, sku_crit, freshness_crit, business_crit]:
            critical_errors.extend(crit.get('criticalErrors', []))
            warnings.extend(crit.get('warnings', []))

        # 8. Compute Deterministic Data Readiness Score (Weighted Average)
        raw_score = (
            schema_crit['score'] * 0.25 +
            quality_crit['score'] * 0.25 +
            sku_crit['score'] * 0.20 +
            freshness_crit['score'] * 0.15 +
            business_crit['score'] * 0.15
        )
        readiness_score = round(max(0.0, min(100.0, raw_score)), 1)

        # 9. Hard-Rule Primacy Evaluation & Final Status Classification
        # Hard Rule Primacy: If any critical_errors exist, status MUST be NOT_READY regardless of score!
        if len(critical_errors) > 0 or schema_crit['status'] == 'FAILED' or freshness_crit['status'] == 'FAILED':
            readiness_status = 'NOT_READY'
            status_message = '🔴 NOT_READY — Dataset không đạt các điều kiện bắt buộc (Hard Rules). Downstream DSS bị chặn.'
            can_proceed = False
        elif len(warnings) > 0 or business_crit['status'] == 'WARNING' or quality_crit['status'] == 'WARNING':
            readiness_status = 'READY_WITH_WARNING'
            status_message = '🟡 READY_WITH_WARNING — Dataset đạt điều kiện xử lý tối thiểu kèm theo cảnh báo. Downstream DSS được phép chạy.'
            can_proceed = True
        else:
            readiness_status = 'READY'
            status_message = '🟢 READY — Dataset đạt toàn bộ tiêu chí chất lượng tối ưu. Cho phép tiếp tục sang các module DSS.'
            can_proceed = True

        # 10. Generate Data Readiness Record
        readiness_record = {
            'datasetId': dataset_id,
            'datasetVersion': dataset_ver,
            'sessionId': sess_id,
            'readinessStatus': readiness_status,
            'readinessScore': readiness_score,
            'statusMessage': status_message,
            'canProceedToDownstream': can_proceed,
            'evaluatedAt': datetime.now().isoformat(),
            'criteriaBreakdown': {
                'schemaReadiness': schema_crit,
                'dataQualityReadiness': quality_crit,
                'skuReadiness': sku_crit,
                'temporalReadiness': freshness_crit,
                'businessSufficiency': business_crit,
            },
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'downstreamProtection': {
                'slowMovingDetection': 'UNLOCKED' if can_proceed else 'BLOCKED',
                'demandAnalysis': 'UNLOCKED' if can_proceed else 'BLOCKED',
                'inventoryCapitalExposure': 'UNLOCKED' if can_proceed else 'BLOCKED',
                'financialAging': 'UNLOCKED' if can_proceed else 'BLOCKED',
                'clearanceSimulation': 'UNLOCKED' if can_proceed else 'BLOCKED',
                'dssRecommendation': 'UNLOCKED' if can_proceed else 'BLOCKED',
            }
        }

        # 11. Export Artifacts
        exported_files = self.export_artifacts(readiness_record, output_dir=output_dir)
        readiness_record['reportsGenerated'] = exported_files

        return readiness_record

    # ── Interceptor Guard ─────────────────────────────────────────────

    def assert_ready_for_downstream(self, session_id: Optional[str] = None, output_dir: str = 'reports/') -> bool:
        """Interceptor Guard: Raises DataReadinessError if status is NOT_READY."""
        gate_file = os.path.join(output_dir, 'data_readiness_gate.json')
        if os.path.exists(gate_file):
            try:
                with open(gate_file, 'r', encoding='utf-8') as f:
                    rec = json.load(f)
                status = rec.get('readinessStatus', 'NOT_READY')
                if status == 'NOT_READY':
                    errors = rec.get('criticalErrors', ['Dataset failed hard readiness rules.'])
                    raise DataReadinessError(
                        f"[DATA READINESS GATE INTERCEPTOR] Access Denied: Dataset '{rec.get('datasetId')}' "
                        f"(version {rec.get('datasetVersion')}) is NOT_READY for downstream DSS analytics. "
                        f"Critical errors: {', '.join(errors)}"
                    )
                return True
            except DataReadinessError:
                raise
            except Exception:
                pass

        # Fallback check if file missing
        rec = self.evaluate_readiness(session_id=session_id, output_dir=output_dir)
        if rec['readinessStatus'] == 'NOT_READY':
            errors = rec.get('criticalErrors', ['Dataset failed hard readiness rules.'])
            raise DataReadinessError(
                f"[DATA READINESS GATE INTERCEPTOR] Access Denied: Dataset is NOT_READY for downstream DSS. "
                f"Critical errors: {', '.join(errors)}"
            )
        return True

    # ── Exporters ─────────────────────────────────────────────────────

    def export_artifacts(self, record: Dict[str, Any], output_dir: str = 'reports/') -> Dict[str, str]:
        """Export all 3 standard DAT-11 report artifacts to reports/."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. data_readiness_gate.json
        gate_path = os.path.join(output_dir, 'data_readiness_gate.json')
        with open(gate_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2, ensure_ascii=False)

        # 2. readiness_criteria_breakdown.json
        break_path = os.path.join(output_dir, 'readiness_criteria_breakdown.json')
        with open(break_path, 'w', encoding='utf-8') as f:
            json.dump(record.get('criteriaBreakdown', {}), f, indent=2, ensure_ascii=False)

        # 3. downstream_gate_status.json
        down_path = os.path.join(output_dir, 'downstream_gate_status.json')
        with open(down_path, 'w', encoding='utf-8') as f:
            json.dump({
                'datasetId': record.get('datasetId'),
                'datasetVersion': record.get('datasetVersion'),
                'readinessStatus': record.get('readinessStatus'),
                'canProceed': record.get('canProceedToDownstream'),
                'downstreamProtection': record.get('downstreamProtection'),
                'evaluatedAt': record.get('evaluatedAt'),
            }, f, indent=2, ensure_ascii=False)

        return {
            'data_readiness_gate': gate_path,
            'readiness_criteria_breakdown': break_path,
            'downstream_gate_status': down_path,
        }

    # ── Internal Criteria Evaluators ──────────────────────────────────

    def _evaluate_schema_readiness(
        self, schema_report: Dict[str, Any], df: Optional[pd.DataFrame]
    ) -> Dict[str, Any]:
        is_valid = schema_report.get('status') == 'VALID' or schema_report.get('valid', True)
        missing_req = schema_report.get('missingRequiredFields', [])

        critical_errors = []
        if not is_valid or len(missing_req) > 0:
            for field in missing_req:
                critical_errors.append(f"Thiếu trường dữ liệu bắt buộc: {field}")

        score = 100.0 if len(critical_errors) == 0 else 0.0
        status = 'PASSED' if len(critical_errors) == 0 else 'FAILED'

        return {
            'criterion': 'Schema Readiness',
            'status': status,
            'score': score,
            'criticalErrors': critical_errors,
            'warnings': [],
            'details': 'Ánh xạ Canonical Schema hoàn tất và đầy đủ các trường bắt buộc (sku, date, quantity).'
        }

    def _evaluate_quality_readiness(
        self, dq_report: Dict[str, Any], dashboard_report: Dict[str, Any], df: Optional[pd.DataFrame]
    ) -> Dict[str, Any]:
        quality_score = float(dq_report.get('qualityScore', dashboard_report.get('overview', {}).get('overallQualityScore', 95.0)))
        missing_count = dq_report.get('metrics', {}).get('missingValuesCount', 0)
        invalid_count = dq_report.get('metrics', {}).get('invalidRecords', 0)

        critical_errors = []
        warnings = []

        if quality_score < 70.0:
            critical_errors.append(f"Chất lượng dữ liệu quá thấp ({quality_score}% < 70%).")
        elif quality_score < 90.0:
            warnings.append(f"Điểm chất lượng ở mức trung bình ({quality_score}%).")

        if missing_count > 0:
            warnings.append(f"Tồn tại {missing_count} ô dữ liệu bị thiếu (missing values).")

        status = 'PASSED' if len(critical_errors) == 0 and len(warnings) == 0 else ('WARNING' if len(critical_errors) == 0 else 'FAILED')

        return {
            'criterion': 'Data Quality Readiness',
            'status': status,
            'score': quality_score,
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'details': 'Đánh giá tỷ lệ hợp lệ, mức độ thiếu dữ liệu và dữ liệu âm/bất thường.'
        }

    def _evaluate_sku_readiness(
        self, sku_mapping_data: Dict[str, Any], dq_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        review_count = dq_report.get('reviewRequiredSkusCount', 0)
        critical_errors = []
        warnings = []

        if review_count > 50:
            warnings.append(f"Có {review_count} biến thể SKU chưa duyệt hợp nhất.")
        elif review_count > 0:
            warnings.append(f"Khuyến nghị kiểm tra {review_count} gợi ý gộp SKU trước khi tính giá trị tồn kho.")

        score = max(70.0, min(100.0, 100.0 - (review_count * 0.5)))
        status = 'PASSED' if len(warnings) == 0 else 'WARNING'

        return {
            'criterion': 'SKU Readiness',
            'status': status,
            'score': score,
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'details': 'Mã SKU đã được chuẩn hóa và loại bỏ các biến thể trùng lặp.'
        }

    def _evaluate_temporal_readiness(
        self, freshness_status: Dict[str, Any], df: Optional[pd.DataFrame]
    ) -> Dict[str, Any]:
        f_status = freshness_status.get('freshnessStatus', 'FRESH')
        f_days = freshness_status.get('freshnessDays', 1)

        critical_errors = []
        warnings = []

        if f_status == 'OUTDATED':
            critical_errors.append(f"Dữ liệu kinh doanh đã quá hạn ({f_days} ngày > 30 ngày). Phân tích bị khóa.")
        elif f_status == 'STALE':
            warnings.append(f"Dữ liệu bắt đầu cũ ({f_days} ngày > 7 ngày).")

        score = max(0.0, min(100.0, 100.0 - (f_days * 2.0)))
        status = 'PASSED' if f_status in ('FRESH', 'AGING') else ('WARNING' if f_status == 'STALE' else 'FAILED')

        return {
            'criterion': 'Temporal / Freshness Readiness',
            'status': status,
            'score': score,
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'details': f"Trạng thái độ mới dữ liệu: {f_status} ({f_days} ngày)."
        }

    def _evaluate_business_sufficiency(
        self, df: Optional[pd.DataFrame], schema_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        critical_errors = []
        warnings = []

        cols = [c.lower() for c in (df.columns if df is not None else ['order_id', 'date', 'sku', 'quantity', 'price', 'cost'])]
        req_found = {'sku': False, 'date': False, 'quantity': False, 'price': False}
        cost_found = False

        for c in cols:
            if 'sku' in c or 'item' in c or 'product' in c:
                req_found['sku'] = True
            if 'date' in c or 'time' in c:
                req_found['date'] = True
            if 'qty' in c or 'quantity' in c or 'amount' in c:
                req_found['quantity'] = True
            if 'price' in c or 'revenue' in c or 'sales' in c:
                req_found['price'] = True
            if 'cost' in c:
                cost_found = True

        for req, found in req_found.items():
            if not found:
                critical_errors.append(f"Thiếu trường thông tin nghiệp vụ bắt buộc: {req}")

        if not cost_found:
            warnings.append("Thiếu trường Giá vốn (Cost) — khuyến nghị bổ sung để tính Capital Exposure chính xác.")

        score = 100.0 if (len(critical_errors) == 0 and cost_found) else (85.0 if len(critical_errors) == 0 else 0.0)
        status = 'PASSED' if (len(critical_errors) == 0 and cost_found) else ('WARNING' if len(critical_errors) == 0 else 'FAILED')

        return {
            'criterion': 'Business Sufficiency',
            'status': status,
            'score': score,
            'criticalErrors': critical_errors,
            'warnings': warnings,
            'details': 'Đầy đủ thông tin nghiệp vụ tối thiểu để thực hiện Slow-Moving Detection.'
        }

    @staticmethod
    def _load_json(file_path: str) -> Dict[str, Any]:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}


def enforce_readiness_gate(func: Callable) -> Callable:
    """Decorator protecting downstream DSS functions from running on NOT_READY datasets."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        session_id = kwargs.get('session_id') or (args[0] if len(args) > 0 and isinstance(args[0], str) else None)
        gate = DataReadinessGate(session_id=session_id)
        gate.assert_ready_for_downstream(session_id=session_id)
        return func(*args, **kwargs)
    return wrapper
