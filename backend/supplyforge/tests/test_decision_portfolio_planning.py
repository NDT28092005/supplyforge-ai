from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from supplyforge.models import ActionPlanRecord, DecisionRecord, SlowMovingAssessmentRun, User, Workspace
from supplyforge.services.decision_portfolio_service import DecisionPortfolioService


class DecisionPortfolioPlanningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='portfolio@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(name='Portfolio', slug='portfolio', owner=self.user)
        self.run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace, source_type='CSV', source_key='CSV',
            analysis_as_of=timezone.now(), source_scope={'warehouse_code': 'MAIN'},
            source_scope_fingerprint='scope', source_snapshot_fingerprint='snapshot',
            policy_version='test', policy_checksum='test', status='COMPLETED',
            is_current=True, completed_at=timezone.now(),
        )

    def _decision(self, decision_id, sku, *, action='DISCOUNT', exposure=1_000, urgency='HIGH', run=None):
        return DecisionRecord.objects.create(
            decision_id=decision_id, workspace_id=self.workspace.id, sku=sku,
            assessment_run=run or self.run, status='RECOMMENDED', action_type=action,
            urgency=urgency, priority_tier='P1', capital_exposure=exposure,
            risk_score=0.5,
            decision_evidence_snapshot={
                'state': 'READY', 'source_scope': {'warehouse_code': 'MAIN', 'channel': 'WEB'},
            },
        )

    def test_capacity_selection_is_deterministic_and_audited(self):
        self._decision('DEC-HIGH', 'SKU-HIGH', exposure=20_000)
        self._decision('DEC-LOW', 'SKU-LOW', exposure=10_000)

        result = DecisionPortfolioService.build(
            workspace_id=self.workspace.id,
            config={'capacity': {'max_actions': 1}, 'window_days': 7},
        )

        self.assertEqual([row['decision_id'] for row in result['sections']['selected']], ['DEC-HIGH'])
        self.assertEqual(result['sections']['deferred'][0]['queue_state'], 'DEFERRED_CAPACITY')
        self.assertEqual(result['summary']['candidates'], 2)
        self.assertTrue(result['policy_checksum'])
        self.assertEqual(result['constraints']['capacity']['team_capacity'], 1)

    def test_campaign_budget_does_not_assume_cost_or_budget(self):
        self._decision('DEC-PROMO-A', 'SKU-A', action='PROMOTION', exposure=20_000)
        self._decision('DEC-PROMO-B', 'SKU-B', action='PROMOTION', exposure=10_000)

        result = DecisionPortfolioService.build(
            workspace_id=self.workspace.id,
            config={
                'capacity': {'max_actions': 2},
                'campaign_budget': {'amount': 100, 'currency': 'VND'},
                'campaign_costs': {'DEC-PROMO-A': 70, 'DEC-PROMO-B': 50},
            },
        )

        self.assertEqual([row['decision_id'] for row in result['sections']['selected']], ['DEC-PROMO-A'])
        self.assertEqual(result['sections']['deferred'][0]['decision_id'], 'DEC-PROMO-B')
        self.assertEqual(result['sections']['deferred'][0]['queue_state'], 'DEFERRED_BUDGET')

        without_budget = DecisionPortfolioService.build(
            workspace_id=self.workspace.id,
            config={'capacity': {'max_actions': 2}, 'campaign_costs': {'DEC-PROMO-A': 70, 'DEC-PROMO-B': 50}},
        )
        self.assertEqual(without_budget['summary']['review_or_data_needed'], 2)
        self.assertTrue(all(row['queue_state'] == 'DATA_NEEDED' for row in without_budget['sections']['review_or_data_needed']))

    def test_stale_decisions_are_excluded_and_active_conflict_is_blocked(self):
        stale_run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace, source_type='CSV', source_key='CSV-OLD',
            analysis_as_of=timezone.now() - timedelta(days=1), source_scope={},
            source_scope_fingerprint='old-scope', source_snapshot_fingerprint='old-snapshot',
            policy_version='test', policy_checksum='test', status='COMPLETED',
            is_current=False, completed_at=timezone.now() - timedelta(days=1),
        )
        self._decision('DEC-STALE', 'SKU-STALE', run=stale_run)
        self._decision('DEC-CONFLICT', 'SKU-CONFLICT')
        today = timezone.localdate()
        ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, campaign_name='Existing', sku='SKU-CONFLICT',
            strategy='DISCOUNT', owner='Owner', start_date=today, due_date=today + timedelta(days=3),
            status='CONFIRMED', action_parameters={'execution_scope': {'warehouse_code': 'MAIN', 'channel': 'WEB'}},
        )

        result = DecisionPortfolioService.build(
            workspace_id=self.workspace.id, config={'capacity': {'max_actions': 2}},
        )

        self.assertNotIn('DEC-STALE', result['input_decision_ids'])
        self.assertEqual(result['sections']['blocked'][0]['decision_id'], 'DEC-CONFLICT')
        self.assertEqual(result['sections']['blocked'][0]['queue_state'], 'BLOCKED_CONFLICT')
