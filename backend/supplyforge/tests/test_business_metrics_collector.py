from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from supplyforge.business_metrics_collector import BusinessSnapshotCollector
from supplyforge.models import (
    CapitalExposureAnalysisRecord,
    DatasetVersion,
    DecisionRecord,
    IngestionSession,
    NotificationRecord,
    SlowMovingRiskAssessment,
    User,
    Workspace,
)


class BusinessSnapshotCollectorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create(
            email='business-metrics@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace = Workspace.objects.create(
            name='Business Metrics Workspace',
            slug='business-metrics-workspace',
            owner=self.user,
        )
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='portfolio.csv',
            status='COMPLETED',
            quality_score='87.50',
        )
        self.version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            version_number=1,
            version_label='v2.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now() - timedelta(days=5),
        )

        for sku, risk_class in (
            ('SKU-CRITICAL', 'CRITICAL'),
            ('SKU-HIGH', 'HIGH_RISK'),
            ('SKU-LOW', 'LOW_RISK'),
        ):
            SlowMovingRiskAssessment.objects.create(
                session=self.session,
                sku=sku,
                canonical_sku_id=sku,
                product_name=sku,
                risk_class=risk_class,
                risk_probability=0.8,
                risk_score=80.0,
                dataset_version=self.version.version_label,
            )

        CapitalExposureAnalysisRecord.objects.create(
            analysis_id='business-metrics-analysis',
            merchant_id=f'workspace:{self.workspace.id}',
            dataset_version=f'session:{self.session.id}',
            status='COMPLETED',
            total_inventory_value=1_000_000.0,
            total_risk_weighted_exposure=400_000.0,
            total_probability_adjusted_exposure=300_000.0,
            total_opportunity_cost=50_000.0,
            risk_distribution=[
                {'group': 'CRITICAL', 'sku_count': 1},
                {'group': 'HIGH_RISK', 'sku_count': 1},
                {'group': 'MEDIUM_RISK', 'sku_count': 0},
                {'group': 'LOW_RISK', 'sku_count': 1},
            ],
        )
        # Version labels are scoped to a workspace. This second active v1.0
        # makes sure a stale v1.0 decision in the first workspace is not
        # mistaken for current merely because another workspace uses v1.0.
        other_workspace = Workspace.objects.create(
            name='Other Business Metrics Workspace',
            slug='other-business-metrics-workspace',
            owner=self.user,
        )
        other_session = IngestionSession.objects.create(
            workspace=other_workspace,
            original_filename='other-portfolio.csv',
            status='COMPLETED',
            quality_score='90.00',
        )
        other_version = DatasetVersion.objects.create(
            workspace=other_workspace,
            ingestion_session=other_session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now() - timedelta(days=2),
        )
        CapitalExposureAnalysisRecord.objects.create(
            analysis_id='business-metrics-other-analysis',
            merchant_id=f'workspace:{other_workspace.id}',
            dataset_version=f'session:{other_session.id}',
            status='COMPLETED',
            risk_distribution=[],
        )
        DecisionRecord.objects.create(
            decision_id='business-metrics-current-p1',
            workspace_id=self.workspace.id,
            sku='SKU-CRITICAL',
            dataset_version=self.version.version_label,
            priority_tier='P1',
            status='RECOMMENDED',
        )
        # A completed decision from a superseded dataset must not inflate the
        # current action backlog.
        DecisionRecord.objects.create(
            decision_id='business-metrics-superseded-p1',
            workspace_id=self.workspace.id,
            sku='SKU-OLD',
            dataset_version='v1.0',
            priority_tier='P1',
            status='RECOMMENDED',
        )
        NotificationRecord.objects.create(
            workspace_id=self.workspace.id,
            notification_type=NotificationRecord.TRIGGER_NEW_CRITICAL_SKU,
            title='Critical SKU detected',
            message='One critical SKU needs review.',
            severity=NotificationRecord.SEVERITY_HIGH,
            is_read=False,
        )

    @staticmethod
    def _metric_value(families, metric_name, labels=None):
        labels = labels or {}
        family = next(item for item in families if item.name == metric_name)
        sample = next(
            item for item in family.samples
            if item.labels == labels and item.name == metric_name
        )
        return sample.value

    def test_collector_exports_current_portfolio_only(self):
        families = list(BusinessSnapshotCollector().collect())

        self.assertEqual(
            self._metric_value(families, 'supplyforge_business_snapshot_up'), 1,
        )
        self.assertEqual(
            self._metric_value(families, 'supplyforge_business_active_datasets'), 2,
        )
        self.assertEqual(
            self._metric_value(
                families,
                'supplyforge_business_portfolio_skus',
                {'risk_class': 'CRITICAL'},
            ),
            1,
        )
        self.assertEqual(
            self._metric_value(
                families,
                'supplyforge_business_portfolio_skus',
                {'risk_class': 'MEDIUM_RISK'},
            ),
            0,
        )
        self.assertEqual(
            self._metric_value(
                families,
                'supplyforge_business_capital_exposure_vnd',
                {'metric': 'risk_weighted_exposure'},
            ),
            400_000.0,
        )
        self.assertEqual(
            self._metric_value(
                families,
                'supplyforge_business_action_backlog_total',
                {'priority_tier': 'P1'},
            ),
            1,
        )
        self.assertEqual(
            self._metric_value(
                families,
                'supplyforge_business_unread_notifications_total',
                {'severity': 'HIGH'},
            ),
            1,
        )

    def test_collector_has_no_tenant_or_pii_labels(self):
        forbidden = {'workspace_id', 'workspace', 'sku', 'user_id', 'email', 'request_id'}
        families = list(BusinessSnapshotCollector().collect())
        labels = {
            label
            for family in families
            for sample in family.samples
            for label in sample.labels
        }
        self.assertTrue(forbidden.isdisjoint(labels))

    def test_metrics_endpoint_includes_business_snapshot_metrics(self):
        response = self.client.get('/metrics')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('supplyforge_business_snapshot_up', content)
        self.assertIn('supplyforge_business_portfolio_skus', content)
        self.assertIn('supplyforge_business_capital_exposure_vnd', content)
