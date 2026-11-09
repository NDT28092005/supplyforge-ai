"""Governed temporal-candidate diagnostics for slow-moving rule cohorts.

This adapter never changes an alert's class, priority, lifecycle, action, or
notification eligibility.  It only stores a calibrated SHADOW/CANARY
prediction beside the same frozen rule cohort for time-aware evaluation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from supplyforge.models import SlowMovingAssessmentRun, SlowMovingOutcomeCohort
from supplyforge.services.slow_moving_quality_policy import load_slow_moving_quality_policy
from supplyforge.services.temporal_candidate_model import (
    TemporalCandidateModelService,
    TemporalCandidateUnavailable,
)
from supplyforge.services.temporal_feature_service import CONTRACT_PATH


HIGH_RISK_CLASSES = {'CRITICAL', 'HIGH_RISK'}
class SlowMovingCandidateShadowService:
    """Run governed temporal inference only as immutable shadow evidence."""

    DIAGNOSTIC_STATUS_RECORDED = 'RECORDED'
    MINIMUM_SLICE_SIZE = 30

    @staticmethod
    def _feature_contract() -> dict[str, Any]:
        return json.loads(CONTRACT_PATH.read_text(encoding='utf-8'))

    @classmethod
    def _scope_failure(cls, run: SlowMovingAssessmentRun) -> str | None:
        scope = run.source_scope if isinstance(run.source_scope, dict) else {}
        contract_policy = cls._feature_contract().get('source_policy') or {}
        if run.source_type != SlowMovingAssessmentRun.SOURCE_CSV:
            return 'SOURCE_TYPE_NOT_SUPPORTED_FOR_TEMPORAL_SHADOW'
        if scope.get('scope_schema_version') != 'slow-moving-source-scope-v2':
            return 'SOURCE_SCOPE_SCHEMA_MISMATCH'
        if scope.get('return_handling') != contract_policy.get('return_handling'):
            return 'RETURN_HANDLING_FEATURE_CONTRACT_MISMATCH'
        if scope.get('order_platforms') != ['sales_import']:
            return 'CHANNEL_SCOPE_FEATURE_CONTRACT_MISMATCH'
        if scope.get('warehouse_scope') != 'ALL_VERIFIED_WAREHOUSES':
            return 'WAREHOUSE_SCOPE_FEATURE_CONTRACT_MISMATCH'
        return None

    @staticmethod
    def _feature_checksum(values: dict[str, Any]) -> str:
        raw = json.dumps(values, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def capture_run(cls, run_id: str, *, batch_size: int = 250) -> dict[str, Any]:
        """Capture calibrated diagnostics in batches without changing rule output."""
        run = SlowMovingAssessmentRun.objects.select_related('workspace').get(id=run_id)
        scope_failure = cls._scope_failure(run)
        if scope_failure:
            return {'status': 'SKIPPED', 'reason': scope_failure, 'recorded': 0, 'failed': 0}
        candidate = TemporalCandidateModelService()
        status = candidate.status()
        if not status.available:
            return {'status': 'SKIPPED', 'reason': status.code, 'detail': status.detail, 'recorded': 0, 'failed': 0}
        if status.serving_state not in {'SHADOW', 'CANARY'}:
            return {'status': 'SKIPPED', 'reason': 'CANDIDATE_NOT_IN_SHADOW_OR_CANARY', 'recorded': 0, 'failed': 0}
        if not status.calibrated:
            return {'status': 'SKIPPED', 'reason': 'CALIBRATOR_EVIDENCE_MISSING', 'recorded': 0, 'failed': 0}
        workspace = run.workspace
        if not workspace.owner_id:
            return {'status': 'SKIPPED', 'reason': 'WORKSPACE_OWNER_MISSING', 'recorded': 0, 'failed': 0}

        recorded = failed = skipped = 0
        cohorts = SlowMovingOutcomeCohort.objects.filter(
            assessment_run=run,
            source_type=SlowMovingAssessmentRun.SOURCE_CSV,
        ).order_by('created_at', 'id')
        for cohort in cohorts.iterator(chunk_size=batch_size):
            prior = cohort.model_diagnostic_json if isinstance(cohort.model_diagnostic_json, dict) else {}
            if (
                prior.get('status') == cls.DIAGNOSTIC_STATUS_RECORDED
                and prior.get('model_version') == status.model_version
            ):
                skipped += 1
                continue
            try:
                prediction = candidate.predict(
                    cohort.canonical_sku,
                    user_id=str(workspace.owner_id),
                    workspace_id=workspace.id,
                    as_of=run.analysis_as_of,
                )
                if prediction.get('serving_state') not in {'SHADOW', 'CANARY'}:
                    skipped += 1
                    continue
                values = dict(prediction.get('feature_values') or {})
                cohort.model_diagnostic_json = {
                    'status': cls.DIAGNOSTIC_STATUS_RECORDED,
                    'model_name': prediction.get('model_name'),
                    'model_version': prediction.get('model_version'),
                    'serving_state': prediction.get('serving_state'),
                    'feature_schema_version': prediction.get('feature_schema_version'),
                    'ground_truth_schema_version': prediction.get('ground_truth_schema_version'),
                    'ground_truth_status': prediction.get('ground_truth_status'),
                    'operating_mode': prediction.get('operating_mode'),
                    'predicted_risk_class': prediction.get('risk_class'),
                    # This value is stored only for mature diagnostic checks;
                    # merchant decision UI continues to show rule priority.
                    'calibrated_high_risk_probability': prediction.get('risk_probability'),
                    'raw_high_risk_probability': prediction.get('raw_high_risk_probability'),
                    'feature_values': values,
                    'feature_checksum': cls._feature_checksum(values),
                    'decision_cutoff': prediction.get('decision_cutoff'),
                }
                cohort.save(update_fields=['model_diagnostic_json', 'updated_at'])
                recorded += 1
            except (TemporalCandidateUnavailable, ValueError) as exc:
                # One SKU with incomplete features cannot make the rule run or
                # other independent shadow cohorts fail.
                failed += 1
            except Exception:
                failed += 1
        return {
            'status': 'COMPLETED', 'model_version': status.model_version,
            'recorded': recorded, 'failed': failed, 'skipped': skipped,
        }

    @staticmethod
    def _metric(rows: list[SlowMovingOutcomeCohort], policy: dict[str, Any]) -> dict[str, Any]:
        high_max = float(policy['high_risk_future_quantity_max'])
        actual = [float(row.future_net_fulfilled_units_60) <= high_max for row in rows]
        rule_predicted = [
            str((row.rule_snapshot_json or {}).get('risk_class') or row.predicted_risk_class) in HIGH_RISK_CLASSES
            for row in rows
        ]
        model_predicted = [
            str((row.model_diagnostic_json or {}).get('predicted_risk_class') or '') in HIGH_RISK_CLASSES
            for row in rows
        ]
        probabilities = [
            float((row.model_diagnostic_json or {}).get('calibrated_high_risk_probability'))
            for row in rows
        ]
        actual_count = sum(actual)

        def precision(predictions):
            positive = sum(predictions)
            return sum(a and p for a, p in zip(actual, predictions)) / positive if positive else None

        def recall(predictions):
            return sum(a and p for a, p in zip(actual, predictions)) / actual_count if actual_count else None

        brier = sum((probability - int(outcome)) ** 2 for probability, outcome in zip(probabilities, actual)) / len(rows)
        bins: dict[int, list[tuple[float, bool]]] = defaultdict(list)
        for probability, outcome in zip(probabilities, actual):
            bins[min(9, int(probability * 10))].append((probability, outcome))
        ece = sum(
            len(entries) / len(rows) * abs(
                sum(value for value, _ in entries) / len(entries)
                - sum(int(outcome) for _, outcome in entries) / len(entries)
            )
            for entries in bins.values()
        )
        return {
            'sample_size': len(rows),
            'actual_high_risk_count': actual_count,
            'rule_high_risk_precision': precision(rule_predicted),
            'rule_high_risk_recall': recall(rule_predicted),
            'candidate_high_risk_precision': precision(model_predicted),
            'candidate_high_risk_recall': recall(model_predicted),
            'candidate_brier': brier,
            'candidate_ece': ece,
        }

    @classmethod
    def diagnostic_report(
        cls, *, workspace_id: int, source_key: str,
        source_scope_fingerprint: str | None = None,
        policy_checksum: str | None = None,
        minimum_slice_size: int | None = None,
    ) -> dict[str, Any]:
        """Compare rules and candidate only on the same mature clean cohorts."""
        policy, _ = load_slow_moving_quality_policy()
        policy_minimum = int((policy.get('diagnostics') or {}).get(
            'minimum_slice_size', cls.MINIMUM_SLICE_SIZE,
        ))
        minimum = max(cls.MINIMUM_SLICE_SIZE, policy_minimum, int(minimum_slice_size or 0))
        cohorts = SlowMovingOutcomeCohort.objects.filter(
            workspace_id=workspace_id,
            source_key=source_key,
            status=SlowMovingOutcomeCohort.STATUS_MATURED,
            future_net_fulfilled_units_60__isnull=False,
        )
        if source_scope_fingerprint:
            cohorts = cohorts.filter(source_scope_fingerprint=source_scope_fingerprint)
        if policy_checksum:
            cohorts = cohorts.filter(policy_checksum=policy_checksum)
        rows = [
            cohort for cohort in cohorts.order_by('decision_cutoff', 'canonical_sku')
            if isinstance(cohort.model_diagnostic_json, dict)
            and cohort.model_diagnostic_json.get('status') == cls.DIAGNOSTIC_STATUS_RECORDED
            and cohort.model_diagnostic_json.get('serving_state') in {'SHADOW', 'CANARY'}
        ]
        if not rows:
            return {
                'state': 'NO_MATURE_SHADOW_EVIDENCE', 'minimum_slice_size': minimum,
                'overall': None, 'slices': [],
                'scope': 'Diagnostic only. Candidate output does not alter rule alerts, actions, or notifications.',
            }
        segments: dict[tuple[str, str], list[SlowMovingOutcomeCohort]] = defaultdict(list)
        for cohort in rows:
            snapshot = cohort.segment_json if isinstance(cohort.segment_json, dict) else {}
            for dimension in ('category', 'channel', 'warehouse'):
                segments[(dimension, str(snapshot.get(dimension) or 'UNSPECIFIED'))].append(cohort)
        slices = []
        for (dimension, value), segment_rows in sorted(segments.items()):
            slices.append({
                'dimension': dimension,
                'value': value,
                'sample_size': len(segment_rows),
                'publishable': len(segment_rows) >= minimum,
                'metrics': cls._metric(segment_rows, policy) if len(segment_rows) >= minimum else None,
            })
        return {
            'state': 'DIAGNOSTIC_ONLY',
            'minimum_slice_size': minimum,
            'overall': cls._metric(rows, policy),
            'slices': slices,
            'scope': 'Time-aware comparison on identical mature rule cohorts. No threshold tuning or merchant-facing probability.',
        }
