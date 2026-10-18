from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import (
    DatasetVersion,
    BackgroundJob,
    IngestionSession,
    ModelVersion,
    Product,
    SlowMovingRiskAssessment,
    TenantFeatureSnapshot,
    User,
    Workspace,
)
from supplyforge.services.mlops_governance import (
    FeatureSnapshotService,
    MLOpsValidationError,
    ModelGovernanceService,
    TrainingDatasetService,
)
from supplyforge.views.auth import generate_access_token


class MLOpsGovernanceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='mlops-owner@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='MLOps Workspace',
            slug='mlops-workspace',
            owner=self.owner,
        )
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='orders.csv',
            status='COMPLETED',
            dataset_version='v1.0',
        )
        self.version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now(),
        )

    def _assessment(self, sku='SKU-1', days_ago=100):
        return SlowMovingRiskAssessment.objects.create(
            session=self.session,
            sku=sku,
            canonical_sku_id=f'C-{sku}',
            product_name=sku,
            risk_class='HIGH_RISK',
            risk_probability=0.8,
            risk_score=80,
            model_version='risk-baseline-v1',
            assessment_timestamp=timezone.now() - timedelta(days=days_ago),
            evidence={
                'sales_velocity_90d': 0.1,
                'dsls': 120,
                'zero_rate_90d': 0.8,
                'stock_quantity': 10,
                'unit_cost': 50,
            },
        )

    def _labeled_snapshot(self, sku='SKU-LABELLED'):
        self._assessment(sku)
        FeatureSnapshotService.materialize_from_assessments(self.version)
        snapshot = TenantFeatureSnapshot.objects.get(workspace=self.workspace, sku_id=sku)
        return FeatureSnapshotService.record_observed_label(
            snapshot,
            risk_level='HIGH_RISK',
            label_source=TenantFeatureSnapshot.LABEL_OPERATIONAL_OUTCOME,
            label_quality=TenantFeatureSnapshot.QUALITY_GOLD,
            observed_at=timezone.now() - timedelta(days=1),
        )

    def _candidate(self, version, manifest=None):
        return ModelGovernanceService.create_candidate(
            self.workspace,
            version=version,
            model_type='XGBClassifier',
            artifact_uri=f'local://models/{version}.joblib',
            artifact_sha256='a' * 64,
            feature_schema_version='risk-features-v1',
            training_manifest=manifest,
            actor=self.owner.email,
        )

    def _promote_healthy_candidate(self, version, manifest=None):
        self._candidate(version, manifest)
        ModelGovernanceService.evaluate_candidate(
            self.workspace,
            version=version,
            metrics={
                'highRiskRecall': 0.9,
                'macroF1': 0.8,
                'ece': 0.04,
                'missingRate': 0.01,
            },
            actor=self.owner.email,
        )
        ModelGovernanceService.approve_for_shadow(
            self.workspace, version=version, actor=self.owner.email
        )
        ModelGovernanceService.record_drift(
            self.workspace,
            version=version,
            drift_status='HEALTHY',
            metrics={'psi': 0.03},
            actor=self.owner.email,
        )
        ModelGovernanceService.start_canary(
            self.workspace, version=version, actor=self.owner.email
        )
        return ModelGovernanceService.promote(
            self.workspace, version=version, actor=self.owner.email, reason='Verified locally'
        )

    def test_feature_snapshots_are_immutable_idempotent_and_unlabeled(self):
        self._assessment('SKU-A')
        self._assessment('SKU-B')

        first = FeatureSnapshotService.materialize_from_assessments(self.version)
        second = FeatureSnapshotService.materialize_from_assessments(self.version)
        snapshots = TenantFeatureSnapshot.objects.filter(workspace=self.workspace)

        self.assertEqual(first['candidateRows'], 2)
        self.assertEqual(second['candidateRows'], 2)
        self.assertEqual(snapshots.count(), 2)
        snapshot = snapshots.get(sku_id='SKU-A')
        self.assertFalse(snapshot.training_eligible)
        self.assertEqual(snapshot.label_source, TenantFeatureSnapshot.LABEL_UNLABELED)
        self.assertEqual(snapshot.source_lineage_json['datasetVersion'], 'v1.0')
        self.assertEqual(snapshot.feature_vector_json['daysSinceLastSale'], 120)

    def test_label_requires_closed_observation_window_and_rejects_heuristic(self):
        self._assessment('SKU-RECENT', days_ago=1)
        FeatureSnapshotService.materialize_from_assessments(self.version)
        recent = TenantFeatureSnapshot.objects.get(sku_id='SKU-RECENT')

        with self.assertRaises(MLOpsValidationError):
            FeatureSnapshotService.record_observed_label(
                recent,
                risk_level='HIGH_RISK',
                label_source=TenantFeatureSnapshot.LABEL_OPERATIONAL_OUTCOME,
                label_quality=TenantFeatureSnapshot.QUALITY_GOLD,
                observed_at=timezone.now(),
            )

        snapshot = self._labeled_snapshot('SKU-PAST')
        with self.assertRaises(MLOpsValidationError):
            FeatureSnapshotService.record_observed_label(
                snapshot,
                risk_level='HIGH_RISK',
                label_source=TenantFeatureSnapshot.LABEL_HEURISTIC,
                label_quality=TenantFeatureSnapshot.QUALITY_GOLD,
                observed_at=timezone.now(),
            )

    def test_training_manifest_freezes_only_observed_non_heuristic_labels(self):
        labelled = self._labeled_snapshot()
        TenantFeatureSnapshot.objects.create(
            workspace=self.workspace,
            session=self.session,
            dataset_version=self.version,
            sku_id='SKU-HEURISTIC',
            snapshot_key='b' * 64,
            feature_vector_json={},
            feature_schema_version='risk-features-v1',
            source_event_time=timezone.now() - timedelta(days=200),
            outcome_observation_ends_at=timezone.now() - timedelta(days=100),
            actual_risk_level='CRITICAL',
            label_source=TenantFeatureSnapshot.LABEL_HEURISTIC,
            label_quality=TenantFeatureSnapshot.QUALITY_GOLD,
            label_observed_at=timezone.now() - timedelta(days=90),
            training_eligible=True,
        )

        manifest = TrainingDatasetService.freeze_manifest(
            self.workspace,
            cutoff_at=timezone.now(),
            feature_schema_version='risk-features-v1',
            include_cross_tenant=False,
            actor=self.owner.email,
        )

        self.assertEqual(manifest.snapshot_count, 1)
        self.assertEqual(manifest.label_distribution_json, {'HIGH_RISK': 1})
        self.assertTrue(manifest.snapshot_checksum.startswith('sha256:'))
        self.assertEqual(manifest.selection_criteria_json['trainingEligible'], True)
        self.assertTrue(labelled.training_eligible)

    def test_cross_tenant_manifest_requires_explicit_opt_in(self):
        self._labeled_snapshot('SKU-LOCAL')
        other = Workspace.objects.create(name='Opt in Workspace', slug='opt-in-workspace')
        other_session = IngestionSession.objects.create(
            workspace=other,
            original_filename='other.csv',
        )
        other_version = DatasetVersion.objects.create(
            workspace=other,
            ingestion_session=other_session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
        )
        TenantFeatureSnapshot.objects.create(
            workspace=other,
            session=other_session,
            dataset_version=other_version,
            sku_id='SKU-OTHER',
            snapshot_key='c' * 64,
            feature_vector_json={},
            feature_schema_version='risk-features-v1',
            source_event_time=timezone.now() - timedelta(days=200),
            outcome_observation_ends_at=timezone.now() - timedelta(days=100),
            actual_risk_level='LOW_RISK',
            label_source=TenantFeatureSnapshot.LABEL_OPERATIONAL_OUTCOME,
            label_quality=TenantFeatureSnapshot.QUALITY_GOLD,
            label_observed_at=timezone.now() - timedelta(days=90),
            label_frozen_at=timezone.now() - timedelta(days=90),
            training_eligible=True,
        )

        with self.assertRaises(MLOpsValidationError):
            TrainingDatasetService.freeze_manifest(
                self.workspace,
                cutoff_at=timezone.now(),
                feature_schema_version='risk-features-v1',
                include_cross_tenant=True,
                actor=self.owner.email,
            )

        self.workspace.training_data_opt_in = True
        self.workspace.save(update_fields=['training_data_opt_in', 'updated_at'])
        other.training_data_opt_in = True
        other.save(update_fields=['training_data_opt_in', 'updated_at'])
        manifest = TrainingDatasetService.freeze_manifest(
            self.workspace,
            cutoff_at=timezone.now(),
            feature_schema_version='risk-features-v1',
            include_cross_tenant=True,
            actor=self.owner.email,
        )
        self.assertEqual(manifest.snapshot_count, 2)
        self.assertTrue(manifest.include_cross_tenant)

    def test_quality_gate_rejection_promotion_and_rollback(self):
        rejected = self._candidate('risk-rejected-v1')
        result = ModelGovernanceService.evaluate_candidate(
            self.workspace,
            version=rejected.version,
            metrics={
                'highRiskRecall': 0.2,
                'macroF1': 0.2,
                'ece': 0.9,
                'missingRate': 0.9,
            },
            actor=self.owner.email,
        )
        self.assertEqual(result.status, 'REJECTED')
        self.assertFalse(result.quality_gate_result_json['passed'])

        first = self._promote_healthy_candidate('risk-v1')
        second = self._promote_healthy_candidate('risk-v2')
        first.refresh_from_db()
        self.assertEqual(first.status, 'RETIRED')
        self.assertEqual(second.status, 'ACTIVE')

        restored = ModelGovernanceService.rollback(
            self.workspace,
            active_version='risk-v2',
            target_version='risk-v1',
            actor=self.owner.email,
            reason='Regression detected',
        )
        second.refresh_from_db()
        self.assertEqual(restored.version, 'risk-v1')
        self.assertEqual(restored.status, 'ACTIVE')
        self.assertEqual(second.status, 'RETIRED')

    def test_ml_worker_materializes_feature_snapshots_after_scoring(self):
        job = BackgroundJob.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            job_type='CSV_IMPORT',
            status='RUNNING',
            stages_json={'ML_INFERENCE': {'status': 'PENDING', 'progress': 0}},
        )
        with patch(
            'supplyforge.views.risk_assessment_api._auto_populate_assessments_from_products'
        ), patch(
            'supplyforge.services.mlops_governance.FeatureSnapshotService.materialize_from_assessments',
            return_value={'completed': True},
        ) as materialize_snapshots, patch(
            'supplyforge.services.lakehouse_ingestion.LakehouseIngestionService.materialize_dashboard_gold',
            return_value={'hasData': False},
        ):
            from supplyforge.tasks import _stage_ml_inference

            context = _stage_ml_inference(job, {'dataset_version_id': str(self.version.id)})

        materialize_snapshots.assert_called_once()
        self.assertEqual(context['feature_snapshot'], {'completed': True})

    def test_governance_api_is_tenant_scoped_and_owner_only(self):
        snapshot = self._labeled_snapshot('SKU-API')
        snapshot.actual_risk_level = None
        snapshot.label_source = TenantFeatureSnapshot.LABEL_UNLABELED
        snapshot.label_quality = TenantFeatureSnapshot.QUALITY_UNLABELED
        snapshot.label_observed_at = None
        snapshot.label_frozen_at = None
        snapshot.training_eligible = False
        snapshot.save()

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=(
                f'Bearer {generate_access_token(self.owner, self.workspace.id)}'
            )
        )
        response = client.post(
            f'/api/v2/ml/governance/snapshots/{snapshot.id}/label',
            {
                'actualRiskLevel': 'HIGH_RISK',
                'labelSource': 'OPERATIONAL_OUTCOME',
                'labelQuality': 'GOLD',
                'labelObservedAt': (timezone.now() - timedelta(days=1)).isoformat(),
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['trainingEligible'])

        viewer = User.objects.create(
            email='mlops-viewer@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_VIEWER,
        )
        client.credentials(
            HTTP_AUTHORIZATION=(
                f'Bearer {generate_access_token(viewer, self.workspace.id)}'
            )
        )
        denied = client.get('/api/v2/ml/governance/models')
        self.assertEqual(denied.status_code, 403)

    def test_auto_scoring_reads_and_replaces_only_the_session_workspace(self):
        other_owner = User.objects.create(
            email='mlops-other-owner@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        other_workspace = Workspace.objects.create(
            name='Other scoring workspace',
            slug='other-scoring-workspace',
            owner=other_owner,
        )
        other_session = IngestionSession.objects.create(
            workspace=other_workspace,
            original_filename='other-orders.csv',
        )
        Product.objects.create(
            id='product-own-000000000001',
            user_id=str(self.owner.id),
            third_party_id='own-product',
            item_sku='SKU-OWN',
            product_name='Own product',
            stock=5,
            cost=10,
        )
        Product.objects.create(
            id='product-other-0000000001',
            user_id=str(other_owner.id),
            third_party_id='other-product',
            item_sku='SKU-OTHER',
            product_name='Other product',
            stock=7,
            cost=10,
        )
        protected = SlowMovingRiskAssessment.objects.create(
            session=other_session,
            sku='SKU-PROTECTED',
            canonical_sku_id='C-PROTECTED',
            product_name='Other assessment',
            risk_class='LOW_RISK',
            risk_probability=0.1,
            risk_score=10,
        )

        from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products

        _auto_populate_assessments_from_products(str(self.session.id))

        self.assertTrue(SlowMovingRiskAssessment.objects.filter(id=protected.id).exists())
        self.assertEqual(
            list(
                SlowMovingRiskAssessment.objects.filter(session=self.session)
                .values_list('sku', flat=True)
            ),
            ['SKU-OWN'],
        )
