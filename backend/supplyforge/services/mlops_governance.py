"""Local-first MLOps lineage, training selection, and model governance."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from supplyforge.models import (
    DatasetVersion,
    ModelVersion,
    SlowMovingRiskAssessment,
    TenantFeatureSnapshot,
    TrainingDatasetManifest,
    Workspace,
)


class MLOpsValidationError(ValueError):
    """Raised when a lineage, quality, or state-transition rule is violated."""


class FeatureSnapshotService:
    """Persists immutable scoring features without treating predictions as labels."""

    FEATURE_SCHEMA_VERSION = 'risk-features-v1'
    TRAINING_LABEL_SOURCES = {
        TenantFeatureSnapshot.LABEL_OPERATIONAL_OUTCOME,
        TenantFeatureSnapshot.LABEL_FROZEN_GROUND_TRUTH,
        TenantFeatureSnapshot.LABEL_EXPERT_ANNOTATION,
        TenantFeatureSnapshot.LABEL_MERCHANT_FEEDBACK,
    }
    TRAINING_LABEL_QUALITIES = {
        TenantFeatureSnapshot.QUALITY_GOLD,
        TenantFeatureSnapshot.QUALITY_SILVER,
    }

    @staticmethod
    def _event_time(assessment) -> object:
        event_time = assessment.assessment_timestamp or timezone.now()
        if timezone.is_naive(event_time):
            return timezone.make_aware(event_time)
        return event_time

    @staticmethod
    def _feature_vector(assessment) -> dict:
        evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
        return {
            'riskProbability': assessment.risk_probability,
            'riskScore': assessment.risk_score,
            'salesVelocity90d': evidence.get('sales_velocity_90d', 0),
            'salesVelocity30d': evidence.get('sales_velocity_30d', 0),
            'zeroRate90d': evidence.get('zero_rate_90d', 0),
            'daysSinceLastSale': evidence.get('dsls', 0),
            'adi': evidence.get('adi', 0),
            'cv2': evidence.get('cv2', 0),
            'sold90d': evidence.get('sold_90d', 0),
            'sold30d': evidence.get('sold_30d', 0),
            'stockQuantity': evidence.get('stock_quantity', 0),
            'unitCost': evidence.get('unit_cost', 0),
        }

    @classmethod
    def materialize_from_assessments(cls, version: DatasetVersion) -> dict:
        """Create idempotent snapshots in bounded batches for one dataset version."""
        if version.ingestion_session_id is None:
            raise MLOpsValidationError('Dataset version is missing its ingestion session.')

        batch_size = settings.MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE
        rows_seen = 0
        batch = []
        assessments = (
            SlowMovingRiskAssessment.objects
            .filter(session_id=version.ingestion_session_id)
            .only(
                'id', 'sku', 'risk_probability', 'risk_score', 'model_version',
                'evidence', 'assessment_timestamp',
            )
            .iterator(chunk_size=batch_size)
        )

        def flush() -> None:
            if not batch:
                return
            TenantFeatureSnapshot.objects.bulk_create(
                batch,
                batch_size=batch_size,
                ignore_conflicts=True,
            )
            batch.clear()

        for assessment in assessments:
            rows_seen += 1
            event_time = cls._event_time(assessment)
            model_version = assessment.model_version or ''
            snapshot_key = hashlib.sha256(
                (
                    f'{version.id}:{assessment.id}:{cls.FEATURE_SCHEMA_VERSION}:'
                    f'{model_version}'
                ).encode('utf-8')
            ).hexdigest()
            batch.append(TenantFeatureSnapshot(
                workspace_id=version.workspace_id,
                dataset_version=version,
                session_id=version.ingestion_session_id,
                sku_id=assessment.sku,
                snapshot_key=snapshot_key,
                feature_vector_json=cls._feature_vector(assessment),
                feature_schema_version=cls.FEATURE_SCHEMA_VERSION,
                model_version=model_version,
                source_event_time=event_time,
                outcome_observation_ends_at=(
                    event_time + timedelta(days=settings.MLOPS_LABEL_OBSERVATION_DAYS)
                ),
                source_lineage_json={
                    'datasetVersion': version.version_label,
                    'datasetVersionId': str(version.id),
                    'ingestionSessionId': str(version.ingestion_session_id),
                    'riskAssessmentId': str(assessment.id),
                },
            ))
            if len(batch) >= batch_size:
                flush()
        flush()

        manifest = dict(version.manifest_json or {})
        manifest['featureSnapshots'] = {
            'completed': True,
            'featureSchemaVersion': cls.FEATURE_SCHEMA_VERSION,
            'candidateRows': rows_seen,
            'labelObservationDays': settings.MLOPS_LABEL_OBSERVATION_DAYS,
            'materializedAt': timezone.now().isoformat(),
        }
        version.manifest_json = manifest
        version.save(update_fields=['manifest_json', 'updated_at'])
        return manifest['featureSnapshots']

    @classmethod
    def record_observed_label(
        cls,
        snapshot: TenantFeatureSnapshot,
        *,
        risk_level: str,
        label_source: str,
        label_quality: str,
        observed_at,
    ) -> TenantFeatureSnapshot:
        """Freeze a real outcome only after its observation window closes."""
        risk_level = str(risk_level or '').strip().upper()
        if risk_level not in {'CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK'}:
            raise MLOpsValidationError('actualRiskLevel is invalid.')
        if label_source not in cls.TRAINING_LABEL_SOURCES:
            raise MLOpsValidationError('Heuristic labels cannot be used for training.')
        if label_quality not in cls.TRAINING_LABEL_QUALITIES:
            raise MLOpsValidationError('Only GOLD or SILVER labels are training eligible.')
        if timezone.is_naive(observed_at):
            observed_at = timezone.make_aware(observed_at)
        if observed_at > timezone.now():
            raise MLOpsValidationError('labelObservedAt cannot be in the future.')
        if (
            snapshot.outcome_observation_ends_at
            and observed_at < snapshot.outcome_observation_ends_at
        ):
            raise MLOpsValidationError(
                'Outcome observation window has not closed for this snapshot.'
            )
        if snapshot.label_frozen_at:
            raise MLOpsValidationError('This snapshot label is already frozen.')

        snapshot.actual_risk_level = risk_level
        snapshot.label_source = label_source
        snapshot.label_quality = label_quality
        snapshot.label_observed_at = observed_at
        snapshot.label_frozen_at = timezone.now()
        snapshot.training_eligible = True
        snapshot.save(update_fields=[
            'actual_risk_level', 'label_source', 'label_quality',
            'label_observed_at', 'label_frozen_at', 'training_eligible', 'computed_at',
        ])
        return snapshot


class TrainingDatasetService:
    """Builds reproducible, leakage-safe training selections from frozen labels."""

    @classmethod
    def _eligible_snapshots(
        cls,
        workspace: Workspace,
        *,
        cutoff_at,
        frozen_at,
        feature_schema_version: str,
        include_cross_tenant: bool,
    ):
        if timezone.is_naive(cutoff_at):
            cutoff_at = timezone.make_aware(cutoff_at)
        if include_cross_tenant:
            if not workspace.training_data_opt_in:
                raise MLOpsValidationError(
                    'Workspace must opt in before requesting cross-tenant training data.'
                )
            source_workspace_ids = Workspace.objects.filter(
                training_data_opt_in=True,
            ).values('id')
        else:
            source_workspace_ids = [workspace.id]

        return TenantFeatureSnapshot.objects.filter(
            workspace_id__in=source_workspace_ids,
            feature_schema_version=feature_schema_version,
            training_eligible=True,
            label_source__in=FeatureSnapshotService.TRAINING_LABEL_SOURCES,
            label_quality__in=FeatureSnapshotService.TRAINING_LABEL_QUALITIES,
            source_event_time__lte=cutoff_at,
            outcome_observation_ends_at__lte=cutoff_at,
            label_observed_at__lte=cutoff_at,
            captured_at__lte=frozen_at,
            actual_risk_level__isnull=False,
        )

    @classmethod
    def freeze_manifest(
        cls,
        workspace: Workspace,
        *,
        cutoff_at,
        feature_schema_version: str,
        include_cross_tenant: bool,
        actor: str,
    ) -> TrainingDatasetManifest:
        if not feature_schema_version:
            raise MLOpsValidationError('featureSchemaVersion is required.')
        if timezone.is_naive(cutoff_at):
            cutoff_at = timezone.make_aware(cutoff_at)
        if cutoff_at > timezone.now():
            raise MLOpsValidationError('cutoffAt cannot be in the future.')

        with transaction.atomic():
            frozen_at = timezone.now()
            snapshots = cls._eligible_snapshots(
                workspace,
                cutoff_at=cutoff_at,
                frozen_at=frozen_at,
                feature_schema_version=feature_schema_version,
                include_cross_tenant=include_cross_tenant,
            )
            digest = hashlib.sha256()
            distribution = Counter()
            count = 0
            for snapshot_key, risk_level in snapshots.order_by('snapshot_key').values_list(
                'snapshot_key', 'actual_risk_level'
            ).iterator(chunk_size=settings.MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE):
                digest.update(f'{snapshot_key}:{risk_level}\n'.encode('utf-8'))
                distribution[risk_level] += 1
                count += 1
            if not count:
                raise MLOpsValidationError(
                    'No observed labels satisfy the requested cutoff and schema.'
                )

            return TrainingDatasetManifest.objects.create(
                workspace=workspace,
                cutoff_at=cutoff_at,
                frozen_at=frozen_at,
                feature_schema_version=feature_schema_version,
                include_cross_tenant=include_cross_tenant,
                snapshot_count=count,
                label_distribution_json=dict(sorted(distribution.items())),
                selection_criteria_json={
                    'capturedAtLte': frozen_at.isoformat(),
                    'cutoffAt': cutoff_at.isoformat(),
                    'labelSources': sorted(FeatureSnapshotService.TRAINING_LABEL_SOURCES),
                    'labelQualities': sorted(FeatureSnapshotService.TRAINING_LABEL_QUALITIES),
                    'trainingEligible': True,
                },
                snapshot_checksum=f'sha256:{digest.hexdigest()}',
                created_by=(actor or '')[:128],
            )


class ModelGovernanceService:
    """Explicit quality gates and manual promotion transitions for model versions."""

    DRIFT_STATUSES = {'UNKNOWN', 'HEALTHY', 'ALERT'}

    @staticmethod
    def _metric(metrics: dict, *keys: str) -> float | None:
        for key in keys:
            value = metrics.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _append_audit(model: ModelVersion, action: str, actor: str, **detail) -> None:
        audit = list(model.governance_audit_json or [])[-99:]
        audit.append({
            'at': timezone.now().isoformat(),
            'action': action,
            'actor': (actor or '')[:128],
            **detail,
        })
        model.governance_audit_json = audit

    @classmethod
    def _locked_model(cls, workspace: Workspace, version: str) -> ModelVersion:
        try:
            return ModelVersion.objects.select_for_update().get(
                workspace=workspace,
                version=version,
            )
        except ModelVersion.DoesNotExist as exc:
            raise MLOpsValidationError('Model version was not found in this workspace.') from exc

    @classmethod
    def create_candidate(
        cls,
        workspace: Workspace,
        *,
        version: str,
        model_type: str,
        artifact_uri: str,
        artifact_sha256: str,
        feature_schema_version: str,
        training_manifest: TrainingDatasetManifest | None,
        actor: str,
    ) -> ModelVersion:
        if not version or not model_type or not artifact_uri or not feature_schema_version:
            raise MLOpsValidationError('version, modelType, artifactUri, and featureSchemaVersion are required.')
        if ModelVersion.objects.filter(version=version).exists():
            raise MLOpsValidationError('Model version already exists.')
        if not re.fullmatch(r'[a-fA-F0-9]{64}', artifact_sha256 or ''):
            raise MLOpsValidationError('artifactSha256 must be a SHA-256 hex digest.')
        if training_manifest and training_manifest.workspace_id != workspace.id:
            raise MLOpsValidationError('Training manifest does not belong to this workspace.')

        model = ModelVersion.objects.create(
            workspace=workspace,
            version=version,
            model_type=model_type,
            artifact_dir=artifact_uri,
            artifact_uri=artifact_uri,
            artifact_sha256=artifact_sha256.lower(),
            feature_schema_version=feature_schema_version,
            training_manifest=training_manifest,
            training_dataset_version=(str(training_manifest.id) if training_manifest else ''),
            dataset_manifest_json={
                'trainingManifestId': str(training_manifest.id) if training_manifest else None,
                'snapshotChecksum': training_manifest.snapshot_checksum if training_manifest else None,
            },
            is_cross_tenant_training=bool(
                training_manifest and training_manifest.include_cross_tenant
            ),
            status='EVALUATING',
        )
        cls._append_audit(model, 'CANDIDATE_REGISTERED', actor)
        model.save(update_fields=['governance_audit_json', 'updated_at'])
        return model

    @classmethod
    def evaluate_candidate(
        cls,
        workspace: Workspace,
        *,
        version: str,
        metrics: dict,
        actor: str,
    ) -> ModelVersion:
        with transaction.atomic():
            model = cls._locked_model(workspace, version)
            if model.status not in {'TRAINING', 'EVALUATING', 'REGRESSION_GATE'}:
                raise MLOpsValidationError('Only a candidate under evaluation can pass the quality gate.')

            recall = cls._metric(metrics, 'highRiskRecall', 'high_risk_recall')
            macro_f1 = cls._metric(metrics, 'macroF1', 'macro_f1')
            ece = cls._metric(metrics, 'ece')
            missing_rate = cls._metric(metrics, 'missingRate', 'missing_rate')
            required = {
                'highRiskRecall': recall,
                'macroF1': macro_f1,
                'ece': ece,
                'missingRate': missing_rate,
            }
            missing = [key for key, value in required.items() if value is None]
            if missing:
                raise MLOpsValidationError(f'Missing or invalid evaluation metrics: {", ".join(missing)}.')
            if any(value < 0 or value > 1 for value in required.values()):
                raise MLOpsValidationError('Evaluation metrics must be between 0 and 1.')

            active = ModelVersion.objects.filter(
                workspace=workspace,
                model_type=model.model_type,
                status='ACTIVE',
            ).order_by('-activated_at').first()
            checks = {
                'highRiskRecall': recall >= settings.MLOPS_MIN_HIGH_RISK_RECALL,
                'macroF1': macro_f1 >= settings.MLOPS_MIN_MACRO_F1,
                'calibration': ece <= settings.MLOPS_MAX_ECE,
                'missingData': missing_rate <= settings.MLOPS_MAX_MISSING_RATE,
            }
            if active and active.high_risk_recall is not None:
                checks['recallRegression'] = recall >= (
                    active.high_risk_recall - settings.MLOPS_MAX_METRIC_REGRESSION
                )
            if active and active.macro_f1 is not None:
                checks['macroF1Regression'] = macro_f1 >= (
                    active.macro_f1 - settings.MLOPS_MAX_METRIC_REGRESSION
                )
            passed = all(checks.values())
            gate = {
                'passed': passed,
                'checks': checks,
                'thresholds': {
                    'minHighRiskRecall': settings.MLOPS_MIN_HIGH_RISK_RECALL,
                    'minMacroF1': settings.MLOPS_MIN_MACRO_F1,
                    'maxEce': settings.MLOPS_MAX_ECE,
                    'maxMissingRate': settings.MLOPS_MAX_MISSING_RATE,
                    'maxRegression': settings.MLOPS_MAX_METRIC_REGRESSION,
                },
                'activeBaseline': active.version if active else None,
            }
            model.high_risk_recall = recall
            model.macro_f1 = macro_f1
            model.ece = ece
            model.evaluation_metrics_json = dict(metrics)
            model.quality_gate_result_json = gate
            model.promotion_gate_result_json = gate
            model.status = 'PROMOTION_REVIEW' if passed else 'REJECTED'
            if not passed:
                model.rejected_by = (actor or '')[:128]
                model.rejected_at = timezone.now()
            cls._append_audit(
                model,
                'QUALITY_GATE_PASSED' if passed else 'QUALITY_GATE_REJECTED',
                actor,
                checks=checks,
            )
            model.save()
            return model

    @classmethod
    def approve_for_shadow(cls, workspace: Workspace, *, version: str, actor: str) -> ModelVersion:
        with transaction.atomic():
            model = cls._locked_model(workspace, version)
            if model.status != 'PROMOTION_REVIEW':
                raise MLOpsValidationError('Only a gate-passed candidate can be approved for shadow mode.')
            model.status = 'SHADOW'
            model.approved_by = (actor or '')[:128]
            model.approved_at = timezone.now()
            model.shadow_started_at = timezone.now()
            cls._append_audit(model, 'APPROVED_FOR_SHADOW', actor)
            model.save()
            return model

    @classmethod
    def record_drift(
        cls,
        workspace: Workspace,
        *,
        version: str,
        drift_status: str,
        metrics: dict,
        actor: str,
    ) -> ModelVersion:
        normalized = str(drift_status or '').upper()
        if normalized not in cls.DRIFT_STATUSES:
            raise MLOpsValidationError('driftStatus must be UNKNOWN, HEALTHY, or ALERT.')
        with transaction.atomic():
            model = cls._locked_model(workspace, version)
            if model.status not in {'SHADOW', 'CANARY'}:
                raise MLOpsValidationError('Drift can only be recorded for SHADOW or CANARY models.')
            model.drift_status = normalized
            model.drift_metrics_json = dict(metrics or {})
            cls._append_audit(model, 'DRIFT_RECORDED', actor, driftStatus=normalized)
            model.save()
            return model

    @classmethod
    def start_canary(cls, workspace: Workspace, *, version: str, actor: str) -> ModelVersion:
        with transaction.atomic():
            model = cls._locked_model(workspace, version)
            if model.status != 'SHADOW' or model.drift_status != 'HEALTHY':
                raise MLOpsValidationError('A SHADOW model with healthy drift status is required for canary.')
            model.status = 'CANARY'
            model.canary_started_at = timezone.now()
            cls._append_audit(model, 'CANARY_STARTED', actor)
            model.save()
            return model

    @classmethod
    def promote(cls, workspace: Workspace, *, version: str, actor: str, reason: str = '') -> ModelVersion:
        with transaction.atomic():
            model = cls._locked_model(workspace, version)
            if model.status != 'CANARY' or model.drift_status != 'HEALTHY':
                raise MLOpsValidationError('Only a healthy CANARY model can be promoted.')
            active_models = list(ModelVersion.objects.select_for_update().filter(
                workspace=workspace,
                model_type=model.model_type,
                status='ACTIVE',
            ))
            now = timezone.now()
            for active in active_models:
                active.status = 'RETIRED'
                active.retired_at = now
                cls._append_audit(active, 'RETIRED_BY_PROMOTION', actor, replacement=model.version)
                active.save()
            model.status = 'ACTIVE'
            model.activated_at = now
            model.promoted_by = (actor or '')[:128]
            model.promotion_reason = (reason or '')[:1000]
            model.rollback_target = active_models[0] if active_models else None
            cls._append_audit(model, 'PROMOTED_ACTIVE', actor, reason=(reason or '')[:512])
            model.save()
            return model

    @classmethod
    def rollback(
        cls,
        workspace: Workspace,
        *,
        active_version: str,
        target_version: str,
        actor: str,
        reason: str = '',
    ) -> ModelVersion:
        with transaction.atomic():
            active = cls._locked_model(workspace, active_version)
            target = cls._locked_model(workspace, target_version)
            if active.status != 'ACTIVE' or target.status != 'RETIRED':
                raise MLOpsValidationError('Rollback requires an ACTIVE model and a RETIRED target.')
            if active.model_type != target.model_type:
                raise MLOpsValidationError('Rollback target must have the same model type.')
            now = timezone.now()
            active.status = 'RETIRED'
            active.retired_at = now
            active.rollback_target = target
            cls._append_audit(active, 'ROLLED_BACK', actor, target=target.version, reason=(reason or '')[:512])
            active.save()
            target.status = 'ACTIVE'
            target.activated_at = now
            cls._append_audit(target, 'ROLLBACK_RESTORED_ACTIVE', actor, source=active.version)
            target.save()
            return target
