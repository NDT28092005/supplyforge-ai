"""Leakage-safe replay for a proposed slow-moving alert threshold policy.

The replay consumes only facts frozen in ``SlowMovingOutcomeCohort``.  It is
intentionally limited to alert-boundary and confirmation-run changes: a
proposal that changes eligibility, catalog context, source scope or return
handling must be rebuilt from source facts and is rejected here.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from supplyforge.services.slow_moving_quality_monitoring import (
    HIGH_RISK_CLASSES,
    SlowMovingQualityMonitoringService,
)


class SlowMovingPolicyReplayError(ValueError):
    """A proposed policy cannot be evaluated honestly from frozen evidence."""


def load_candidate_policy(path: Path) -> tuple[dict[str, Any], str]:
    """Load the small replay contract and reject out-of-scope policy changes."""
    try:
        raw = path.read_bytes()
        policy = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlowMovingPolicyReplayError('Không đọc được tệp phương án cảnh báo.') from exc
    required = {
        'schema_version', 'version', 'risk_boundaries',
        'consecutive_runs_to_open', 'eligibility_context_policy',
    }
    if required.difference(policy) or policy.get('schema_version') != 'slow-moving-alert-replay-v1':
        raise SlowMovingPolicyReplayError('Tệp phương án cảnh báo không đúng định dạng replay v1.')
    if str(policy.get('eligibility_context_policy') or '').upper() != 'UNCHANGED':
        raise SlowMovingPolicyReplayError(
            'Phương án thay đổi điều kiện dữ liệu hoặc tình trạng hàng phải chạy lại từ dữ liệu nguồn đã đóng băng; không thể so sánh bằng cohort hiện có.'
        )
    boundaries = policy.get('risk_boundaries')
    if not isinstance(boundaries, dict):
        raise SlowMovingPolicyReplayError('Ngưỡng mức cần xem trong phương án không hợp lệ.')
    try:
        medium = float(boundaries.get('medium_at_or_above', 40))
        high = float(boundaries['high_at_or_above'])
        critical = float(boundaries['critical_at_or_above'])
        consecutive = int(policy['consecutive_runs_to_open'])
    except (TypeError, ValueError, KeyError) as exc:
        raise SlowMovingPolicyReplayError('Ngưỡng hoặc số lần xác nhận trong phương án không hợp lệ.') from exc
    if not 0 <= medium <= high <= critical <= 100 or not 1 <= consecutive <= 10:
        raise SlowMovingPolicyReplayError('Ngưỡng hoặc số lần xác nhận trong phương án nằm ngoài phạm vi cho phép.')
    return policy, hashlib.sha256(raw).hexdigest()


class SlowMovingPolicyReplayService:
    """Replay one candidate policy without reading future orders or live facts."""

    @staticmethod
    def _risk_class(score: float, boundaries: dict[str, Any]) -> str:
        if score >= float(boundaries['critical_at_or_above']):
            return 'CRITICAL'
        if score >= float(boundaries['high_at_or_above']):
            return 'HIGH_RISK'
        if score >= float(boundaries.get('medium_at_or_above', 40)):
            return 'MEDIUM_RISK'
        return 'LOW_RISK'

    @staticmethod
    def _metric_rows(rows: list[dict[str, Any]], *, horizon: int, z_score: float, high_max: float) -> dict[str, Any]:
        outcome_key = f'outcome_{horizon}'
        mature = [row for row in rows if row.get(outcome_key) is not None]
        opened_high = [
            row for row in mature
            if row['opened_alert'] and row['risk_class'] in HIGH_RISK_CLASSES
        ]
        opened_critical = [
            row for row in mature
            if row['opened_alert'] and row['risk_class'] == 'CRITICAL'
        ]
        actual_high = [row for row in mature if float(row[outcome_key]) <= high_max]
        true_high = [row for row in opened_high if float(row[outcome_key]) <= high_max]
        true_critical = [row for row in opened_critical if float(row[outcome_key]) == 0]
        return {
            'matured_eligible_skus': len(mature),
            'opened_high_risk_alert_count': len(opened_high),
            'opened_critical_alert_count': len(opened_critical),
            'actual_high_risk_count': len(actual_high),
            'high_risk_true_positive_count': len(true_high),
            'critical_true_positive_count': len(true_critical),
            'high_risk_precision': len(true_high) / len(opened_high) if opened_high else None,
            'high_risk_precision_wilson_lower': SlowMovingQualityMonitoringService.wilson_lower(
                len(true_high), len(opened_high), z_score,
            ),
            'high_risk_recall': len(true_high) / len(actual_high) if actual_high else None,
            'critical_precision': len(true_critical) / len(opened_critical) if opened_critical else None,
            'critical_precision_wilson_lower': SlowMovingQualityMonitoringService.wilson_lower(
                len(true_critical), len(opened_critical), z_score,
            ),
            'opened_alert_rate': len(opened_high) / len(mature) if mature else None,
        }

    @classmethod
    def replay(cls, *, cohorts, candidate_policy: dict[str, Any], quality_policy: dict[str, Any]) -> dict[str, Any]:
        """Evaluate candidate and baseline on exactly the same frozen rows.

        ``cohorts`` must be scope- and score-policy-homogeneous.  The caller
        owns that boundary because it is the essential protection against
        mixing an old import, another warehouse, or a later score policy.
        """
        ordered = sorted(
            cohorts,
            key=lambda row: (row.decision_cutoff, row.canonical_sku, row.source_assessment_key),
        )
        if not ordered:
            raise SlowMovingPolicyReplayError('Không có cohort đóng băng để chạy lại phương án.')
        boundaries = candidate_policy['risk_boundaries']
        consecutive_required = int(candidate_policy['consecutive_runs_to_open'])
        candidate_state: dict[str, dict[str, Any]] = {}
        cutoff_skus: set[tuple[Any, str]] = set()
        candidate_rows: list[dict[str, Any]] = []
        baseline_rows: list[dict[str, Any]] = []

        for cohort in ordered:
            cutoff_sku = (cohort.decision_cutoff, cohort.canonical_sku)
            if cutoff_sku in cutoff_skus:
                raise SlowMovingPolicyReplayError(
                    'Có nhiều cohort cho cùng SKU trong một mốc; không thể xác định thứ tự xác nhận mà không suy đoán.'
                )
            cutoff_skus.add(cutoff_sku)
            snapshot = cohort.rule_snapshot_json if isinstance(cohort.rule_snapshot_json, dict) else {}
            try:
                score = float(snapshot['priority_score'])
            except (KeyError, TypeError, ValueError) as exc:
                raise SlowMovingPolicyReplayError(
                    f'Không có điểm ưu tiên đóng băng cho SKU {cohort.canonical_sku}; không thể replay an toàn.'
                ) from exc
            candidate_risk = cls._risk_class(score, boundaries)
            is_candidate_high = candidate_risk in HIGH_RISK_CLASSES
            state = candidate_state.setdefault(cohort.canonical_sku, {'consecutive': 0, 'open': False})
            opened_now = False
            if is_candidate_high:
                state['consecutive'] += 1
                if not state['open'] and state['consecutive'] >= consecutive_required:
                    state['open'] = True
                    opened_now = True
            else:
                state['consecutive'] = 0
                state['open'] = False
            segment = cohort.segment_json if isinstance(cohort.segment_json, dict) else {}
            shared = {
                'cohort_id': str(cohort.id),
                'cutoff': cohort.decision_cutoff.isoformat(),
                'sku': cohort.canonical_sku,
                'outcome_30': cohort.future_net_fulfilled_units_30,
                'outcome_60': cohort.future_net_fulfilled_units_60,
                'outcome_90': cohort.future_net_fulfilled_units_90,
                'segment': segment,
            }
            candidate_rows.append({
                **shared, 'risk_class': candidate_risk, 'opened_alert': opened_now,
            })
            baseline_rows.append({
                **shared,
                'risk_class': cohort.predicted_risk_class,
                'opened_alert': bool(cohort.opened_alert),
            })

        z_score = float(quality_policy['confidence']['z_score'])
        high_max = float(quality_policy['high_risk_future_quantity_max'])
        minimum_slice_size = int(quality_policy['diagnostics']['minimum_slice_size'])

        def report_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
            slices: dict[str, dict[str, Any]] = {}
            for key in ('category', 'channel', 'warehouse'):
                grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    grouped[str(row['segment'].get(key) or 'UNSPECIFIED')].append(row)
                eligible = {
                    label: cls._metric_rows(values, horizon=60, z_score=z_score, high_max=high_max)
                    for label, values in grouped.items()
                    if len([value for value in values if value['outcome_60'] is not None]) >= minimum_slice_size
                }
                if eligible:
                    slices[key] = eligible
            return {
                'primary_60_days': cls._metric_rows(rows, horizon=60, z_score=z_score, high_max=high_max),
                'sensitivity': {
                    str(horizon): cls._metric_rows(rows, horizon=horizon, z_score=z_score, high_max=high_max)
                    for horizon in (30, 60, 90)
                },
                'diagnostic_slices_60_days': slices,
            }

        return {
            'candidate_policy_version': str(candidate_policy['version']),
            'baseline': report_for(baseline_rows),
            'candidate': report_for(candidate_rows),
            'replay_scope': {
                'cohorts_evaluated': len(candidate_rows),
                'uses_frozen_priority_scores_only': True,
                'uses_future_outcomes_only_after_each_cutoff': True,
                'eligibility_context_policy': 'UNCHANGED',
            },
        }
