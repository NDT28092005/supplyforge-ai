"""Regression tests for tenant-scoped operational SKU action plans."""

from django.test import TestCase
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import IngestionSession, SlowMovingRiskAssessment, TenantFeatureSnapshot, User, Workspace
from supplyforge.models.action_plan import ActionPlanEventRecord, ActionPlanRecord
from supplyforge.models.decision import DecisionRecord
from supplyforge.views.auth import generate_access_token


class ActionPlanOperationalQueueTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = User.objects.create(
            email='action-queue-owner@example.com',
            role=User.ROLE_OWNER,
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace = Workspace.objects.create(
            name='Action Queue Workspace',
            slug='action-queue-workspace',
            owner=self.owner,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {generate_access_token(self.owner, self.workspace.id)}'
        )

    def test_decision_backed_plan_requires_outcome_to_complete(self):
        decision = DecisionRecord.objects.create(
            decision_id='WS-ACTION-DEC-001',
            workspace_id=self.workspace.id,
            sku='SKU-ACTION-001',
            action_type='DISCOUNT',
            expected_recovery_value=1_200_000,
            status='ACCEPTED',
        )
        create = self.client.post('/api/v1/action-plans/', {
            'decision_id': decision.decision_id,
            'sku': decision.sku,
            'campaign': 'Clearance SKU-ACTION-001',
            'owner': 'Merchandising A',
            'duration': 14,
            'start': '2026-10-01',
            'due_date': '2026-10-15',
        }, format='json')
        self.assertEqual(create.status_code, 201)
        plan_id = create.data['plan_id']
        self.assertEqual(create.data['expected_recovery_value'], 1_200_000)
        self.assertEqual(create.data['status'], 'DRAFT')

        self.assertEqual(self.client.patch(
            f'/api/v1/action-plans/{plan_id}/status/', {'status': 'CONFIRMED'}, format='json'
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f'/api/v1/action-plans/{plan_id}/status/', {'status': 'IN_PROGRESS'}, format='json'
        ).status_code, 200)
        decision.refresh_from_db()
        self.assertEqual(decision.status, 'EXECUTED')

        self.assertEqual(self.client.patch(
            f'/api/v1/action-plans/{plan_id}/status/', {'status': 'COMPLETED'}, format='json'
        ).status_code, 400)
        outcome = self.client.patch(
            f'/api/v1/action-plans/{plan_id}/outcome/', {
                'actual_recovery_value': 900_000,
                'actual_units_sold': 18,
                'outcome_notes': 'Discount campaign closed after 14 days.',
            }, format='json')
        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(outcome.data['status'], 'COMPLETED')
        self.assertEqual(outcome.data['outcome']['recovery_accuracy_pct'], 75.0)
        self.assertEqual(ActionPlanEventRecord.objects.filter(plan_id=plan_id).count(), 4)
        decision.refresh_from_db()
        self.assertEqual(decision.status, 'COMPLETED')

        history = self.client.get(f'/api/v1/action-plans/{plan_id}/history/')
        summary = self.client.get('/api/v1/action-plans/summary/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data['history']), 4)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data['completed_plans'], 1)
        self.assertEqual(summary.data['actual_recovery_value'], 900_000)

    def test_paginated_queue_and_sales_outcome_summary(self):
        for index in range(12):
            ActionPlanRecord.objects.create(
                workspace_id=self.workspace.id,
                campaign_name=f'Plan {index}', sku=f'SKU-{index:03d}',
                strategy='DISCOUNT', owner='Merchandising', start_date='2026-10-01',
                due_date='2026-10-15', status='DRAFT',
            )

        page = self.client.get('/api/v1/action-plans/?page=2&page_size=5')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.data['items']), 5)
        self.assertEqual(page.data['pagination']['total_items'], 12)
        self.assertEqual(page.data['pagination']['total_pages'], 3)

        plan = ActionPlanRecord.objects.filter(workspace_id=self.workspace.id).first()
        plan.status = 'IN_PROGRESS'
        plan.expected_sales_value = 2_000_000
        plan.save(update_fields=['status', 'expected_sales_value'])
        result = self.client.patch(f'/api/v1/action-plans/{plan.plan_id}/outcome/', {
            'actual_recovery_value': 1_000_000,
            'actual_sales_value': 1_500_000,
            'actual_units_sold': 12,
        }, format='json')
        self.assertEqual(result.status_code, 200)
        summary = self.client.get('/api/v1/action-plans/summary/')
        self.assertEqual(summary.data['actual_sales_value'], 1_500_000)
        self.assertEqual(summary.data['completed_sku_count'], 1)

    def test_effectiveness_uses_only_frozen_observed_labels(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename='observed.csv', status='COMPLETED',
        )
        rows = [
            ('SKU-OBS-1', 'HIGH_RISK', 90, 'HIGH_RISK'),
            ('SKU-OBS-2', 'LOW_RISK', 80, 'HIGH_RISK'),
            ('SKU-OBS-3', 'HIGH_RISK', 70, 'LOW_RISK'),
        ]
        for sku, predicted, score, actual in rows:
            assessment = SlowMovingRiskAssessment.objects.create(
                session=session, sku=sku, canonical_sku_id=sku, product_name=sku,
                risk_class=predicted, risk_probability=score / 100, risk_score=score,
            )
            TenantFeatureSnapshot.objects.create(
                workspace=self.workspace, sku_id=sku, feature_vector_json={},
                source_lineage_json={'riskAssessmentId': str(assessment.id)},
                actual_risk_level=actual,
                label_frozen_at=timezone.now(),
            )

        response = self.client.get('/api/v1/decision-effectiveness/?k=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'READY')
        self.assertEqual(response.data['precision_at_k'], 1.0)
        self.assertEqual(response.data['recall_high_risk_at_k'], 1.0)
        self.assertEqual(response.data['high_risk_precision'], 0.5)

    def test_list_is_scoped_to_authenticated_workspace(self):
        other = Workspace.objects.create(
            name='Other Action Queue Workspace',
            slug='other-action-queue-workspace',
            owner=self.owner,
        )
        ActionPlanRecord.objects.create(
            workspace_id=other.id,
            campaign_name='Other workspace plan',
            sku='SKU-OTHER',
            strategy='DISCOUNT',
            owner='Other team',
            start_date='2026-10-01',
            due_date='2026-10-15',
        )

        response = self.client.get('/api/v1/action-plans/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
