"""Regression tests for frozen slow-moving policy replay."""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from supplyforge.services.slow_moving_policy_backtest import SlowMovingPolicyReplayService


class SlowMovingPolicyReplayTests(SimpleTestCase):
    def _cohort(self, *, cutoff, score, opened, outcome):
        return SimpleNamespace(
            id=f'cohort-{cutoff.date().isoformat()}',
            decision_cutoff=cutoff,
            canonical_sku='SKU-REPLAY',
            source_assessment_key=f'row-{cutoff.date().isoformat()}',
            rule_snapshot_json={'priority_score': score},
            segment_json={'category': 'General', 'channel': 'CSV', 'warehouse': 'MAIN'},
            predicted_risk_class='HIGH_RISK',
            opened_alert=opened,
            future_net_fulfilled_units_30=Decimal(str(outcome)),
            future_net_fulfilled_units_60=Decimal(str(outcome)),
            future_net_fulfilled_units_90=Decimal(str(outcome)),
        )

    def test_replay_uses_only_cutoff_scores_and_two_run_confirmation(self):
        cutoff = timezone.make_aware(datetime(2026, 1, 1))
        cohorts = [
            self._cohort(cutoff=cutoff, score=70, opened=False, outcome=0),
            self._cohort(cutoff=cutoff + timedelta(days=7), score=70, opened=True, outcome=0),
        ]
        quality_policy = {
            'confidence': {'z_score': 1.645},
            'high_risk_future_quantity_max': 5,
            'diagnostics': {'minimum_slice_size': 30},
        }
        result = SlowMovingPolicyReplayService.replay(
            cohorts=cohorts,
            candidate_policy={
                'version': 'candidate-v1',
                'risk_boundaries': {'medium_at_or_above': 40, 'high_at_or_above': 65, 'critical_at_or_above': 85},
                'consecutive_runs_to_open': 2,
            },
            quality_policy=quality_policy,
        )

        candidate = result['candidate']['primary_60_days']
        self.assertEqual(candidate['opened_high_risk_alert_count'], 1)
        self.assertEqual(candidate['high_risk_precision'], 1.0)
        self.assertEqual(result['replay_scope']['cohorts_evaluated'], 2)
