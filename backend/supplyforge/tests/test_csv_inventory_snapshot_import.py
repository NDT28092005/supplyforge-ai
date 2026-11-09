"""Regression coverage for the explicit CSV inventory-evidence contract."""

import io
from datetime import date

from django.test import TestCase

from supplyforge.models import (
    DecisionRecord,
    DemandReturnEvent,
    IngestionSession,
    InventoryRecord,
    Product,
    Sku,
    SlowMovingRiskAssessment,
    User,
    Workspace,
)
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.services.inventory_readiness import InventoryReadinessGate
from supplyforge.services.capital_exposure_service import CapitalExposureAnalysisService
from supplyforge.services.auto_decision_generator import AutoDecisionGeneratorService
from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products


class CsvInventorySnapshotImportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='csv-inventory-owner@example.test',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='CSV inventory evidence workspace',
            slug='csv-inventory-evidence-workspace',
            owner=self.owner,
        )

    def test_explicit_snapshot_is_available_to_the_capital_gate(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='happy-path.csv',
            ingestion_id='IMP-HAPPY-PATH-001',
        )
        csv_payload = (
            'order_id,item_sku,product_name,quantity,price,cost,stock,order_date,'
            'inventory_as_of_date,inventory_snapshot_id,warehouse_code,lifecycle_status\n'
            'ORD-1,SKU-HAPPY-1,Happy SKU,2,150000,100000,80,2026-10-20,'
            '2026-10-29,CSV-HAPPY-20261029-SKU-HAPPY-1,WH-CENTRAL,ACTIVE\n'
            'ORD-2,SKU-HAPPY-1,Happy SKU,1,150000,100000,80,2026-10-29,'
            '2026-10-29,CSV-HAPPY-20261029-SKU-HAPPY-1,WH-CENTRAL,ACTIVE\n'
        )

        result = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )

        self.assertEqual(result['rows_valid'], 2)
        self.assertEqual(result['inventory_snapshots_created'], 1)
        self.assertEqual(result['inventory_snapshot_incomplete_skus'], 0)

        record = InventoryRecord.objects.get(canonical_sku='SKU-HAPPY-1')
        self.assertEqual(record.warehouse_code, 'WH-CENTRAL')
        self.assertTrue(record.as_of_verified)
        self.assertEqual(record.source_lineage_json['source_type'], 'CSV_EXPLICIT_INVENTORY_SNAPSHOT')

        readiness = InventoryReadinessGate.evaluate(
            workspace_id=self.workspace.id,
            canonical_sku='SKU-HAPPY-1',
            as_of=date(2026, 10, 29),
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.capital_exposure, 8_000_000.0)

    def test_stock_column_without_snapshot_contract_is_not_promoted(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='orders-only.csv',
        )
        csv_payload = (
            'order_id,item_sku,product_name,quantity,price,cost,stock,order_date\n'
            'ORD-1,SKU-ORDERS-ONLY,Orders only,1,150000,100000,80,2026-10-29\n'
        )

        result = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )

        self.assertEqual(result['rows_valid'], 1)
        self.assertEqual(result['inventory_snapshots_created'], 0)
        self.assertFalse(InventoryRecord.objects.filter(canonical_sku='SKU-ORDERS-ONLY').exists())

    def test_partial_return_is_stored_as_a_net_demand_event_not_a_sale_order(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='sales-and-returns.csv',
            ingestion_id='IMP-RETURN-EVENT-001',
        )
        csv_payload = (
            'order_id,item_sku,product_name,quantity,return_quantity,return_id,price,cost,order_date,order_status,not_calculate_money,warehouse\n'
            'ORD-RETURN-1,SKU-RETURN,Returnable SKU,5,,,150000,100000,2026-10-01,COMPLETED,false,WH-CENTRAL\n'
            'ORD-RETURN-1,SKU-RETURN,Returnable SKU,5,2,RET-RETURN-1,0,0,2026-10-08,RETURNED,false,WH-CENTRAL\n'
        )

        result = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )

        self.assertEqual(result['new_rows'], 1)
        self.assertEqual(result['return_events_received'], 1)
        event = DemandReturnEvent.objects.get(workspace=self.workspace, canonical_sku='SKU-RETURN')
        self.assertEqual(event.quantity, 2)
        self.assertEqual(event.external_return_id, 'RET-RETURN-1')

    def test_readiness_aggregates_latest_evidence_from_all_warehouses(self):
        sku = Sku.objects.create(
            workspace=self.workspace,
            original_name='Multi warehouse SKU',
            normalized_name='SKU-MULTI-WH',
        )
        for warehouse, quantity, cost in (
            ('WH-CENTRAL', 10, 100_000),
            ('WH-SOUTH', 5, 120_000),
        ):
            InventoryRecord.objects.create(
                sku=sku,
                canonical_sku='SKU-MULTI-WH',
                warehouse_code=warehouse,
                record_date=date(2026, 10, 29),
                quantity=quantity,
                available_quantity=quantity,
                cost_price=cost,
                selling_price=150_000,
                lifecycle_status='ACTIVE',
                as_of_verified=True,
                source_snapshot_id=f'CSV-MULTI-{warehouse}',
            )

        readiness = InventoryReadinessGate.evaluate(
            workspace_id=self.workspace.id,
            canonical_sku='SKU-MULTI-WH',
            as_of=date(2026, 10, 29),
        )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.warehouse_count, 2)
        self.assertEqual(readiness.available_quantity, 15.0)
        self.assertEqual(readiness.capital_exposure, 1_600_000.0)
        self.assertIsNone(readiness.unit_cost)
        self.assertEqual(readiness.unit_selling_price, 150_000.0)

    def test_capital_analysis_preserves_verified_multi_warehouse_total(self):
        """A differing warehouse cost must not turn verified capital into zero."""
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='multi-warehouse.csv',
            status='COMPLETED',
        )
        sku = Sku.objects.create(
            workspace=self.workspace,
            original_name='Multi warehouse capital SKU',
            normalized_name='SKU-MULTI-CAPITAL',
        )
        for warehouse, quantity, cost in (
            ('WH-CENTRAL', 10, 100_000),
            ('WH-SOUTH', 5, 120_000),
        ):
            InventoryRecord.objects.create(
                sku=sku,
                canonical_sku='SKU-MULTI-CAPITAL',
                warehouse_code=warehouse,
                record_date=date(2026, 10, 29),
                quantity=quantity,
                available_quantity=quantity,
                cost_price=cost,
                selling_price=150_000,
                lifecycle_status='ACTIVE',
                as_of_verified=True,
                source_snapshot_id=f'CSV-MULTI-CAPITAL-{warehouse}',
            )

        readiness = InventoryReadinessGate.evaluate(
            workspace_id=self.workspace.id,
            canonical_sku='SKU-MULTI-CAPITAL',
            as_of=date(2026, 10, 29),
        )
        SlowMovingRiskAssessment.objects.create(
            session=session,
            sku='SKU-MULTI-CAPITAL',
            canonical_sku_id='CSKU-MULTI-CAPITAL',
            product_name='Multi warehouse capital SKU',
            risk_class='HIGH_RISK',
            risk_probability=0.8,
            risk_score=80,
            evidence={
                'stock_quantity': readiness.available_quantity,
                'unit_cost': readiness.unit_cost,
                'capital_exposure_vnd': readiness.capital_exposure,
                'dsls': 120,
                'inventory_readiness': {
                    'status': readiness.status,
                    'record_date': readiness.record_date.isoformat(),
                    'warehouse_count': readiness.warehouse_count,
                },
            },
        )

        analysis = CapitalExposureAnalysisService.ensure_current_analysis(self.workspace.id)

        self.assertIsNotNone(analysis)
        item = analysis.items.get(sku='SKU-MULTI-CAPITAL')
        self.assertEqual(item.capital_exposure, 1_600_000)

    def test_mutable_product_stock_cannot_seed_financial_decision(self):
        assessment = SlowMovingRiskAssessment(
            sku='SKU-NO-SNAPSHOT',
            product_name='No inventory evidence',
            risk_class='CRITICAL',
            risk_probability=0.9,
            risk_score=90,
            evidence={
                'stock_quantity': 80,
                'unit_cost': 100_000,
                'unit_price': 150_000,
                'capital_exposure_vnd': 8_000_000,
                'sales_velocity_30d': 1,
                'inventory_readiness': {'status': 'INVENTORY_UNAVAILABLE'},
            },
        )
        product = Product(
            id='product-no-snapshot',
            user_id=str(self.owner.id),
            third_party_id='product-no-snapshot',
            item_sku='SKU-NO-SNAPSHOT',
            stock=80,
            cost=100_000,
            price=150_000,
        )

        context = AutoDecisionGeneratorService._decision_context(assessment, product)

        self.assertFalse(context['input_readiness']['inventory_observed'])
        self.assertFalse(context['input_readiness']['financial_inputs_complete'])
        self.assertIsNone(context['stock_on_hand'])
        self.assertIsNone(context['unit_cost'])
        self.assertIsNone(context['unit_price'])
        self.assertEqual(context['decision_status'], 'NOT_READY')

    def test_clear_retires_csv_snapshot_and_allows_same_file_to_be_imported_again(self):
        """Clearing an operational CSV must not fail on its inventory evidence."""
        first_session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='reloadable.csv',
            ingestion_id='IMP-RELOADABLE-001',
        )
        csv_payload = (
            'order_id,item_sku,product_name,quantity,price,cost,stock,order_date,'
            'inventory_as_of_date,inventory_snapshot_id,warehouse_code,lifecycle_status\n'
            'ORD-RELOAD-1,SKU-RELOAD,Reloadable SKU,2,150000,100000,80,2026-10-20,'
            '2026-10-29,CSV-RELOAD-20261029,WH-CENTRAL,ACTIVE\n'
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=first_session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )

        DynamicFileImportService.clear_data(
            str(self.owner.id),
            workspace_id=self.workspace.id,
        )

        self.assertFalse(InventoryRecord.objects.filter(
            canonical_sku='SKU-RELOAD',
            source_lineage_json__source_type='CSV_EXPLICIT_INVENTORY_SNAPSHOT',
        ).exists())

        second_session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='reloadable.csv',
            ingestion_id='IMP-RELOADABLE-002',
        )
        result = DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=second_session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )
        self.assertEqual(result['rows_valid'], 1)
        self.assertEqual(InventoryRecord.objects.filter(canonical_sku='SKU-RELOAD').count(), 1)

    def test_ready_snapshot_requires_a_current_operational_alert_before_decisioning(self):
        session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='decision-happy-path.csv',
            ingestion_id='IMP-DECISION-HAPPY-001',
        )
        csv_payload = (
            'order_id,item_sku,product_name,quantity,price,cost,stock,order_date,'
            'inventory_as_of_date,inventory_snapshot_id,warehouse_code,lifecycle_status\n'
            # This SKU has no sale in the latest 90 days but carries material stock.
            'ORD-OLD-1,SKU-CRITICAL-READY,Critical ready SKU,1,250000,150000,160,2026-07-01,'
            '2026-10-29,CSV-HAPPY-CRITICAL,WH-CENTRAL,ACTIVE\n'
            # This row defines the portfolio reference date used by the assessment.
            'ORD-RECENT-1,SKU-HEALTHY,Healthy SKU,4,90000,50000,20,2026-10-29,'
            '2026-10-29,CSV-HAPPY-HEALTHY,WH-CENTRAL,ACTIVE\n'
        )
        DynamicFileImportService.process_batch_import(
            io.BytesIO(csv_payload.encode('utf-8')),
            {},
            str(self.owner.id),
            session_id=session.id,
            workspace_id=self.workspace.id,
            run_post_import_hooks=False,
        )

        _auto_populate_assessments_from_products(str(session.id))

        assessment = SlowMovingRiskAssessment.objects.get(session=session, sku='SKU-CRITICAL-READY')
        self.assertEqual(
            assessment.evidence['inventory_readiness']['status'],
            'READY',
            {
                'records': list(InventoryRecord.objects.values('canonical_sku', 'record_date', 'warehouse_code', 'sku__workspace_id')),
                'workspace': self.workspace.id,
                'evidence': assessment.evidence,
            },
        )
        # The legacy/session-bound helper remains available for research and
        # backfill compatibility, but it cannot mint a merchant-facing action
        # merely because its stock snapshot is complete.  The production path
        # must publish a current `SlowMovingAssessmentRun` and open/acknowledge
        # its alert first; `AutoDecisionGeneratorService` enforces both gates.
        self.assertIsNone(assessment.assessment_run_id)
        self.assertFalse(
            DecisionRecord.objects.filter(
                workspace_id=self.workspace.id,
                sku='SKU-CRITICAL-READY',
            ).exists()
        )
