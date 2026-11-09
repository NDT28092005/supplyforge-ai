"""Regression tests for trusted CSV slow-moving operational runs."""

import json
from datetime import date, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from supplyforge.models import (
    DatasetVersion,
    DecisionRecord,
    IngestionSession,
    InventoryRecord,
    Order,
    OrderItem,
    Product,
    Sku,
    SlowMovingAlertState,
    SlowMovingAssessmentRun,
    SlowMovingRiskAssessment,
    SlowMovingDispositionEvent,
    User,
    Workspace,
)
from supplyforge.services.auto_decision_generator import AutoDecisionGeneratorService
from supplyforge.services.slow_moving_run_service import SlowMovingRunService


class SlowMovingOperationalRunTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='slow-moving-run@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='Slow moving operational run', slug='slow-moving-operational-run', owner=self.user,
        )
        self.as_of = date(2026, 10, 29)
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='slow-moving.csv',
            date_range_start=date(2026, 7, 1),
            date_range_end=self.as_of,
            status='COMPLETED',
        )
        self.version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime.combine(self.as_of, datetime.max.time())),
        )

    def _add_catalog_and_inventory(self, sku):
        product = Product.objects.create(
            id=f'product-{sku}', user_id=str(self.user.id), workspace=self.workspace,
            third_party_id=f'product-{sku}', item_sku=sku, canonical_sku=sku,
            product_name=f'Product {sku}', active_on_web=True,
        )
        inventory_sku = Sku.objects.create(
            workspace=self.workspace, original_name=sku, normalized_name=sku,
        )
        InventoryRecord.objects.create(
            sku=inventory_sku, canonical_sku=sku, warehouse_code='MAIN',
            record_date=self.as_of, available_quantity=25, quantity=25,
            cost_price=100_000, selling_price=150_000, lifecycle_status='ACTIVE',
            as_of_verified=True, source_snapshot_id=f'CSV-{sku}-{self.as_of.isoformat()}',
        )
        return product

    def _add_order(self, suffix, sku, event_date, *, status='COMPLETED', verified=True):
        event_at = timezone.make_aware(datetime.combine(event_date, datetime.min.time()))
        order = Order.objects.create(
            id=f'order-{suffix}', user_id=str(self.user.id), workspace=self.workspace,
            order_id=f'ORDER-{suffix}', status=status, is_accounting=True,
            demand_eligibility_verified=verified, source_event_at=event_at,
            created_at=event_at,
        )
        OrderItem.objects.create(
            order=order, sku=sku, canonical_sku=sku, product_name=sku, quantity=1,
        )

    def test_current_run_uses_qualified_history_and_requires_two_runs_to_open(self):
        self._add_catalog_and_inventory('SKU-OLD')
        self._add_catalog_and_inventory('SKU-UNVERIFIED')
        self._add_order('old', 'SKU-OLD', date(2026, 7, 1))
        self._add_order('unverified', 'SKU-UNVERIFIED', date(2026, 7, 1), status='UNKNOWN', verified=False)

        first = SlowMovingRunService.run_csv_for_dataset(self.version)
        old = SlowMovingRiskAssessment.objects.get(assessment_run=first, sku='SKU-OLD')
        unverified = SlowMovingRiskAssessment.objects.get(assessment_run=first, sku='SKU-UNVERIFIED')
        self.assertEqual(old.assessment_status, 'COMPLETE')
        self.assertIsNone(old.risk_probability)
        self.assertEqual(old.evidence['score_semantics'], 'RULE_PRIORITY_NOT_PROBABILITY')
        self.assertEqual(old.evidence['alert_lifecycle_status'], 'CANDIDATE')
        self.assertEqual(unverified.assessment_status, 'INSUFFICIENT_HISTORY')

        self.version.status = DatasetVersion.STATUS_SUPERSEDED
        self.version.save(update_fields=['status'])
        second_session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename='slow-moving-v2.csv',
            date_range_start=date(2026, 7, 1), date_range_end=self.as_of, status='COMPLETED',
        )
        second_version = DatasetVersion.objects.create(
            workspace=self.workspace, ingestion_session=second_session,
            parent_version=self.version, version_number=2, version_label='v2.0',
            import_type='INITIAL', status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime.combine(self.as_of, datetime.max.time())),
        )
        second = SlowMovingRunService.run_csv_for_dataset(second_version)

        self.assertTrue(second.is_current)
        self.assertFalse(SlowMovingAssessmentRun.objects.get(id=first.id).is_current)
        alert = SlowMovingAlertState.objects.get(workspace=self.workspace, canonical_sku='SKU-OLD')
        self.assertEqual(alert.status, SlowMovingAlertState.STATUS_OPEN)
        self.assertEqual(alert.consecutive_eligible_runs, 2)

        response = self.client.get('/api/v1/risk/assessments/list')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source']['run_id'], str(second.id))
        self.assertEqual(response.data['total_count'], 1)
        self.assertEqual(response.data['assessments'][0]['sku'], 'SKU-OLD')

        disposition = self.client.post(
            '/api/v1/risk/dispositions',
            data=json.dumps({
                'source': 'CSV', 'canonical_sku': 'SKU-OLD',
                'event_type': 'STOCK_TRANSFER',
                'occurred_at': (second.analysis_as_of + timedelta(days=1)).isoformat(),
                'evidence_reference': 'transfer-proof-1',
            }),
            content_type='application/json',
        )
        self.assertEqual(disposition.status_code, 201)
        event = SlowMovingDispositionEvent.objects.get(id=disposition.data['id'])
        self.assertEqual(event.source_scope_fingerprint, second.source_scope_fingerprint)
        self.assertEqual(event.canonical_sku, 'SKU-OLD')

    def test_open_current_alert_persists_localized_option_snapshot(self):
        self._add_catalog_and_inventory('SKU-OPTIONS')
        self._add_order('options-old', 'SKU-OPTIONS', date(2026, 7, 1))
        first = SlowMovingRunService.run_csv_for_dataset(self.version)
        self.assertTrue(first.is_current)

        self.version.status = DatasetVersion.STATUS_SUPERSEDED
        self.version.save(update_fields=['status'])
        next_session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename='slow-moving-options-v2.csv',
            date_range_start=date(2026, 7, 1), date_range_end=self.as_of, status='COMPLETED',
        )
        next_version = DatasetVersion.objects.create(
            workspace=self.workspace, ingestion_session=next_session,
            parent_version=self.version, version_number=2, version_label='v2.0',
            import_type='INITIAL', status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime.combine(self.as_of, datetime.max.time())),
        )
        current = SlowMovingRunService.run_csv_for_dataset(next_version)
        self.assertTrue(current.is_current)

        created = AutoDecisionGeneratorService.generate_decisions_from_assessments(
            workspace_id=self.workspace.id,
        )
        self.assertEqual(len(created), 1)
        decision = DecisionRecord.objects.get(assessment_run=current, sku='SKU-OPTIONS')
        option_set = decision.action_parameters['merchant_option_set']
        self.assertEqual(option_set['version'], 'MERCHANT_DECISION_OPTIONS_V1')
        labels = [option['label'] for option in option_set['options']]
        self.assertIn('Giữ giá và theo dõi', labels)
        self.assertIn('Giảm giá có kiểm soát', labels)
        self.assertIn('Xả hàng nhanh có phê duyệt', labels)
        self.assertTrue(all('score' not in option and 'action' not in option for option in option_set['options']))
