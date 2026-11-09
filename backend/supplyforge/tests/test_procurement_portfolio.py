from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from supplyforge.models import (
    DecisionRecord, InventoryRecord, ProcurementBudget, Sku,
    SlowMovingAssessmentRun, Supplier, SupplierSkuTerm, User, Workspace,
)
from supplyforge.services.procurement_planning import ProcurementPlanningService


class ProcurementPortfolioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='procurement-portfolio@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(name='Procurement portfolio', slug='procurement-portfolio', owner=self.user)
        self.supplier = Supplier.objects.create(workspace=self.workspace, name='NCC')
        self.run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace, source_type='CSV', source_key='CSV', analysis_as_of=timezone.now(),
            source_scope={}, source_scope_fingerprint='scope', source_snapshot_fingerprint='snapshot',
            policy_version='test', policy_checksum='test', status='COMPLETED', is_current=True,
            completed_at=timezone.now(),
        )
        for sku in ('SKU-ORDER', 'SKU-STOP'):
            stock_sku = Sku.objects.create(workspace=self.workspace, original_name=sku, normalized_name=sku)
            InventoryRecord.objects.create(
                sku=stock_sku, canonical_sku=sku, warehouse_code='MAIN', record_date=timezone.localdate(),
                quantity=10, available_quantity=10, as_of_verified=True,
            )
            SupplierSkuTerm.objects.create(
                supplier=self.supplier, canonical_sku=sku, lead_time_days=7, moq=1,
                order_multiple=1, unit_cost=Decimal('100'), effective_from=timezone.localdate(),
            )

    @staticmethod
    def _forecast(*, workspace_id, sku, horizon_days, persist, **kwargs):
        return {
            'status': 'READY', 'sku': sku, 'horizon_days': horizon_days,
            'estimated_stockout_date': (timezone.localdate() + timedelta(days=2)).isoformat(),
            'recommended_order_quantity': 10, 'capital_required': 500,
            'recommendation': 'ORDER', 'open_purchase_orders': [], 'lineage': {},
        }

    @patch.object(ProcurementPlanningService, 'plan_sku', side_effect=_forecast.__func__)
    def test_stop_replenishment_overrides_order_and_does_not_mutate_po(self, _forecast):
        today = timezone.localdate()
        ProcurementBudget.objects.create(
            workspace=self.workspace, period_start=today, period_end=today + timedelta(days=30), amount=1_000,
        )
        DecisionRecord.objects.create(
            decision_id='STOP-1', workspace_id=self.workspace.id, sku='SKU-STOP', assessment_run=self.run,
            status='RECOMMENDED', action_type='STOP_REPLENISHMENT',
            decision_evidence_snapshot={'state': 'READY'},
        )

        result = ProcurementPlanningService.plan_portfolio(workspace_id=self.workspace.id, horizon_days=30)
        states = {item['sku']: item['portfolio_state'] for item in result['items']}

        self.assertEqual(states['SKU-ORDER'], 'ORDER_REVIEW')
        self.assertEqual(states['SKU-STOP'], 'REVIEW_STOP_REPLENISHMENT')
        stop_item = next(item for item in result['items'] if item['sku'] == 'SKU-STOP')
        self.assertEqual(stop_item['slow_moving_conflict']['decision_ids'], ['STOP-1'])
        self.assertIn('không tự tạo', result['boundary'])

    @patch.object(ProcurementPlanningService, 'plan_sku', side_effect=_forecast.__func__)
    def test_insufficient_or_missing_budget_requires_review(self, _forecast):
        today = timezone.localdate()
        ProcurementBudget.objects.create(
            workspace=self.workspace, period_start=today, period_end=today + timedelta(days=30), amount=400,
        )
        result = ProcurementPlanningService.plan_portfolio(workspace_id=self.workspace.id, horizon_days=30)
        self.assertTrue(all(item['portfolio_state'] == 'REVIEW_BUDGET' for item in result['items']))
        self.assertEqual(result['budget']['remaining_before_new_orders'], 400.0)
