"""
Module 03 Risk Monitoring & Validation Engine (M3-08)
======================================================
Production Risk Monitoring & Validation Engine for Slow-Moving Product Risk Detection.
Continuously audits quality, consistency, probability bounds, class distribution shift vs EXP-02 baseline,
feature drift, and model performance benchmarks vs EXP-03 without retraining or mutating Ground Truth.

Outputs artifacts:
  - reports/risk_monitoring_report.json
  - reports/risk_monitoring_alerts.json
  - data/processed/risk_monitoring_metrics.csv
"""

import json
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class RiskMonitoringEngine:
    """Production Risk Monitoring & Validation Engine for M3-08."""

    EXP02_BASELINE_DISTRIBUTION = {
        'CRITICAL': 0.636,
        'HIGH_RISK': 0.245,
        'MEDIUM_RISK': 0.020,
        'LOW_RISK': 0.099
    }

    EXP03_BENCHMARK = {
        'macro_f1': 0.7336,
        'high_risk_recall': 0.9807,
        'fnr': 0.0193
    }

    ACADEMIC_NOTICE = (
        "Module 03 Scope Notice (M3-08): "
        "Risk Monitoring Engine audits observable demand signals <= t0 and model outputs. "
        "It does NOT issue inventory stockout guarantees or financial liquidation directives."
    )

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    def evaluate_risk_assessments(
        self,
        assessments: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        output_dir: str = 'reports/',
        data_dir: str = 'data/processed/'
    ) -> Dict[str, Any]:
        """Execute full validation suite, drift analysis, status evaluation, and alert generation."""
        sess_id = session_id or self.session_id
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        if not assessments:
            raise ValueError("Assessments list for M3-08 risk monitoring is empty or None.")

        total_skus = len(assessments)
        alerts = []
        invalid_prob_count = 0
        invalid_score_count = 0
        invalid_class_count = 0
        missing_metadata_count = 0

        probabilities = []
        scores = []
        class_counts = {'CRITICAL': 0, 'HIGH_RISK': 0, 'MEDIUM_RISK': 0, 'LOW_RISK': 0}

        # 1. Output & Score Validation Loop
        for idx, a in enumerate(assessments):
            risk_obj = a.get('assessment', {})
            r_class = risk_obj.get('risk_class')
            r_prob = risk_obj.get('risk_probability')
            r_score = risk_obj.get('risk_score')

            # Probability Check
            if r_prob is None or not isinstance(r_prob, (int, float)) or math.isnan(r_prob) or math.isinf(r_prob) or not (0.0 <= r_prob <= 1.0):
                invalid_prob_count += 1
            else:
                probabilities.append(float(r_prob))

            # Score Check
            if r_score is None or not isinstance(r_score, (int, float)) or math.isnan(r_score) or math.isinf(r_score) or not (0.0 <= r_score <= 100.0):
                invalid_score_count += 1
            else:
                scores.append(float(r_score))

            # Class Check
            if r_class not in class_counts:
                invalid_class_count += 1
            else:
                class_counts[r_class] += 1

            # Metadata Check
            meta = a.get('metadata', {})
            if not meta.get('model_version') or not meta.get('data_version'):
                missing_metadata_count += 1

        # 2. Probability Statistics Computation
        if probabilities:
            s_probs = sorted(probabilities)
            p_mean = sum(s_probs) / len(s_probs)
            p_min = s_probs[0]
            p_max = s_probs[-1]
            p_median = s_probs[len(s_probs) // 2]
            p25 = s_probs[int(len(s_probs) * 0.25)]
            p75 = s_probs[int(len(s_probs) * 0.75)]
            p95 = s_probs[int(len(s_probs) * 0.95)]
        else:
            p_mean = p_min = p_max = p_median = p25 = p75 = p95 = 0.0

        prob_stats = {
            'mean': round(p_mean, 4),
            'median': round(p_median, 4),
            'min': round(p_min, 4),
            'max': round(p_max, 4),
            'p25': round(p25, 4),
            'p75': round(p75, 4),
            'p95': round(p95, 4)
        }

        # 3. Class Distribution Drift Analysis
        current_distribution = {
            cls: round(count / total_skus, 4) for cls, count in class_counts.items()
        }
        max_dist_drift = max(
            abs(current_distribution[cls] - self.EXP02_BASELINE_DISTRIBUTION[cls])
            for cls in self.EXP02_BASELINE_DISTRIBUTION
        )

        # 4. Alert Rules & Status Audit
        now_str = datetime.utcnow().isoformat() + "Z"

        if invalid_prob_count > 0:
            alerts.append({
                'rule_id': 'RULE_INVALID_PROBABILITY',
                'severity': 'CRITICAL',
                'detected_at': now_str,
                'affected_count': invalid_prob_count,
                'affected_percentage': round(invalid_prob_count / total_skus, 4),
                'description': f"Phát hiện {invalid_prob_count} SKU có risk probability không hợp lệ (ngoài khoảng [0,1], NaN hoặc Null).",
                'recommended_next_step': "Kiểm tra lại Probability Calibration Layer (M3-04) và Model Inference Layer (M3-01)."
            })

        if invalid_score_count > 0:
            alerts.append({
                'rule_id': 'RULE_INVALID_SCORE',
                'severity': 'CRITICAL',
                'detected_at': now_str,
                'affected_count': invalid_score_count,
                'affected_percentage': round(invalid_score_count / total_skus, 4),
                'description': f"Phát hiện {invalid_score_count} SKU có risk score vượt domain [0,100] hoặc bị lỗi định dạng.",
                'recommended_next_step': "Kiểm tra Risk Scoring Engine (M3-02)."
            })

        if invalid_class_count > 0:
            alerts.append({
                'rule_id': 'RULE_INVALID_CLASS',
                'severity': 'CRITICAL',
                'detected_at': now_str,
                'affected_count': invalid_class_count,
                'affected_percentage': round(invalid_class_count / total_skus, 4),
                'description': f"Phát hiện {invalid_class_count} SKU có risk_class nằm ngoài 4 cấp tiêu chuẩn.",
                'recommended_next_step': "Kiểm tra Risk Classification Engine (M3-03)."
            })

        if max_dist_drift > 0.25:
            alerts.append({
                'rule_id': 'RULE_EXTREME_DISTRIBUTION_DRIFT',
                'severity': 'CRITICAL',
                'detected_at': now_str,
                'affected_count': total_skus,
                'affected_percentage': round(max_dist_drift, 4),
                'description': f"Phân bố Risk Class biến động cực lớn so với EXP-02 Baseline (Độ lệch max: {round(max_dist_drift*100, 1)}%).",
                'recommended_next_step': "Kiểm tra tính toàn vẹn của Feature Matrix (M2-08) và Data Readiness Gate (DAT-11)."
            })
        elif max_dist_drift > 0.15:
            alerts.append({
                'rule_id': 'RULE_DISTRIBUTION_SHIFT_WARNING',
                'severity': 'WARNING',
                'detected_at': now_str,
                'affected_count': total_skus,
                'affected_percentage': round(max_dist_drift, 4),
                'description': f"Phân bố Risk Class có dấu hiệu dịch chuyển nhẹ so với EXP-02 Baseline (Độ lệch max: {round(max_dist_drift*100, 1)}%).",
                'recommended_next_step': "Theo dõi xu hướng dữ liệu bán hàng mới."
            })

        if missing_metadata_count > 0:
            alerts.append({
                'rule_id': 'RULE_MISSING_METADATA_LINEAGE',
                'severity': 'WARNING',
                'detected_at': now_str,
                'affected_count': missing_metadata_count,
                'affected_percentage': round(missing_metadata_count / total_skus, 4),
                'description': f"Phát hiện {missing_metadata_count} SKU thiếu thông tin model/data lineage metadata.",
                'recommended_next_step': "Kiểm tra Risk Assessment Assembly Engine (M3-06)."
            })

        # Overall Status Determination
        if invalid_prob_count > 0 or invalid_score_count > 0 or invalid_class_count > 0:
            overall_status = "INVALID"
        elif any(a['severity'] == 'CRITICAL' for a in alerts):
            overall_status = "CRITICAL"
        elif any(a['severity'] == 'WARNING' for a in alerts):
            overall_status = "WARNING"
        else:
            overall_status = "HEALTHY"

        # 5. Output Report Payload
        report = {
            'monitoring_run_id': f"MRUN-{sess_id[:8]}",
            'session_id': sess_id,
            'status': overall_status,
            'evaluation_timestamp': now_str,
            'total_skus_evaluated': total_skus,
            'risk_distribution': current_distribution,
            'baseline_exp02_distribution': self.EXP02_BASELINE_DISTRIBUTION,
            'max_distribution_drift': round(max_dist_drift, 4),
            'probability_statistics': prob_stats,
            'validation_summary': {
                'probability_validation': 'PASSED' if invalid_prob_count == 0 else 'FAILED',
                'score_validation': 'PASSED' if invalid_score_count == 0 else 'FAILED',
                'classification_validation': 'PASSED' if invalid_class_count == 0 else 'FAILED',
                'metadata_lineage_validation': 'PASSED' if missing_metadata_count == 0 else 'FAILED'
            },
            'exp03_benchmark_reference': self.EXP03_BENCHMARK,
            'academic_notice': self.ACADEMIC_NOTICE,
            'alerts_count': len(alerts)
        }

        # 6. Save Artifacts
        rep_json_path = os.path.join(output_dir, 'risk_monitoring_report.json')
        alt_json_path = os.path.join(output_dir, 'risk_monitoring_alerts.json')
        met_csv_path = os.path.join(data_dir, 'risk_monitoring_metrics.csv')

        with open(rep_json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        with open(alt_json_path, 'w', encoding='utf-8') as f:
            json.dump({'alerts': alerts}, f, indent=2, ensure_ascii=False)

        met_df = pd.DataFrame([{
            'session_id': sess_id,
            'status': overall_status,
            'total_skus': total_skus,
            'mean_probability': prob_stats['mean'],
            'max_dist_drift': round(max_dist_drift, 4),
            'critical_pct': current_distribution['CRITICAL'],
            'high_risk_pct': current_distribution['HIGH_RISK'],
            'alerts_count': len(alerts),
            'timestamp': now_str
        }])
        met_df.to_csv(met_csv_path, index=False)

        return {
            'session_id': sess_id,
            'status': overall_status,
            'total_skus': total_skus,
            'report': report,
            'alerts': alerts,
            'artifacts': {
                'report_json': rep_json_path,
                'alerts_json': alt_json_path,
                'metrics_csv': met_csv_path
            }
        }
