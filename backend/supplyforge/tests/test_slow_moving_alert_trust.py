"""Focused regression coverage for merchant-trust slow-moving extensions."""

from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from supplyforge.models import (
    DatasetVersion,
    IngestionSession,
    InventoryRecord,
    Order,
    OrderItem,
    Product,
    Sku,
    SlowMovingAlertPassport,
    SlowMovingAlertState,
    SlowMovingAlertDigestDelivery,
    SlowMovingFeedbackRemediation,
    SlowMovingSkuContext,
    User,
    Workspace,
)
from supplyforge.services.slow_moving_alert_operations import (
    SlowMovingAlertDigestService,
    SlowMovingAlertHealthService,
)
from supplyforge.services.slow_moving_run_service import SlowMovingRunService


class SlowMovingAlertTrustTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='slow-alert-trust@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='Slow alert trust', slug='slow-alert-trust', owner=self.user,
        )
        self.as_of = date(2026, 10, 29)
        self.session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename='trust-v1.csv',
            date_range_start=date(2026, 7, 1), date_range_end=self.as_of,
            status='COMPLETED',
        )
        self.version = DatasetVersion.objects.create(
            workspace=self.workspace, ingestion_session=self.session,
            version_number=1, version_label='trust-v1', import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime.combine(self.as_of, datetime.max.time())),
        )
        self.sku = 'SKU-TRUST'
        Product.objects.create(
            id='product-slow-alert-trust', user_id=str(self.user.id), workspace=self.workspace,
            third_party_id='product-slow-alert-trust', item_sku=self.sku,
            canonical_sku=self.sku, product_name='Trust product', active_on_web=True,
        )
        inventory_sku = Sku.objects.create(
            workspace=self.workspace, original_name=self.sku, normalized_name=self.sku,
        )
        InventoryRecord.objects.create(
            sku=inventory_sku, canonical_sku=self.sku, warehouse_code='MAIN',
            record_date=self.as_of, available_quantity=25, quantity=25, cost_price=100,
            selling_price=150, lifecycle_status='ACTIVE', as_of_verified=True,
            source_snapshot_id='trust-stock-v1',
        )
        event_at = timezone.make_aware(datetime.combine(date(2026, 7, 1), datetime.min.time()))
        order = Order.objects.create(
            id='trust-order', user_id=str(self.user.id), workspace=self.workspace,
            order_id='TRUST-ORDER', status='COMPLETED', is_accounting=True,
            demand_eligibility_verified=True, source_event_at=event_at, created_at=event_at,
        )
        OrderItem.objects.create(order=order, sku=self.sku, canonical_sku=self.sku, product_name=self.sku, quantity=1)

    def _next_version(self, number: int):
        previous = DatasetVersion.objects.get(status=DatasetVersion.STATUS_ACTIVE)
        previous.status = DatasetVersion.STATUS_SUPERSEDED
        previous.save(update_fields=['status'])
        session = IngestionSession.objects.create(
            workspace=self.workspace, original_filename=f'trust-v{number}.csv',
            date_range_start=date(2026, 7, 1), date_range_end=self.as_of, status='COMPLETED',
        )
        return DatasetVersion.objects.create(
            workspace=self.workspace, ingestion_session=session, parent_version=previous,
            version_number=number, version_label=f'trust-v{number}', import_type='INCREMENTAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime.combine(self.as_of, datetime.max.time())),
        )

    def _add_second_eligible_sku(self):
        sku = 'SKU-CURSOR'
        Product.objects.create(
            id='product-slow-alert-cursor', user_id=str(self.user.id), workspace=self.workspace,
            third_party_id='product-slow-alert-cursor', item_sku=sku, canonical_sku=sku,
            product_name='Cursor product', active_on_web=True,
            created_at=timezone.make_aware(datetime(2026, 7, 1)),
        )
        inventory_sku = Sku.objects.create(
            workspace=self.workspace, original_name=sku, normalized_name=sku,
        )
        InventoryRecord.objects.create(
            sku=inventory_sku, canonical_sku=sku, warehouse_code='MAIN',
            record_date=self.as_of, available_quantity=15, quantity=15, cost_price=100,
            selling_price=150, lifecycle_status='ACTIVE', as_of_verified=True,
            source_snapshot_id='cursor-stock-v1',
        )

    def test_non_sellable_context_blocks_assessment_and_exposes_context_reason(self):
        SlowMovingSkuContext.objects.create(
            workspace=self.workspace, canonical_sku=self.sku,
            availability=SlowMovingSkuContext.AVAILABILITY_HELD,
            catalog_role=SlowMovingSkuContext.ROLE_STANDALONE,
            evidence_reference='warehouse-count-2026-10-29', declared_by=str(self.user.id),
            effective_from=timezone.make_aware(datetime(2026, 1, 1)),
        )
        run = SlowMovingRunService.run_csv_for_dataset(self.version)
        assessment = run.assessments.get(canonical_sku_id=self.sku)
        self.assertEqual(assessment.assessment_status, 'LIFECYCLE_EXCLUDED')
        self.assertEqual(assessment.evidence['catalog_context']['status'], 'NOT_SELLABLE')
        self.assertIn('INVENTORY_HELD', assessment.evidence['eligibility_reasons'])

    def test_expired_merchant_context_requires_confirmation_instead_of_falling_back_to_sellable(self):
        SlowMovingSkuContext.objects.create(
            workspace=self.workspace,
            canonical_sku=self.sku,
            source_key='CSV',
            availability=SlowMovingSkuContext.AVAILABILITY_HELD,
            catalog_role=SlowMovingSkuContext.ROLE_STANDALONE,
            evidence_reference='warehouse-count-2026-09-01',
            provenance_json={'source': 'merchant-api'},
            declared_by=str(self.user.id),
            effective_from=timezone.make_aware(datetime(2026, 8, 1)),
            effective_to=timezone.make_aware(datetime(2026, 9, 1)),
        )
        run = SlowMovingRunService.run_csv_for_dataset(self.version)
        assessment = run.assessments.get(canonical_sku_id=self.sku)
        self.assertEqual(assessment.assessment_status, 'DATA_INCOMPLETE')
        self.assertEqual(assessment.evidence['catalog_context']['status'], 'DATA_NEEDED')
        self.assertIn('CATALOG_CONTEXT_EXPIRED', assessment.evidence['eligibility_reasons'])

    def test_resolved_alert_stays_closed_until_material_stock_change_then_has_passport(self):
        SlowMovingRunService.run_csv_for_dataset(self.version)
        second = SlowMovingRunService.run_csv_for_dataset(self._next_version(2))
        alert = SlowMovingAlertState.objects.get(workspace=self.workspace, canonical_sku=self.sku)
        self.assertEqual(alert.status, SlowMovingAlertState.STATUS_OPEN)

        closed = self.client.post(
            f'/api/v1/risk/alerts/{alert.id}/state',
            data={'action': 'RESOLVE', 'note': 'Đã rà soát tại kho.'},
            content_type='application/json',
        )
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(SlowMovingAlertState.objects.get(id=alert.id).status, SlowMovingAlertState.STATUS_RESOLVED)

        third = SlowMovingRunService.run_csv_for_dataset(self._next_version(3))
        alert.refresh_from_db()
        self.assertEqual(alert.status, SlowMovingAlertState.STATUS_RESOLVED)
        self.assertEqual(third.summary['alert_lifecycle'].get('RESOLVED'), 1)

        inventory = InventoryRecord.objects.get(canonical_sku=self.sku)
        InventoryRecord.objects.create(
            sku=inventory.sku, canonical_sku=self.sku, warehouse_code='MAIN',
            record_date=self.as_of, available_quantity=40, quantity=40, cost_price=100,
            selling_price=150, lifecycle_status='ACTIVE', as_of_verified=True,
            source_snapshot_id='trust-stock-v4',
        )
        fourth = SlowMovingRunService.run_csv_for_dataset(self._next_version(4))
        alert.refresh_from_db()
        self.assertEqual(alert.status, SlowMovingAlertState.STATUS_CANDIDATE)
        passport = SlowMovingAlertPassport.objects.get(alert_state=alert, assessment_run=fourth)
        self.assertEqual(passport.event_type, SlowMovingAlertPassport.EVENT_REOPENED)
        self.assertTrue(any(change.get('label') == 'Tồn có thể bán tăng' for change in passport.changed_facts_json))

    def test_feedback_creates_a_visible_remediation_and_health_keeps_quality_separate(self):
        SlowMovingRunService.run_csv_for_dataset(self.version)
        SlowMovingRunService.run_csv_for_dataset(self._next_version(2))
        alert = SlowMovingAlertState.objects.get(workspace=self.workspace, canonical_sku=self.sku)
        response = self.client.post(
            f'/api/v1/risk/alerts/{alert.id}/state',
            data={'action': 'ACKNOWLEDGE', 'feedback_reason': 'DISPLAY_STOCK'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        remediation = SlowMovingFeedbackRemediation.objects.get(alert_state=alert)
        self.assertEqual(remediation.remediation_type, SlowMovingFeedbackRemediation.TYPE_CATALOG)
        health = SlowMovingAlertHealthService.report(workspace_id=self.workspace.id)
        self.assertIn('alerts', health)
        self.assertIn('outcome_evidence', health)
        self.assertNotIn('high_risk_precision', health['outcome_evidence'])

    def test_in_app_digest_is_idempotent_and_never_assigns_an_unowned_alert(self):
        SlowMovingRunService.run_csv_for_dataset(self.version)
        SlowMovingRunService.run_csv_for_dataset(self._next_version(2))
        alert = SlowMovingAlertState.objects.get(workspace=self.workspace, canonical_sku=self.sku)
        alert.owner_label = 'ops@example.test'
        alert.next_review_at = timezone.now()
        alert.save(update_fields=['owner_label', 'next_review_at', 'updated_at'])

        first = SlowMovingAlertDigestService.prepare_in_app_digests(
            workspace_id=self.workspace.id,
        )
        second = SlowMovingAlertDigestService.prepare_in_app_digests(
            workspace_id=self.workspace.id,
        )

        self.assertEqual(first['digests_created'], 1)
        self.assertEqual(second['digests_created'], 0)
        self.assertEqual(second['digests_existing'], 1)
        delivery = SlowMovingAlertDigestDelivery.objects.get(workspace=self.workspace)
        self.assertEqual(delivery.status, SlowMovingAlertDigestDelivery.STATUS_QUEUED)
        self.assertEqual(delivery.alert_ids_json, [str(alert.id)])

    def test_cursor_queue_reads_typed_projection_without_json_metric_cast(self):
        self._add_second_eligible_sku()
        run = SlowMovingRunService.run_csv_for_dataset(self.version)
        self.assertTrue(run.assessments.filter(priority_score__isnull=False).exists())
        first = self.client.get('/api/v1/risk/assessments/list', {
            'pagination': 'cursor', 'limit': 1, 'sort_by': '-risk_score',
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['pagination']['mode'], 'cursor')
        self.assertTrue(first.data['pagination']['has_next'])
        second = self.client.get('/api/v1/risk/assessments/list', {
            'pagination': 'cursor', 'limit': 1, 'sort_by': '-risk_score',
            'cursor': first.data['pagination']['next_cursor'],
        })
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.data['assessments'][0]['assessment_id'], second.data['assessments'][0]['assessment_id'])
