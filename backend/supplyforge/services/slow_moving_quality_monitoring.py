"""Outcome-based quality gates for merchant slow-moving alerts."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from typing import Any

from supplyforge.models import (
    SlowMovingAlertFeedback,
    SlowMovingAssessmentRun,
    SlowMovingOutcomeCohort,
)
from supplyforge.services.slow_moving_quality_policy import load_slow_moving_quality_policy


HIGH_RISK_CLASSES = {'CRITICAL', 'HIGH_RISK'}
ADVERSE_FEEDBACK_REASONS = {
    SlowMovingAlertFeedback.REASON_DATA_INCORRECT,
    SlowMovingAlertFeedback.REASON_NOT_RELEVANT,
}
ACCURACY_METRIC_KEYS = {
    'high_risk_precision',
    'high_risk_precision_wilson_lower',
    'high_risk_recall',
    'critical_precision',
    'critical_precision_wilson_lower',
    'capital_weighted_high_risk_precision',
}


class SlowMovingQualityMonitoringService:
    """Report policy gates from mature, immutable outcome cohorts only."""

    @staticmethod
    def _check(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
        return {'name': name, 'passed': bool(passed), 'expected': expected, 'actual': actual}

    @staticmethod
    def _scope_fingerprint(scope: dict[str, Any], source_type: str) -> str:
        """Rebuild the source-specific stable scope digest without live facts."""
        excluded = {'source_range_end'}
        if source_type == SlowMovingAssessmentRun.SOURCE_CSV:
            excluded.update({'dataset_version_id', 'dataset_checksum'})
        stable_scope = {key: value for key, value in scope.items() if key not in excluded}
        raw = json.dumps(stable_scope, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _scope_date(scope: dict[str, Any], field: str) -> date | None:
        value = scope.get(field)
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    @classmethod
    def _run_lineage_failures(cls, run: SlowMovingAssessmentRun) -> list[str]:
        """Validate the immutable source declaration before trusting cohorts.

        This deliberately reads only the frozen run metadata.  A current
        connection or active CSV import can change after a cohort is created,
        so it is not valid evidence for a historical decision.
        """
        scope = run.source_scope if isinstance(run.source_scope, dict) else {}
        failures: list[str] = []
        prefix = f'RUN:{run.id}:'
        if not scope:
            return [f'{prefix}SOURCE_SCOPE_MISSING']
        if str(scope.get('source_type') or '').upper() != run.source_type:
            failures.append(f'{prefix}SOURCE_TYPE_MISMATCH')
        if str(scope.get('workspace_id') or '') != str(run.workspace_id):
            failures.append(f'{prefix}WORKSPACE_SCOPE_MISMATCH')
        if not run.source_scope_fingerprint:
            failures.append(f'{prefix}SOURCE_SCOPE_FINGERPRINT_MISSING')
        elif cls._scope_fingerprint(scope, run.source_type) != run.source_scope_fingerprint:
            failures.append(f'{prefix}SOURCE_SCOPE_FINGERPRINT_MISMATCH')

        start = cls._scope_date(scope, 'source_range_start')
        end = cls._scope_date(scope, 'source_range_end')
        if start is None or end is None:
            failures.append(f'{prefix}SOURCE_RANGE_MISSING')
        else:
            if end != run.analysis_as_of.date():
                failures.append(f'{prefix}SOURCE_RANGE_END_MISMATCH')
            if end < start or (end - start).days + 1 < 45:
                failures.append(f'{prefix}SOURCE_COVERAGE_BELOW_45_DAYS')

        if run.source_type == SlowMovingAssessmentRun.SOURCE_CSV:
            if scope.get('scope_schema_version') != 'slow-moving-source-scope-v2':
                failures.append(f'{prefix}CSV_SCOPE_SCHEMA_INVALID')
            if run.source_key != 'CSV':
                failures.append(f'{prefix}CSV_SOURCE_KEY_INVALID')
            if not run.dataset_version_id or str(scope.get('dataset_version_id') or '') != str(run.dataset_version_id):
                failures.append(f'{prefix}CSV_DATASET_VERSION_MISMATCH')
            if not isinstance(scope.get('order_platforms'), list) or not scope['order_platforms']:
                failures.append(f'{prefix}CSV_CHANNEL_SCOPE_MISSING')
            if not scope.get('warehouse_scope'):
                failures.append(f'{prefix}CSV_WAREHOUSE_SCOPE_MISSING')
            if scope.get('return_handling') != 'NET_SALES_MINUS_RETURN_EVENTS':
                failures.append(f'{prefix}CSV_RETURN_HANDLING_INVALID')
        elif run.source_type == SlowMovingAssessmentRun.SOURCE_ODOO:
            if scope.get('scope_schema_version') != 'slow-moving-odoo-source-scope-v1':
                failures.append(f'{prefix}ODOO_SCOPE_SCHEMA_INVALID')
            if not run.integration_connection_id:
                failures.append(f'{prefix}ODOO_CONNECTION_MISSING')
            elif str(scope.get('integration_connection_id') or '') != str(run.integration_connection_id):
                failures.append(f'{prefix}ODOO_CONNECTION_SCOPE_MISMATCH')
            if run.integration_connection_id and run.source_key != f'ODOO:{run.integration_connection_id}':
                failures.append(f'{prefix}ODOO_SOURCE_KEY_INVALID')
            warehouse_ids = scope.get('warehouse_ids')
            if not isinstance(warehouse_ids, list) or not [value for value in warehouse_ids if str(value)]:
                failures.append(f'{prefix}ODOO_WAREHOUSE_SCOPE_MISSING')
            if scope.get('sales_metric_warehouse_id') != '':
                failures.append(f'{prefix}ODOO_SALES_CHANNEL_SCOPE_INVALID')
            if scope.get('return_handling') != 'NET_SALES_MINUS_RETURNS':
                failures.append(f'{prefix}ODOO_RETURN_HANDLING_INVALID')
            if not run.source_snapshot_fingerprint:
                failures.append(f'{prefix}ODOO_SNAPSHOT_FINGERPRINT_MISSING')
        else:
            failures.append(f'{prefix}SOURCE_TYPE_UNSUPPORTED')
        return failures

    @classmethod
    def _lineage_failures(
        cls,
        current_run: SlowMovingAssessmentRun,
        cohorts: list[SlowMovingOutcomeCohort],
    ) -> list[str]:
        failures = cls._run_lineage_failures(current_run)
        validated_runs = {current_run.id}
        for cohort in cohorts:
            prefix = f'COHORT:{cohort.id}:'
            if cohort.workspace_id != current_run.workspace_id:
                failures.append(f'{prefix}WORKSPACE_MISMATCH')
            if cohort.source_type != current_run.source_type or cohort.source_key != current_run.source_key:
                failures.append(f'{prefix}SOURCE_MISMATCH')
            if cohort.policy_checksum != current_run.policy_checksum:
                failures.append(f'{prefix}POLICY_MISMATCH')
            if cohort.source_scope_fingerprint != current_run.source_scope_fingerprint:
                failures.append(f'{prefix}SOURCE_SCOPE_MISMATCH')
            scope = cohort.source_scope if isinstance(cohort.source_scope, dict) else {}
            if not scope or cls._scope_fingerprint(scope, cohort.source_type) != cohort.source_scope_fingerprint:
                failures.append(f'{prefix}SOURCE_SCOPE_FINGERPRINT_MISMATCH')
            if not cohort.opening_inventory_verified:
                failures.append(f'{prefix}OPENING_INVENTORY_UNVERIFIED')
            elif cohort.opening_stock_quantity is None or cohort.opening_stock_quantity <= 0:
                failures.append(f'{prefix}OPENING_STOCK_NOT_POSITIVE')
            assessment_run = cohort.assessment_run
            if not assessment_run:
                failures.append(f'{prefix}ASSESSMENT_RUN_MISSING')
            else:
                if assessment_run.id not in validated_runs:
                    failures.extend(cls._run_lineage_failures(assessment_run))
                    validated_runs.add(assessment_run.id)
                if (
                    assessment_run.workspace_id != cohort.workspace_id
                    or assessment_run.source_key != cohort.source_key
                    or assessment_run.source_type != cohort.source_type
                ):
                    failures.append(f'{prefix}ASSESSMENT_RUN_SOURCE_MISMATCH')
        # A repeated error must not make the response arbitrarily large on a
        # high-volume tenant, while still retaining deterministic diagnostics.
        return sorted(set(failures))[:100]

    @classmethod
    def _withheld_metrics(cls, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            **metrics,
            **{key: None for key in ACCURACY_METRIC_KEYS},
            'accuracy_visibility': 'WITHHELD_INSUFFICIENT_EVIDENCE',
        }

    @classmethod
    def _withheld_cohorts(cls, cohorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**cohort, **{key: None for key in ACCURACY_METRIC_KEYS}}
            for cohort in cohorts
        ]

    @staticmethod
    def _notification_payload(
        *, state: str, notification_gates: list[dict[str, Any]], lineage_failures: list[str],
        repeated_quality_breach: bool, revision_breach: bool,
    ) -> dict[str, Any]:
        enabled = state == 'NOTIFICATION_ELIGIBLE'
        reasons: list[str] = []
        if lineage_failures:
            reasons.append('LINEAGE_INTEGRITY_FAILURE')
        if repeated_quality_breach:
            reasons.append('TWO_CONSECUTIVE_COHORT_QUALITY_BREACHES')
        if revision_breach:
            reasons.append('OUTCOME_LABEL_REVISION_RATE_EXCEEDED')
        if state == 'INSUFFICIENT_EVIDENCE':
            reasons.append('INSUFFICIENT_MATURE_EVIDENCE')
        if state == 'QUEUE_ONLY':
            reasons.extend(gate['name'] for gate in notification_gates if not gate['passed'])
        return {
            'proactive_notifications_enabled': enabled,
            'delivery_mode': 'PROACTIVE' if enabled else 'QUEUE_ONLY',
            'disabled_reasons': reasons,
        }

    @staticmethod
    def wilson_lower(successes: int, total: int, z_score: float) -> float | None:
        if total <= 0:
            return None
        proportion = successes / total
        denominator = 1 + z_score ** 2 / total
        centre = proportion + z_score ** 2 / (2 * total)
        margin = z_score * math.sqrt(
            (proportion * (1 - proportion) + z_score ** 2 / (4 * total)) / total
        )
        return max(0.0, (centre - margin) / denominator)

    @classmethod
    def _metrics(cls, cohorts: list[SlowMovingOutcomeCohort], policy: dict[str, Any]) -> dict[str, Any]:
        high_max = float(policy['high_risk_future_quantity_max'])
        z_score = float(policy['confidence']['z_score'])
        opened = [cohort for cohort in cohorts if cohort.opened_alert]
        opened_high = [cohort for cohort in opened if cohort.predicted_risk_class in HIGH_RISK_CLASSES]
        opened_critical = [cohort for cohort in opened if cohort.predicted_risk_class == 'CRITICAL']
        actual_high = [
            cohort for cohort in cohorts
            if float(cohort.future_net_fulfilled_units_60) <= high_max
        ]
        true_high = [
            cohort for cohort in opened_high
            if float(cohort.future_net_fulfilled_units_60) <= high_max
        ]
        true_critical = [
            cohort for cohort in opened_critical
            if float(cohort.future_net_fulfilled_units_60) == 0
        ]
        capital_covered = [
            cohort for cohort in cohorts
            if cohort.opening_capital_exposure is not None
        ]
        opened_high_capital = [
            cohort for cohort in opened_high
            if cohort.opening_capital_exposure is not None
        ]
        true_high_capital = [
            cohort for cohort in opened_high_capital
            if float(cohort.future_net_fulfilled_units_60) <= high_max
        ]
        opened_high_risk_capital = sum(
            float(cohort.opening_capital_exposure) for cohort in opened_high_capital
        )
        true_positive_high_risk_capital = sum(
            float(cohort.opening_capital_exposure) for cohort in true_high_capital
        )
        return {
            'matured_eligible_skus': len(cohorts),
            'opened_alert_count': len(opened),
            'opened_high_risk_alert_count': len(opened_high),
            'opened_critical_alert_count': len(opened_critical),
            'actual_high_risk_count': len(actual_high),
            'high_risk_true_positive_count': len(true_high),
            'critical_true_positive_count': len(true_critical),
            'high_risk_precision': len(true_high) / len(opened_high) if opened_high else None,
            'high_risk_precision_wilson_lower': cls.wilson_lower(len(true_high), len(opened_high), z_score),
            'high_risk_recall': len(true_high) / len(actual_high) if actual_high else None,
            'critical_precision': len(true_critical) / len(opened_critical) if opened_critical else None,
            'critical_precision_wilson_lower': cls.wilson_lower(
                len(true_critical), len(opened_critical), z_score,
            ),
            'opened_alert_rate': len(opened_high) / len(cohorts) if cohorts else None,
            'opening_capital_coverage': len(capital_covered) / len(cohorts) if cohorts else None,
            'opened_high_risk_capital': opened_high_risk_capital,
            'true_positive_high_risk_capital': true_positive_high_risk_capital,
            'capital_weighted_high_risk_precision': (
                true_positive_high_risk_capital / opened_high_risk_capital
                if opened_high_risk_capital > 0 else None
            ),
            'label_revision_count': sum(cohort.label_revision > 0 for cohort in cohorts),
            'label_revision_rate': (
                sum(cohort.label_revision > 0 for cohort in cohorts) / len(cohorts)
                if cohorts else None
            ),
        }

    @staticmethod
    def _distinct_decision_cohorts(cohorts: list[SlowMovingOutcomeCohort]) -> int:
        return len({cohort.decision_cutoff.date() for cohort in cohorts})

    @classmethod
    def _cohort_reports(cls, cohorts: list[SlowMovingOutcomeCohort], policy: dict[str, Any]) -> list[dict[str, Any]]:
        grouped: dict[str, list[SlowMovingOutcomeCohort]] = defaultdict(list)
        for cohort in cohorts:
            grouped[cohort.decision_cutoff.date().isoformat()].append(cohort)
        result = []
        for cutoff, rows in sorted(grouped.items()):
            result.append({'decision_cutoff_date': cutoff, **cls._metrics(rows, policy)})
        return result

    @classmethod
    def report(cls, *, workspace_id: int, source_key: str = 'CSV') -> dict[str, Any]:
        source_key = str(source_key or 'CSV')
        if source_key.upper() == SlowMovingAssessmentRun.SOURCE_CSV:
            source_key = SlowMovingAssessmentRun.SOURCE_CSV
        elif source_key.upper().startswith('ODOO:'):
            # Integration UUIDs are stored in their canonical lower-case
            # representation; upper-casing a whole source key breaks Odoo
            # quality lookups while CSV legitimately remains case-insensitive.
            source_key = f"ODOO:{source_key.split(':', 1)[1].lower()}"
        policy, quality_policy_checksum = load_slow_moving_quality_policy()
        current_run = (
            SlowMovingAssessmentRun.objects.filter(
                workspace_id=workspace_id,
                source_key=source_key,
                status=SlowMovingAssessmentRun.STATUS_COMPLETED,
                is_current=True,
            )
            .order_by('-completed_at')
            .first()
        )
        if not current_run:
            return {
                'state': 'INSUFFICIENT_EVIDENCE',
                'reason': 'NO_CURRENT_OPERATIONAL_RUN',
                'workspace_id': workspace_id,
                'source_key': source_key,
                'quality_policy_checksum': quality_policy_checksum,
                'gates': [],
                'metrics': {},
                'cohorts': [],
                'lineage_failures': [],
                'notification': {
                    'proactive_notifications_enabled': False,
                    'delivery_mode': 'QUEUE_ONLY',
                    'disabled_reasons': ['NO_CURRENT_OPERATIONAL_RUN'],
                },
            }

        all_scope_cohorts = SlowMovingOutcomeCohort.objects.filter(
            workspace_id=workspace_id,
            source_key=source_key,
            policy_checksum=current_run.policy_checksum,
            source_scope_fingerprint=current_run.source_scope_fingerprint,
        )
        mature = list(
            all_scope_cohorts.filter(
                status=SlowMovingOutcomeCohort.STATUS_MATURED,
                future_net_fulfilled_units_60__isnull=False,
            ).select_related('assessment_run').order_by('decision_cutoff', 'canonical_sku')
        )
        lineage_failures = cls._lineage_failures(current_run, mature)
        metrics = cls._metrics(mature, policy)
        cohort_reports = cls._cohort_reports(mature, policy)
        pending_count = all_scope_cohorts.filter(
            status=SlowMovingOutcomeCohort.STATUS_PENDING,
        ).count()
        blocked_count = all_scope_cohorts.filter(
            status=SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED,
        ).count()
        confounded_count = all_scope_cohorts.filter(
            status=SlowMovingOutcomeCohort.STATUS_CONFOUNDED,
        ).count()
        total_considered = int((current_run.summary or {}).get('total_skus_considered') or 0)
        eligible_now = int((current_run.summary or {}).get('eligible_skus') or 0)
        data_coverage = eligible_now / total_considered if total_considered else None
        feedback = SlowMovingAlertFeedback.objects.filter(
            workspace_id=workspace_id,
            alert_state__source_key=source_key,
        )
        feedback_count = feedback.count()
        adverse_feedback_count = feedback.filter(reason__in=ADVERSE_FEEDBACK_REASONS).count()
        adverse_feedback_rate = adverse_feedback_count / feedback_count if feedback_count else None

        pilot = policy['pilot']
        notification = policy['notification']
        rollback = policy['rollback']
        distinct_cohorts = cls._distinct_decision_cohorts(mature)
        gates = [
            cls._check(
                'pilot_matured_eligible_skus',
                metrics['matured_eligible_skus'] >= int(pilot['minimum_matured_eligible_skus']),
                pilot['minimum_matured_eligible_skus'], metrics['matured_eligible_skus'],
            ),
            cls._check(
                'pilot_opened_high_risk_alerts',
                metrics['opened_high_risk_alert_count'] >= int(pilot['minimum_matured_opened_high_risk_alerts']),
                pilot['minimum_matured_opened_high_risk_alerts'], metrics['opened_high_risk_alert_count'],
            ),
            cls._check(
                'pilot_decision_cohorts',
                distinct_cohorts >= int(pilot['minimum_distinct_decision_cohorts']),
                pilot['minimum_distinct_decision_cohorts'], distinct_cohorts,
            ),
        ]
        pilot_ready = all(gate['passed'] for gate in gates)
        notification_gates = [
            cls._check('notification_matured_eligible_skus', metrics['matured_eligible_skus'] >= int(notification['minimum_matured_eligible_skus']), notification['minimum_matured_eligible_skus'], metrics['matured_eligible_skus']),
            cls._check('notification_opened_high_risk_alerts', metrics['opened_high_risk_alert_count'] >= int(notification['minimum_matured_opened_high_risk_alerts']), notification['minimum_matured_opened_high_risk_alerts'], metrics['opened_high_risk_alert_count']),
            cls._check('notification_opened_critical_alerts', metrics['opened_critical_alert_count'] >= int(notification['minimum_matured_opened_critical_alerts']), notification['minimum_matured_opened_critical_alerts'], metrics['opened_critical_alert_count']),
            cls._check('notification_decision_cohorts', distinct_cohorts >= int(notification['minimum_distinct_decision_cohorts']), notification['minimum_distinct_decision_cohorts'], distinct_cohorts),
            cls._check('eligible_data_coverage', data_coverage is not None and data_coverage >= float(notification['minimum_eligible_data_coverage']), notification['minimum_eligible_data_coverage'], data_coverage),
            cls._check('high_risk_precision', metrics['high_risk_precision'] is not None and metrics['high_risk_precision'] >= float(notification['minimum_high_risk_precision']), notification['minimum_high_risk_precision'], metrics['high_risk_precision']),
            cls._check('high_risk_precision_wilson_lower', metrics['high_risk_precision_wilson_lower'] is not None and metrics['high_risk_precision_wilson_lower'] >= float(notification['minimum_high_risk_precision_wilson_lower']), notification['minimum_high_risk_precision_wilson_lower'], metrics['high_risk_precision_wilson_lower']),
            cls._check('high_risk_recall', metrics['high_risk_recall'] is not None and metrics['high_risk_recall'] >= float(notification['minimum_high_risk_recall']), notification['minimum_high_risk_recall'], metrics['high_risk_recall']),
            cls._check('critical_precision', metrics['critical_precision'] is not None and metrics['critical_precision'] >= float(notification['minimum_critical_precision']), notification['minimum_critical_precision'], metrics['critical_precision']),
            cls._check('critical_precision_wilson_lower', metrics['critical_precision_wilson_lower'] is not None and metrics['critical_precision_wilson_lower'] >= float(notification['minimum_critical_precision_wilson_lower']), notification['minimum_critical_precision_wilson_lower'], metrics['critical_precision_wilson_lower']),
            cls._check('opened_alert_rate', metrics['opened_alert_rate'] is not None and metrics['opened_alert_rate'] <= float(notification['maximum_opened_alert_rate']), notification['maximum_opened_alert_rate'], metrics['opened_alert_rate']),
            cls._check('adverse_feedback_rate', feedback_count < int(notification['minimum_feedback_records']) or (adverse_feedback_rate is not None and adverse_feedback_rate < float(notification['maximum_adverse_feedback_rate'])), notification['maximum_adverse_feedback_rate'], adverse_feedback_rate),
        ]

        # Do not skip a low-volume cohort when determining consecutiveness.
        # It interrupts the breach sequence because its quality result is not
        # statistically comparable to either neighbour.
        recent = cohort_reports[-int(rollback['consecutive_breaches']):]
        repeated_quality_breach = (
            len(recent) == int(rollback['consecutive_breaches'])
            and all(
                row['opened_high_risk_alert_count'] >= int(
                    rollback['minimum_opened_alerts_per_cohort']
                )
                and
                row['high_risk_precision'] is not None
                and row['high_risk_precision_wilson_lower'] is not None
                and (
                    row['high_risk_precision'] < float(rollback['minimum_high_risk_precision'])
                    or row['high_risk_precision_wilson_lower'] < float(
                        rollback['minimum_high_risk_precision_wilson_lower']
                    )
                )
                for row in recent
            )
        )
        revision_breach = (
            metrics['label_revision_rate'] is not None
            and metrics['label_revision_rate'] > float(rollback['maximum_label_revision_rate'])
        )
        rollback_required = bool(lineage_failures) or repeated_quality_breach or revision_breach
        if rollback_required:
            state = 'ROLLBACK_REQUIRED'
        elif not pilot_ready:
            state = 'INSUFFICIENT_EVIDENCE'
        elif all(gate['passed'] for gate in notification_gates):
            state = 'NOTIFICATION_ELIGIBLE'
        else:
            state = 'QUEUE_ONLY'
        accuracy_is_publishable = pilot_ready and not lineage_failures
        public_metrics = metrics if accuracy_is_publishable else cls._withheld_metrics(metrics)
        public_cohorts = cohort_reports if accuracy_is_publishable else cls._withheld_cohorts(cohort_reports)
        public_gates = gates + notification_gates
        if not accuracy_is_publishable:
            public_gates = [
                {
                    **gate,
                    'actual': None if gate['name'] in {
                        'high_risk_precision', 'high_risk_precision_wilson_lower',
                        'high_risk_recall', 'critical_precision',
                        'critical_precision_wilson_lower',
                    } else gate['actual'],
                }
                for gate in public_gates
            ]
        notification_payload = cls._notification_payload(
            state=state,
            notification_gates=notification_gates,
            lineage_failures=lineage_failures,
            repeated_quality_breach=repeated_quality_breach,
            revision_breach=revision_breach,
        )
        try:
            from supplyforge.services.slow_moving_candidate_shadow import SlowMovingCandidateShadowService

            model_diagnostics = SlowMovingCandidateShadowService.diagnostic_report(
                workspace_id=workspace_id, source_key=source_key,
                source_scope_fingerprint=current_run.source_scope_fingerprint,
                policy_checksum=current_run.policy_checksum,
            )
        except Exception:
            # Diagnostic inference must never prevent the deterministic rule
            # quality report or notification fail-closed gate from loading.
            model_diagnostics = {'state': 'DIAGNOSTIC_UNAVAILABLE'}
        return {
            'state': state,
            'workspace_id': workspace_id,
            'source_key': source_key,
            'source_run_id': str(current_run.id),
            'analysis_as_of': current_run.analysis_as_of.isoformat(),
            'score_policy_checksum': current_run.policy_checksum,
            'quality_policy_checksum': quality_policy_checksum,
            'source_scope_fingerprint': current_run.source_scope_fingerprint,
            'scope': 'Mature 60-day future net fulfilled demand only. Capital weighting uses opening exposure and does not prove capital remained trapped or that an action caused an outcome.',
            'metrics': {
                **public_metrics,
                'distinct_decision_cohorts': distinct_cohorts,
                'eligible_data_coverage': data_coverage,
                'feedback_count': feedback_count,
                'adverse_feedback_count': adverse_feedback_count,
                'adverse_feedback_rate': adverse_feedback_rate,
                'pending_outcome_count': pending_count,
                'blocked_outcome_count': blocked_count,
                'confounded_outcome_count': confounded_count,
            },
            'gates': public_gates,
            'rollback': {
                'required': rollback_required,
                'lineage_failure': bool(lineage_failures),
                'repeated_quality_breach': repeated_quality_breach,
                'label_revision_breach': revision_breach,
            },
            'lineage_failures': lineage_failures,
            'notification': notification_payload,
            'cohorts': public_cohorts,
            'model_diagnostics': model_diagnostics,
        }

    @classmethod
    def can_send_proactive_notification(cls, *, workspace_id: int, source_key: str = 'CSV') -> bool:
        """Single fail-closed guard for every future notification delivery path."""
        report = cls.report(workspace_id=workspace_id, source_key=source_key)
        return bool((report.get('notification') or {}).get('proactive_notifications_enabled'))
