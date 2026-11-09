"""Regression tests for tenant-scoped operational SKU action plans."""

from django.test import TestCase
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from unittest.mock import patch

from supplyforge.models import (
    IngestionSession, IntegrationConnection, InventoryRecord, Sku, SlowMovingRiskAssessment,
    TenantFeatureSnapshot, User, Workspace,
)
from supplyforge.models.action_plan import ActionPlanEventRecord, ActionPlanRecord
from supplyforge.models.decision import DecisionRecord
from supplyforge.services.decision_evidence_freshness import DecisionEvidenceFreshnessService
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

    def _create_current_odoo_evidence(self, sku: str) -> tuple[InventoryRecord, dict]:
        connection = IntegrationConnection.objects.create(
            workspace=self.workspace,
            provider='ODOO',
            display_name='Odoo test',
            status=IntegrationConnection.STATUS_ACTIVE,
            base_url='https://odoo.example.test',
        )
        inventory_sku = Sku.objects.create(
            workspace=self.workspace,
            original_name=sku,
            normalized_name=sku,
        )
        record = InventoryRecord.objects.create(
            sku=inventory_sku,
            canonical_sku=sku,
            warehouse_code='WH-01',
            record_date=timezone.localdate(),
            quantity=100,
            available_quantity=100,
            cost_price=70_000,
            selling_price=100_000,
            lifecycle_status='ACTIVE',
            as_of_verified=True,
            source_snapshot_id=f'ODOO:{connection.id}:today:{sku}:WH-01',
            source_observed_at=timezone.now(),
            source_lineage_json={
                'provider': 'ODOO',
                'connection_id': str(connection.id),
            },
        )
        return record, DecisionEvidenceFreshnessService.capture(
            workspace_id=self.workspace.id,
            sku=sku,
        )

    def test_decision_backed_plan_requires_outcome_to_complete(self):
        decision = DecisionRecord.objects.create(
            decision_id='WS-ACTION-DEC-001',
            workspace_id=self.workspace.id,
            sku='SKU-ACTION-001',
            action_type='BUNDLE',
            expected_recovery_value=1_200_000,
            status='ACCEPTED',
            action_parameters={'projection': {'status': 'SCENARIO_ESTIMATE'}},
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
        tasks = self.client.get(f'/api/v1/action-plans/{plan_id}/tasks/')
        self.assertEqual(tasks.status_code, 200)
        for task in tasks.data['checklist']['items']:
            result = self.client.patch(
                f"/api/v1/action-plans/{plan_id}/tasks/{task['id']}/",
                {'status': 'SKIPPED', 'skipped_reason': 'Không áp dụng cho thử nghiệm hồi quy.'},
                format='json',
            )
            self.assertEqual(result.status_code, 200)
        outcome = self.client.patch(
            f'/api/v1/action-plans/{plan_id}/outcome/', {
                'actual_recovery_value': 900_000,
                'actual_units_sold': 18,
                'outcome_notes': 'Discount campaign closed after 14 days.',
            }, format='json')
        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(outcome.data['status'], 'COMPLETED')
        self.assertEqual(outcome.data['outcome']['recovery_accuracy_pct'], 75.0)
        self.assertEqual(ActionPlanEventRecord.objects.filter(plan_id=plan_id).count(), 7)
        decision.refresh_from_db()
        self.assertEqual(decision.status, 'COMPLETED')

        history = self.client.get(f'/api/v1/action-plans/{plan_id}/history/')
        summary = self.client.get('/api/v1/action-plans/summary/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data['history']), 7)
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

    def test_overlapping_incompatible_plans_are_blocked_but_explicit_other_warehouse_is_allowed(self):
        first = self.client.post('/api/v1/action-plans/', {
            'sku': 'SKU-SCOPE-GUARD', 'campaign': 'Giảm giá kho HCM', 'owner': 'Merchandising',
            'duration': 14, 'start': '2026-10-01', 'due_date': '2026-10-15', 'strategy': 'DISCOUNT',
            'execution_scope': {'warehouse_code': 'WH-HCM', 'channel': 'Web'},
        }, format='json')
        self.assertEqual(first.status_code, 201)

        conflict = self.client.post('/api/v1/action-plans/', {
            'sku': 'SKU-SCOPE-GUARD', 'campaign': 'Xả kho trùng', 'owner': 'Merchandising',
            'duration': 7, 'start': '2026-10-05', 'due_date': '2026-10-12', 'strategy': 'CLEARANCE',
            'execution_scope': {'warehouse_code': 'WH-HCM', 'channel': 'Web'},
        }, format='json')
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data['error']['code'], 'ACTION_PLAN_CONFLICT')
        self.assertEqual(len(conflict.data['conflicting_plans']), 1)

        separate = self.client.post('/api/v1/action-plans/', {
            'sku': 'SKU-SCOPE-GUARD', 'campaign': 'Xả kho Hà Nội', 'owner': 'Merchandising',
            'duration': 7, 'start': '2026-10-05', 'due_date': '2026-10-12', 'strategy': 'CLEARANCE',
            'execution_scope': {'warehouse_code': 'WH-HN', 'channel': 'Web'},
        }, format='json')
        self.assertEqual(separate.status_code, 201)

    @patch('supplyforge.services.model_runtime_guard.ModelLoaderService.runtime_status')
    def test_model_backed_plan_does_not_start_when_runtime_is_not_ready(self, runtime_status):
        runtime_status.return_value = {
            'state': 'UNAVAILABLE',
            'model_version': 'risk-v1',
            'explainability': 'UNAVAILABLE',
            'decision_actions_allowed': False,
        }
        decision = DecisionRecord.objects.create(
            decision_id='WS-MODEL-PLAN-GUARD', workspace_id=self.workspace.id,
            sku='SKU-MODEL-PLAN-GUARD', action_type='MONITOR', status='ACCEPTED',
            action_parameters={'model_runtime_required': True},
        )
        plan = ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, decision_id=decision.decision_id,
            campaign_name='Model-backed plan', sku=decision.sku, strategy='MONITOR',
            owner='Merchandising', start_date='2026-10-01', due_date='2026-10-15',
            status='CONFIRMED',
        )

        response = self.client.patch(
            f'/api/v1/action-plans/{plan.plan_id}/status/', {'status': 'IN_PROGRESS'}, format='json'
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['error']['code'], 'MODEL_RUNTIME_NOT_READY')
        plan.refresh_from_db()
        decision.refresh_from_db()
        self.assertEqual(plan.status, 'CONFIRMED')
        self.assertEqual(decision.status, 'ACCEPTED')

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

    def test_plan_requires_approved_eligible_decision_and_keeps_execution_parameters(self):
        _, evidence_snapshot = self._create_current_odoo_evidence('SKU-GUARDRAIL')
        decision = DecisionRecord.objects.create(
            decision_id='WS-ACTION-DEC-GUARDRAIL',
            workspace_id=self.workspace.id,
            sku='SKU-GUARDRAIL',
            action_type='DISCOUNT',
            discount_rate=0.20,
            status='REVIEWED',
            action_parameters={
                'eligibility': {
                    'eligible_actions': ['DISCOUNT'],
                    'requires_review_actions': ['BUNDLE'],
                    'blocked_actions': ['CLEARANCE'],
                },
                'evidence_snapshot': evidence_snapshot,
            },
        )
        base_payload = {
            'decision_id': decision.decision_id,
            'sku': decision.sku,
            'campaign': 'Controlled SKU plan',
            'owner': 'Merchandising',
            'duration': 14,
            'start': '2026-10-01',
            'due_date': '2026-10-15',
            'strategy': 'DISCOUNT',
        }

        not_approved = self.client.post('/api/v1/action-plans/', base_payload, format='json')
        self.assertEqual(not_approved.status_code, 409)
        self.assertEqual(not_approved.data['error']['code'], 'DECISION_APPROVAL_REQUIRED')

        decision.status = 'ACCEPTED'
        decision.save(update_fields=['status'])
        blocked = self.client.post('/api/v1/action-plans/', {
            **base_payload,
            'strategy': 'CLEARANCE',
            'strategy_override_reason': 'Need a faster clearance campaign.',
        }, format='json')
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data['error']['code'], 'INVALID_STRATEGY')

        created = self.client.post('/api/v1/action-plans/', {
            **base_payload,
            'execution_parameters': {'discount_rate': 0.25},
            'strategy_override_reason': 'Margin remains acceptable in the selected channel.',
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['strategy'], 'DISCOUNT')
        self.assertEqual(created.data['action_parameters']['discount_rate'], 0.25)
        self.assertEqual(created.data['action_parameters']['source'], 'DECISION_RECOMMENDATION')

    def test_price_plan_requires_revalidation_and_records_owner_override(self):
        record, evidence_snapshot = self._create_current_odoo_evidence('SKU-FRESHNESS')
        decision = DecisionRecord.objects.create(
            decision_id='WS-ACTION-DEC-FRESHNESS',
            workspace_id=self.workspace.id,
            sku='SKU-FRESHNESS',
            action_type='DISCOUNT',
            status='ACCEPTED',
            action_parameters={
                'eligibility': {'eligible_actions': ['DISCOUNT']},
                'evidence_snapshot': evidence_snapshot,
            },
        )
        payload = {
            'decision_id': decision.decision_id,
            'sku': decision.sku,
            'campaign': 'Giảm giá có kiểm soát',
            'owner': 'Merchandising',
            'duration': 14,
            'start': '2026-10-01',
            'due_date': '2026-10-15',
            'strategy': 'DISCOUNT',
        }
        record.available_quantity = 80
        record.save(update_fields=['available_quantity', 'updated_at'])

        blocked = self.client.post('/api/v1/action-plans/', payload, format='json')
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.data['error']['code'], 'DECISION_REVALIDATION_REQUIRED')
        self.assertTrue(blocked.data['data_evidence']['override_allowed'])

        created = self.client.post('/api/v1/action-plans/', {
            **payload,
            'data_evidence_override_reason': 'Đã kiểm tra tồn thực tế và chấp nhận thay đổi trước chiến dịch.',
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['action_parameters']['data_evidence']['state'], 'OVERRIDDEN')
        self.assertEqual(
            created.data['action_parameters']['execution_evidence_snapshot']['records'][0]['available_quantity'],
            '80.0000',
        )

    def test_confirmation_rechecks_the_execution_baseline(self):
        record, evidence_snapshot = self._create_current_odoo_evidence('SKU-CONFIRM-FRESHNESS')
        decision = DecisionRecord.objects.create(
            decision_id='WS-ACTION-DEC-CONFIRM-FRESHNESS',
            workspace_id=self.workspace.id,
            sku='SKU-CONFIRM-FRESHNESS',
            action_type='DISCOUNT',
            status='ACCEPTED',
            action_parameters={
                'eligibility': {'eligible_actions': ['DISCOUNT']},
                'evidence_snapshot': evidence_snapshot,
            },
        )
        created = self.client.post('/api/v1/action-plans/', {
            'decision_id': decision.decision_id,
            'sku': decision.sku,
            'campaign': 'Giảm giá đã kiểm tra',
            'owner': 'Merchandising',
            'duration': 14,
            'start': '2026-10-01',
            'due_date': '2026-10-15',
            'strategy': 'DISCOUNT',
        }, format='json')
        self.assertEqual(created.status_code, 201)

        record.selling_price = 95_000
        record.save(update_fields=['selling_price', 'updated_at'])
        plan_id = created.data['plan_id']
        blocked = self.client.patch(
            f'/api/v1/action-plans/{plan_id}/status/', {'status': 'CONFIRMED'}, format='json'
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.data['data_evidence']['code'], 'ODOO_FACTS_CHANGED')

        confirmed = self.client.patch(f'/api/v1/action-plans/{plan_id}/status/', {
            'status': 'CONFIRMED',
            'data_evidence_override_reason': 'Giá mới đã được kiểm tra, biên lợi nhuận vẫn đạt ngưỡng phê duyệt.',
        }, format='json')
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data['status'], 'CONFIRMED')
        self.assertEqual(confirmed.data['action_parameters']['data_evidence']['state'], 'OVERRIDDEN')

    def test_decision_summary_is_portfolio_scoped_and_price_simulation_is_guarded(self):
        DecisionRecord.objects.create(
            decision_id='WS-SUM-1', workspace_id=self.workspace.id, sku='SKU-SUM-1',
            risk_class='CRITICAL', priority_tier='P1', action_type='DISCOUNT',
            capital_exposure=12_000_000, expected_recovery_value=8_000_000,
            status='RECOMMENDED',
        )
        DecisionRecord.objects.create(
            decision_id='WS-SUM-2', workspace_id=self.workspace.id, sku='SKU-SUM-2',
            risk_class='HIGH_RISK', priority_tier='P2', action_type='MONITOR',
            capital_exposure=3_000_000, expected_recovery_value=0,
            status='REVIEWED',
        )
        monitor = DecisionRecord.objects.create(
            decision_id='WS-SUM-3', workspace_id=self.workspace.id, sku='SKU-SUM-3',
            risk_class='MEDIUM_RISK', priority_tier='P3', action_type='MONITOR',
            status='RECOMMENDED',
        )

        summary = self.client.get('/api/v1/decisions/summary/')
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data['at_risk_skus'], 2)
        self.assertEqual(summary.data['capital_exposure'], 15_000_000.0)
        self.assertEqual(summary.data['projected_recovery_value'], 8_000_000.0)
        self.assertEqual(summary.data['projected_sku_count'], 1)
        self.assertEqual(summary.data['needs_review_count'], 2)

        simulation = self.client.post('/api/v1/decisions/simulate/', {
            'decision_id': monitor.decision_id,
            'discount_rate': 0.15,
            'duration_days': 14,
        }, format='json')
        self.assertEqual(simulation.status_code, 422)
        self.assertEqual(simulation.data['code'], 'SIMULATION_NOT_APPLICABLE')

    def test_price_actions_require_verified_inventory_and_observed_demand(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename='simulation-input.csv', status='COMPLETED',
        )

        def create_inputs(sku, velocity):
            inventory_sku = Sku.objects.create(
                workspace=self.workspace, original_name=sku, normalized_name=sku,
            )
            InventoryRecord.objects.create(
                sku=inventory_sku, canonical_sku=sku, record_date=timezone.localdate(),
                quantity=100, available_quantity=100, cost_price=70_000,
                selling_price=100_000, as_of_verified=True,
            )
            SlowMovingRiskAssessment.objects.create(
                session=session, sku=sku, canonical_sku_id=sku, product_name=sku,
                risk_class='CRITICAL', risk_probability=0.9, risk_score=90,
                evidence={'sales_velocity_30d': velocity, 'sales_velocity_90d': velocity},
            )

        legacy = DecisionRecord.objects.create(
            decision_id='LEGACY-PRICE-ACTION', workspace_id=self.workspace.id, sku='SKU-LEGACY-PRICE',
            action_type='DISCOUNT_CLEARANCE', capital_exposure=7_000_000,
        )
        create_inputs(legacy.sku, 1.0)
        supported = self.client.post('/api/v1/decisions/simulate/', {'decision_id': legacy.decision_id}, format='json')
        self.assertEqual(supported.status_code, 200)
        self.assertTrue(supported.data['success'])

        no_demand = DecisionRecord.objects.create(
            decision_id='ZERO-DEMAND-PRICE-ACTION', workspace_id=self.workspace.id, sku='SKU-ZERO-DEMAND',
            action_type='DISCOUNT', capital_exposure=7_000_000,
        )
        create_inputs(no_demand.sku, 0.0)
        blocked = self.client.post('/api/v1/decisions/simulate/', {'decision_id': no_demand.decision_id}, format='json')
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.data['code'], 'SIMULATION_DEMAND_UNAVAILABLE')
        self.assertIn('chưa ghi nhận nhu cầu bán', blocked.data['detail'])
