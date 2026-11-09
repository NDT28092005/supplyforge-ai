"""Immutable policy contract for slow-moving outcome quality gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUALITY_POLICY_PATH = PROJECT_ROOT / 'config' / 'slow_moving_alert_quality_policy.json'

# These are product safety floors, not tuning defaults.  Relaxing one of
# them would let an unproven alert stream present itself as trustworthy.
PILOT_MINIMUMS = {
    'minimum_matured_eligible_skus': 100,
    'minimum_matured_opened_high_risk_alerts': 30,
    'minimum_distinct_decision_cohorts': 3,
}
NOTIFICATION_MINIMUMS = {
    'minimum_matured_eligible_skus': 500,
    'minimum_matured_opened_high_risk_alerts': 100,
    'minimum_matured_opened_critical_alerts': 30,
    'minimum_distinct_decision_cohorts': 3,
    'minimum_high_risk_precision': 0.70,
    'minimum_high_risk_precision_wilson_lower': 0.60,
    'minimum_high_risk_recall': 0.60,
    'minimum_critical_precision': 0.80,
    'minimum_critical_precision_wilson_lower': 0.65,
    'minimum_eligible_data_coverage': 0.80,
}


class SlowMovingQualityPolicyError(ValueError):
    """Raised when the quality policy is missing or unsafe to apply."""


def _require_at_least(section: dict[str, Any], minimums: dict[str, float | int], name: str) -> None:
    for field, floor in minimums.items():
        if field not in section:
            raise SlowMovingQualityPolicyError(f'Quality policy {name}.{field} is required.')
        try:
            value = float(section[field])
        except (TypeError, ValueError) as exc:
            raise SlowMovingQualityPolicyError(
                f'Quality policy {name}.{field} must be numeric.'
            ) from exc
        if value < float(floor):
            raise SlowMovingQualityPolicyError(
                f'Quality policy {name}.{field} cannot be below {floor}.'
            )


def load_slow_moving_quality_policy(
    path: Path = QUALITY_POLICY_PATH,
) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise SlowMovingQualityPolicyError(f'Quality policy not found: {path}')
    raw = path.read_bytes()
    try:
        policy = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlowMovingQualityPolicyError('Quality policy is not valid JSON.') from exc

    required = {
        'schema_version', 'primary_horizon_days', 'sensitivity_horizon_days',
        'label_grace_days', 'high_risk_future_quantity_max',
        'critical_future_quantity', 'confidence', 'pilot', 'notification',
        'rollback', 'diagnostics',
    }
    missing = sorted(required.difference(policy))
    if missing:
        raise SlowMovingQualityPolicyError(f'Quality policy is missing fields: {missing}')
    if policy['schema_version'] != 'slow-moving-alert-quality-v1':
        raise SlowMovingQualityPolicyError('Quality policy schema version is unsupported.')
    if int(policy['primary_horizon_days']) != 60:
        raise SlowMovingQualityPolicyError('The operational primary horizon must remain 60 days.')
    if sorted({int(value) for value in policy['sensitivity_horizon_days']}) != [30, 60, 90]:
        raise SlowMovingQualityPolicyError('Sensitivity horizons must be exactly 30, 60 and 90 days.')
    if int(policy['label_grace_days']) < 0:
        raise SlowMovingQualityPolicyError('Label grace days cannot be negative.')
    if int(policy['critical_future_quantity']) != 0 or int(policy['high_risk_future_quantity_max']) < 1:
        raise SlowMovingQualityPolicyError('Future-demand outcome boundaries are invalid.')
    confidence = dict(policy['confidence'])
    if confidence.get('method') != 'wilson_one_sided' or float(confidence.get('z_score', 0)) <= 0:
        raise SlowMovingQualityPolicyError('Quality policy must use a positive one-sided Wilson interval.')
    for section in ('pilot', 'notification', 'rollback', 'diagnostics'):
        if not isinstance(policy[section], dict):
            raise SlowMovingQualityPolicyError(f'Quality policy section {section} must be an object.')
    _require_at_least(policy['pilot'], PILOT_MINIMUMS, 'pilot')
    _require_at_least(policy['notification'], NOTIFICATION_MINIMUMS, 'notification')

    notification = policy['notification']
    try:
        maximum_opened_alert_rate = float(notification['maximum_opened_alert_rate'])
    except (KeyError, TypeError, ValueError) as exc:
        raise SlowMovingQualityPolicyError(
            'Quality policy notification.maximum_opened_alert_rate must be numeric.'
        ) from exc
    if not 0 <= maximum_opened_alert_rate <= 0.15:
        raise SlowMovingQualityPolicyError(
            'Notification alert rate must be between 0 and 0.15.'
        )

    rollback = policy['rollback']
    try:
        consecutive_breaches = int(rollback['consecutive_breaches'])
        minimum_opened_alerts = int(rollback['minimum_opened_alerts_per_cohort'])
        rollback_precision = float(rollback['minimum_high_risk_precision'])
        rollback_wilson = float(rollback['minimum_high_risk_precision_wilson_lower'])
        maximum_revision_rate = float(rollback['maximum_label_revision_rate'])
    except (KeyError, TypeError, ValueError) as exc:
        raise SlowMovingQualityPolicyError('Rollback policy thresholds are invalid.') from exc
    if consecutive_breaches != 2:
        raise SlowMovingQualityPolicyError('Rollback must trigger after exactly two consecutive cohorts.')
    if minimum_opened_alerts <= 0:
        raise SlowMovingQualityPolicyError('Rollback cohort alert volume must be positive.')
    if rollback_precision < NOTIFICATION_MINIMUMS['minimum_high_risk_precision']:
        raise SlowMovingQualityPolicyError('Rollback precision cannot be weaker than notification precision.')
    if rollback_wilson < NOTIFICATION_MINIMUMS['minimum_high_risk_precision_wilson_lower']:
        raise SlowMovingQualityPolicyError('Rollback Wilson bound cannot be weaker than notification Wilson bound.')
    if not 0 <= maximum_revision_rate <= 1:
        raise SlowMovingQualityPolicyError('Rollback label revision rate must be between 0 and 1.')
    try:
        minimum_slice_size = int(policy['diagnostics']['minimum_slice_size'])
    except (KeyError, TypeError, ValueError) as exc:
        raise SlowMovingQualityPolicyError(
            'Quality policy diagnostics.minimum_slice_size must be an integer.'
        ) from exc
    if minimum_slice_size < 30:
        raise SlowMovingQualityPolicyError(
            'Diagnostic slice size cannot be below 30 outcomes.'
        )
    return policy, hashlib.sha256(raw).hexdigest()
