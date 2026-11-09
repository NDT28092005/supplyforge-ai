"""Regression coverage for outcome-based slow-moving quality gates."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from supplyforge.models import (
    DemandReturnEvent,
    DatasetVersion,
    IntegrationConnection,
    IntegrationOperationalRiskAssessment,
    IntegrationOperationalRiskSnapshot,
    IntegrationSkuDailyMetric,
    IngestionSession,
    Order,
    OrderItem,
    SlowMovingAssessmentRun,
    SlowMovingDispositionEvent,
    SlowMovingOutcomeCohort,
    SlowMovingRiskAssessment,
    User,
    Workspace,
)
from supplyforge.services.slow_moving_outcomes import SlowMovingOutcomeService
from supplyforge.services.slow_moving_candidate_shadow import SlowMovingCandidateShadowService
from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService
from supplyforge.services.slow_moving_run_service import SlowMovingRunService


class SlowMovingOutcomeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='slow-outcome@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='Outcome Workspace', slug='outcome-workspace', owner=self.owner,
        )
        self.other_workspace = Workspace.objects.create(
            name='Other Outcome Workspace', slug='other-outcome-workspace', owner=self.owner,
        )
        self.cutoff = timezone.make_aware(datetime(2026, 1, 1, 23, 59, 59))
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='outcome.csv',
            date_range_start=date(2025, 9, 1),
            date_range_end=date(2026, 4, 15),
            status='COMPLETED',
        )
        self.version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            version_number=1,
            version_label='outcome-v1',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.make_aware(datetime(2026, 4, 15, 23, 59, 59)),
        )
        self.scope = {
            'scope_schema_version': 'slow-moving-source-scope-v2',
            'source_type': 'CSV',
            'workspace_id': self.workspace.id,
            'dataset_version_id': str(self.version.id),
            'source_range_start': '2025-09-01',
            'source_range_end': self.cutoff.date().isoformat(),
            'order_platforms': ['sales_import'],
            'warehouse_scope': 'ALL_VERIFIED_WAREHOUSES',
            'return_handling': 'NET_SALES_MINUS_RETURN_EVENTS',
        }
        self.run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace,
            source_type=SlowMovingAssessmentRun.SOURCE_CSV,
            source_key='CSV',
            dataset_version=self.version,
            analysis_as_of=self.cutoff,
            source_scope=self.scope,
            source_scope_fingerprint=SlowMovingRunService.source_scope_fingerprint(self.scope),
            policy_version='test-policy',
            policy_checksum='a' * 64,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
            summary={'total_skus_considered': 1, 'eligible_skus': 1},
        )

    def _assessment(self, sku='SKU-A', risk_class='HIGH_RISK', opened=False):
        evidence = {
            'stock_quantity': 10,
            'capital_exposure_vnd': 100,
            'inventory_readiness': {'status': 'READY'},
            'alert_opened_this_run': opened,
        }
        return SlowMovingRiskAssessment.objects.create(
            session=self.session,
            assessment_run=self.run,
            sku=sku,
            canonical_sku_id=sku,
            product_name=sku,
            category='CSV',
            risk_class=risk_class,
            risk_score=80,
            evidence=evidence,
            assessment_status='COMPLETE',
            decision_cutoff=self.cutoff.isoformat(),
            model_version='test-policy',
            calibration_version='not_applicable_rule_priority',
            diagnostic_rule_version='test-policy',
            dataset_version='outcome-v1',
        )

    def _future_order(self, workspace, suffix, sku, at, quantity):
        order = Order.objects.create(
            id=f'outcome-order-{suffix}', user_id=str(self.owner.id), workspace=workspace,
            order_id=f'OUTCOME-{suffix}', platform='sales_import', status='COMPLETED',
            is_accounting=True, demand_eligibility_verified=True, source_event_at=at,
            created_at=at,
        )
        OrderItem.objects.create(
            order=order, sku=sku, canonical_sku=sku, product_name=sku, quantity=quantity,
        )

    def _return_event(self, suffix, sku, at, quantity, *, workspace=None):
        return DemandReturnEvent.objects.create(
            workspace=workspace or self.workspace,
            canonical_sku=sku,
            platform='sales_import',
            original_order_id=f'OUTCOME-{suffix}',
            external_return_id=f'RETURN-{suffix}',
            quantity=Decimal(str(quantity)),
            occurred_at=at,
            source_event_key=f'return-event-{suffix}',
            source_lineage_json={'source_type': 'CSV'},
        )

    def _matured_cohort(self, *, run, sku, cutoff, future_units, opening_capital=100):
        return SlowMovingOutcomeCohort.objects.create(
            workspace=self.workspace,
            assessment_run=run,
            source_type=run.source_type,
            source_key=run.source_key,
            source_scope=run.source_scope,
            source_scope_fingerprint=run.source_scope_fingerprint,
            policy_version=run.policy_version,
            policy_checksum=run.policy_checksum,
            source_assessment_key=f'manual:{run.id}:{sku}',
            source_sku=sku,
            canonical_sku=sku,
            decision_cutoff=cutoff,
            predicted_risk_class='HIGH_RISK',
            opened_alert=True,
            opening_stock_quantity=Decimal('10'),
            opening_inventory_verified=True,
            opening_capital_exposure=Decimal(str(opening_capital)),
            outcome_30_ends_at=cutoff + timedelta(days=30),
            outcome_60_ends_at=cutoff + timedelta(days=60),
            outcome_90_ends_at=cutoff + timedelta(days=90),
            maturity_eligible_at=cutoff + timedelta(days=74),
            status=SlowMovingOutcomeCohort.STATUS_MATURED,
            future_net_fulfilled_units_60=Decimal(str(future_units)),
            outcome_60_observed_at=cutoff + timedelta(days=74),
        )

    def test_mature_outcome_uses_future_events_from_the_same_workspace_only(self):
        self._assessment(opened=True)
        SlowMovingOutcomeService.capture_run(self.run)
        # Same owner but another workspace must never turn this cohort into a
        # false negative.
        self._future_order(
            self.other_workspace, 'other', 'SKU-A', self.cutoff + timedelta(days=10), 9,
        )
        result = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=75),
        )
        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        self.assertEqual(result['matured_now'], 1)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_MATURED)
        self.assertEqual(cohort.future_net_fulfilled_units_60, Decimal('0'))

    def test_cutoff_event_and_late_grace_period_are_not_mislabelled(self):
        self._assessment()
        SlowMovingOutcomeService.capture_run(self.run)
        self._future_order(self.workspace, 'cutoff', 'SKU-A', self.cutoff, 4)
        self._future_order(self.workspace, 'future', 'SKU-A', self.cutoff + timedelta(days=2), 3)

        early = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=73),
        )
        self.assertEqual(early['matured_now'], 0)
        final = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )
        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        self.assertEqual(final['matured_now'], 1)
        self.assertEqual(cohort.future_net_fulfilled_units_60, Decimal('3'))

    def test_partial_later_return_reduces_future_net_fulfilled_demand(self):
        self._assessment(opened=True)
        SlowMovingOutcomeService.capture_run(self.run)
        self._future_order(self.workspace, 'sale-before-return', 'SKU-A', self.cutoff + timedelta(days=2), 5)
        self._return_event('partial', 'SKU-A', self.cutoff + timedelta(days=12), 3)

        SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )

        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_MATURED)
        self.assertEqual(cohort.future_net_fulfilled_units_60, Decimal('2'))

    def test_return_event_reduces_historical_net_velocity_without_removing_sale_line(self):
        self._future_order(self.workspace, 'historical-sale', 'SKU-NET', self.cutoff - timedelta(days=8), 10)
        self._return_event('historical-partial', 'SKU-NET', self.cutoff - timedelta(days=3), 4)

        demand = SlowMovingRunService._qualified_demand_by_sku(
            self.workspace.id,
            self.cutoff,
            lookback_days=90,
            accepted_statuses=('COMPLETED', 'SHIPPED'),
            order_platforms=('sales_import',),
        )['SKU-NET']

        self.assertEqual(demand['sold_90d'], 6.0)
        self.assertEqual(demand['sold_30d'], 6.0)
        self.assertEqual(demand['returned_90d'], 4.0)
        self.assertEqual(demand['qualified_order_lines'], 1)

    def test_csv_coverage_gap_blocks_outcome_instead_of_inferring_zero_sales(self):
        self._assessment(opened=True)
        SlowMovingOutcomeService.capture_run(self.run)
        self.session.date_range_end = self.cutoff.date() + timedelta(days=30)
        self.session.save(update_fields=['date_range_end'])
        self.version.status = DatasetVersion.STATUS_SUPERSEDED
        self.version.save(update_fields=['status'])
        later_session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='gap.csv',
            date_range_start=self.cutoff.date() + timedelta(days=40),
            date_range_end=self.cutoff.date() + timedelta(days=75),
            status='COMPLETED',
        )
        DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=later_session,
            parent_version=self.version,
            version_number=2,
            version_label='gap-v2',
            import_type='INCREMENTAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=self.cutoff + timedelta(days=75),
        )

        result = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )
        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        self.assertEqual(result['blocked_now'], 1)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED)
        self.assertEqual(cohort.block_reason, 'OUTCOME_SOURCE_COVERAGE_INCOMPLETE')

    def test_csv_scope_mismatch_blocks_outcome_even_when_later_file_reaches_horizon(self):
        self._assessment(opened=True)
        SlowMovingOutcomeService.capture_run(self.run)
        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        cohort.source_scope = {**cohort.source_scope, 'warehouse_scope': 'WAREHOUSE:ONE'}
        cohort.source_scope_fingerprint = SlowMovingRunService.source_scope_fingerprint(cohort.source_scope)
        cohort.save(update_fields=['source_scope', 'source_scope_fingerprint'])

        result = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )
        cohort.refresh_from_db()
        self.assertEqual(result['blocked_now'], 1)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_DATA_BLOCKED)
        self.assertEqual(cohort.block_reason, 'CSV_OUTCOME_SCOPE_MISMATCH')

    def test_operational_disposition_confounds_outcome_instead_of_counting_it_as_clean_label(self):
        self._assessment(opened=True)
        SlowMovingOutcomeService.capture_run(self.run)
        SlowMovingDispositionEvent.objects.create(
            workspace=self.workspace,
            source_type=self.run.source_type,
            source_key=self.run.source_key,
            source_scope_fingerprint=self.run.source_scope_fingerprint,
            canonical_sku='SKU-A',
            event_type=SlowMovingDispositionEvent.TYPE_STOCK_TRANSFER,
            occurred_at=self.cutoff + timedelta(days=8),
            evidence_reference='warehouse-transfer-1',
            provenance_json={'source': 'merchant-confirmed'},
        )

        result = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )
        cohort = SlowMovingOutcomeCohort.objects.get(assessment__assessment_run=self.run)
        report = SlowMovingQualityMonitoringService.report(
            workspace_id=self.workspace.id, source_key='CSV',
        )

        self.assertEqual(result['confounded_now'], 1)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_CONFOUNDED)
        self.assertEqual(cohort.confounder_types, ['STOCK_TRANSFER'])
        self.assertEqual(report['metrics']['confounded_outcome_count'], 1)
        self.assertEqual(report['metrics']['matured_eligible_skus'], 0)

    def test_capital_weighted_precision_uses_opening_exposure_only(self):
        true_positive = self._matured_cohort(
            run=self.run, sku='CAP-TRUE', cutoff=self.cutoff, future_units=0, opening_capital=100,
        )
        false_positive = self._matured_cohort(
            run=self.run, sku='CAP-FALSE', cutoff=self.cutoff, future_units=10, opening_capital=300,
        )
        from supplyforge.services.slow_moving_quality_policy import load_slow_moving_quality_policy

        policy, _ = load_slow_moving_quality_policy()
        metrics = SlowMovingQualityMonitoringService._metrics([true_positive, false_positive], policy)

        self.assertEqual(metrics['opening_capital_coverage'], 1.0)
        self.assertEqual(metrics['opened_high_risk_capital'], 400.0)
        self.assertEqual(metrics['true_positive_high_risk_capital'], 100.0)
        self.assertEqual(metrics['capital_weighted_high_risk_precision'], 0.25)

    def test_candidate_diagnostics_are_shadow_only_and_slice_metrics_require_declared_sample(self):
        model_true = self._matured_cohort(
            run=self.run, sku='MODEL-TRUE', cutoff=self.cutoff, future_units=0,
        )
        model_false = self._matured_cohort(
            run=self.run, sku='MODEL-FALSE', cutoff=self.cutoff, future_units=10,
        )
        for cohort, risk_class, probability in (
            (model_true, 'HIGH_RISK', 0.9),
            (model_false, 'HIGH_RISK', 0.8),
        ):
            cohort.rule_snapshot_json = {'risk_class': 'HIGH_RISK', 'priority_score': 80}
            cohort.segment_json = {'category': 'CSV', 'channel': 'sales_import', 'warehouse': 'ALL_VERIFIED_WAREHOUSES'}
            cohort.model_diagnostic_json = {
                'status': 'RECORDED', 'serving_state': 'SHADOW',
                'model_version': 'shadow-v1', 'predicted_risk_class': risk_class,
                'calibrated_high_risk_probability': probability,
            }
            cohort.save(update_fields=['rule_snapshot_json', 'segment_json', 'model_diagnostic_json'])

        report = SlowMovingCandidateShadowService.diagnostic_report(
            workspace_id=self.workspace.id, source_key='CSV', minimum_slice_size=2,
        )

        self.assertEqual(report['state'], 'DIAGNOSTIC_ONLY')
        self.assertEqual(report['overall']['sample_size'], 2)
        self.assertEqual(report['overall']['candidate_high_risk_precision'], 0.5)
        self.assertTrue(all(not slice_row['publishable'] for slice_row in report['slices']))

    def test_candidate_shadow_refuses_scope_that_does_not_match_feature_contract(self):
        self.run.source_scope = {**self.scope, 'order_platforms': ['another_channel']}
        self.run.save(update_fields=['source_scope'])

        result = SlowMovingCandidateShadowService.capture_run(str(self.run.id))

        self.assertEqual(result['status'], 'SKIPPED')
        self.assertEqual(result['reason'], 'CHANNEL_SCOPE_FEATURE_CONTRACT_MISMATCH')

    def test_quality_metrics_use_opened_alerts_for_precision_and_all_eligible_for_recall(self):
        self._assessment('SKU-TP', opened=True)
        self._assessment('SKU-FN', risk_class='LOW_RISK', opened=False)
        self.run.summary = {'total_skus_considered': 2, 'eligible_skus': 2}
        self.run.save(update_fields=['summary'])
        SlowMovingOutcomeService.capture_run(self.run)
        self._future_order(self.workspace, 'tp', 'SKU-TP', self.cutoff + timedelta(days=1), 0 + 1)
        self._future_order(self.workspace, 'fn', 'SKU-FN', self.cutoff + timedelta(days=1), 1)
        SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )

        report = SlowMovingQualityMonitoringService.report(
            workspace_id=self.workspace.id, source_key='CSV',
        )
        self.assertEqual(report['metrics']['matured_eligible_skus'], 2)
        self.assertEqual(report['metrics']['opened_high_risk_alert_count'], 1)
        self.assertIsNone(report['metrics']['high_risk_precision'])
        self.assertIsNone(report['metrics']['high_risk_recall'])
        self.assertEqual(report['metrics']['accuracy_visibility'], 'WITHHELD_INSUFFICIENT_EVIDENCE')
        self.assertEqual(report['state'], 'INSUFFICIENT_EVIDENCE')
        self.assertFalse(report['notification']['proactive_notifications_enabled'])
        self.assertEqual(report['notification']['delivery_mode'], 'QUEUE_ONLY')

    def test_wilson_lower_bound_never_claims_precision_with_no_alerts(self):
        self.assertIsNone(SlowMovingQualityMonitoringService.wilson_lower(0, 0, 1.645))
        self.assertLess(
            SlowMovingQualityMonitoringService.wilson_lower(7, 10, 1.645),
            0.7,
        )

    def test_lineage_failure_forces_queue_only_and_disables_notifications(self):
        self.run.source_scope = {**self.scope, 'workspace_id': self.other_workspace.id}
        self.run.save(update_fields=['source_scope'])

        report = SlowMovingQualityMonitoringService.report(
            workspace_id=self.workspace.id, source_key='CSV',
        )

        self.assertEqual(report['state'], 'ROLLBACK_REQUIRED')
        self.assertTrue(report['rollback']['lineage_failure'])
        self.assertTrue(any('WORKSPACE_SCOPE_MISMATCH' in reason for reason in report['lineage_failures']))
        self.assertEqual(report['notification']['delivery_mode'], 'QUEUE_ONLY')
        self.assertFalse(report['notification']['proactive_notifications_enabled'])
        self.assertIn('LINEAGE_INTEGRITY_FAILURE', report['notification']['disabled_reasons'])
        self.assertFalse(SlowMovingQualityMonitoringService.can_send_proactive_notification(
            workspace_id=self.workspace.id, source_key='CSV',
        ))

    def test_two_bad_cohorts_including_wilson_breaches_force_queue_only(self):
        old_cutoff = self.cutoff - timedelta(days=31)
        old_scope = {**self.scope, 'source_range_end': old_cutoff.date().isoformat()}
        old_run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace,
            source_type=SlowMovingAssessmentRun.SOURCE_CSV,
            source_key='CSV',
            dataset_version=self.version,
            analysis_as_of=old_cutoff,
            source_scope=old_scope,
            source_scope_fingerprint=SlowMovingRunService.source_scope_fingerprint(old_scope),
            policy_version='test-policy',
            policy_checksum='a' * 64,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            summary={'total_skus_considered': 20, 'eligible_skus': 20},
        )
        # Each cohort has 70% precision. It meets the point threshold but
        # its one-sided Wilson lower bound remains below 60%, so two such
        # cohorts must still shut off proactive delivery.
        for index in range(20):
            self._matured_cohort(
                run=old_run,
                sku=f'OLD-{index}',
                cutoff=old_cutoff,
                future_units=0 if index < 14 else 6,
            )
            self._matured_cohort(
                run=self.run,
                sku=f'CURRENT-{index}',
                cutoff=self.cutoff,
                future_units=0 if index < 14 else 6,
            )

        report = SlowMovingQualityMonitoringService.report(
            workspace_id=self.workspace.id, source_key='CSV',
        )

        self.assertEqual(report['state'], 'ROLLBACK_REQUIRED')
        self.assertTrue(report['rollback']['repeated_quality_breach'])
        self.assertEqual(report['notification']['delivery_mode'], 'QUEUE_ONLY')
        self.assertFalse(report['notification']['proactive_notifications_enabled'])
        self.assertIn(
            'TWO_CONSECUTIVE_COHORT_QUALITY_BREACHES',
            report['notification']['disabled_reasons'],
        )

    def test_odoo_outcome_uses_net_sales_and_survives_snapshot_replacement(self):
        connection = IntegrationConnection.objects.create(
            workspace=self.workspace, provider='ODOO', display_name='Outcome Odoo',
            status=IntegrationConnection.STATUS_ACTIVE, warehouse_ids=['10'],
        )
        snapshot = IntegrationOperationalRiskSnapshot.objects.create(
            connection=connection, source_data_as_of=self.cutoff.date(), status='READY',
        )
        scope = {
            'scope_schema_version': 'slow-moving-odoo-source-scope-v1',
            'source_type': 'ODOO',
            'workspace_id': self.workspace.id,
            'integration_connection_id': str(connection.id),
            'warehouse_ids': ['10'],
            'sales_metric_warehouse_id': '',
            'return_handling': 'NET_SALES_MINUS_RETURNS',
            'source_range_start': '2025-09-01',
            'source_range_end': self.cutoff.date().isoformat(),
        }
        run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace,
            source_type=SlowMovingAssessmentRun.SOURCE_ODOO,
            source_key=f'ODOO:{connection.id}',
            integration_connection=connection,
            analysis_as_of=self.cutoff,
            source_scope=scope,
            source_scope_fingerprint=SlowMovingQualityMonitoringService._scope_fingerprint(
                scope, SlowMovingAssessmentRun.SOURCE_ODOO,
            ),
            source_snapshot_fingerprint='b' * 64,
            policy_version='odoo_operational_rules_v1',
            policy_checksum='b' * 64,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
            summary={'total_skus_considered': 1, 'eligible_skus': 1},
        )
        assessment = IntegrationOperationalRiskAssessment.objects.create(
            snapshot=snapshot, external_sku='ODOO-OUTCOME', canonical_sku='CAN-OUTCOME',
            product_name='Odoo outcome item', risk_class='HIGH_RISK', risk_score=80,
            evidence={
                'stock_quantity': 10,
                'inventory_readiness': {'status': 'READY'},
                'alert_opened_this_run': True,
            },
        )
        SlowMovingOutcomeService.capture_odoo_run(run, [assessment])
        cohort = SlowMovingOutcomeCohort.objects.get(assessment_run=run)
        self.assertEqual(cohort.source_sku, 'ODOO-OUTCOME')

        metrics = []
        for offset in range(1, 61):
            metric_date = self.cutoff.date() + timedelta(days=offset)
            metrics.extend([
                IntegrationSkuDailyMetric(
                    connection=connection, external_sku='ODOO-OUTCOME', warehouse_id='10',
                    metric_date=metric_date, on_hand_quantity=10,
                ),
                IntegrationSkuDailyMetric(
                    connection=connection, external_sku='ODOO-OUTCOME', warehouse_id='',
                    metric_date=metric_date,
                    sales_quantity=4 if offset == 1 else 0,
                    returned_quantity=2 if offset == 1 else 0,
                ),
            ])
        IntegrationSkuDailyMetric.objects.bulk_create(metrics)
        # A live Odoo refresh deletes this current read-model row. Its frozen
        # cohort must still retain enough source identity to produce an audit.
        assessment.delete()
        cohort.refresh_from_db()
        self.assertIsNone(cohort.integration_assessment)

        result = SlowMovingOutcomeService.mature_outcomes(
            workspace_id=self.workspace.id,
            as_of=self.cutoff + timedelta(days=74),
        )
        cohort.refresh_from_db()
        self.assertEqual(result['matured_now'], 1)
        self.assertEqual(cohort.status, SlowMovingOutcomeCohort.STATUS_MATURED)
        self.assertEqual(cohort.future_net_fulfilled_units_60, Decimal('2'))
        # The source prefix is case-insensitive, while the connection UUID
        # remains canonical. This must not turn a valid Odoo cohort into a
        # false "no run" report.
        report = SlowMovingQualityMonitoringService.report(
            workspace_id=self.workspace.id,
            source_key=f'odoo:{str(connection.id).upper()}',
        )
        self.assertEqual(report['state'], 'INSUFFICIENT_EVIDENCE')
        self.assertFalse(report['notification']['proactive_notifications_enabled'])
