from django.test import TestCase
from django.utils import timezone

from supplyforge.models import ActionPlanRecord, DecisionRecord, SlowMovingAssessmentRun, User, Workspace
from supplyforge.services.decision_portfolio_service import DecisionPortfolioService
from supplyforge.services.weekly_action_planning import WeeklyActionPlanningService


class WeeklyActionPlanningTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='week-owner@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(name='Weekly plan', slug='weekly-plan', owner=self.owner)
        self.run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace, source_type='CSV', source_key='CSV', analysis_as_of=timezone.now(),
            source_scope={}, source_scope_fingerprint='scope', source_snapshot_fingerprint='snapshot',
            policy_version='test', policy_checksum='test', status='COMPLETED', is_current=True,
            completed_at=timezone.now(),
        )

    def _decision(self, decision_id, sku):
        return DecisionRecord.objects.create(
            decision_id=decision_id, workspace_id=self.workspace.id, sku=sku,
            assessment_run=self.run, status='RECOMMENDED', action_type='BUNDLE', urgency='HIGH',
            priority_tier='P1', capital_exposure=100_000, risk_score=0.5,
            decision_evidence_snapshot={'state': 'READY'},
        )

    def test_weekly_snapshot_assigns_selected_work_without_creating_action_plan(self):
        first = self._decision('DEC-WEEK-1', 'SKU-WEEK-1')
        self._decision('DEC-WEEK-2', 'SKU-WEEK-2')
        portfolio = DecisionPortfolioService.build(
            workspace_id=self.workspace.id, config={'capacity': {'max_actions': 1}},
        )
        result = WeeklyActionPlanningService.create(
            workspace_id=self.workspace.id, actor='owner@example.test',
            config={
                'portfolio_run_id': portfolio['run_id'],
                'assignments': {first.decision_id: self.owner.id},
            },
        )
        self.assertEqual(result['summary']['today'], 1)
        self.assertEqual(result['sections']['today'][0]['decision_id'], first.decision_id)
        self.assertEqual(result['sections']['today'][0]['owner']['user_id'], self.owner.id)
        self.assertEqual(result['summary']['deferred'], 1)
        self.assertEqual(ActionPlanRecord.objects.filter(workspace_id=self.workspace.id).count(), 0)

    def test_selected_sku_without_owner_is_visible_as_needing_assignment(self):
        self._decision('DEC-WEEK-NO-OWNER', 'SKU-WEEK-NO-OWNER')
        portfolio = DecisionPortfolioService.build(
            workspace_id=self.workspace.id, config={'capacity': {'max_actions': 1}},
        )
        result = WeeklyActionPlanningService.create(
            workspace_id=self.workspace.id, actor='owner@example.test', config={'portfolio_run_id': portfolio['run_id']},
        )
        self.assertEqual(result['summary']['needs_owner'], 1)
        self.assertIn('Chỉ định người phụ trách', result['sections']['needs_owner'][0]['next_step'])
