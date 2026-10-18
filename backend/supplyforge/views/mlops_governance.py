"""Tenant-scoped manual model governance APIs."""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.models import ModelVersion, TenantFeatureSnapshot, TrainingDatasetManifest, Workspace
from supplyforge.services.mlops_governance import (
    FeatureSnapshotService,
    MLOpsValidationError,
    ModelGovernanceService,
    TrainingDatasetService,
)


def _governance_workspace(request):
    if not (
        getattr(request, 'tenant_context_validated', False)
        and getattr(request, 'workspace_id', None)
    ):
        return None, Response({
            'error': 'Yêu cầu cần Authorization Bearer token.',
            'code': 'UNAUTHENTICATED',
        }, status=status.HTTP_401_UNAUTHORIZED)
    if getattr(request, 'user_role', None) not in {'OWNER', 'ADMIN'}:
        return None, Response({
            'error': 'Chỉ OWNER hoặc ADMIN được quản trị mô hình.',
            'code': 'FORBIDDEN',
        }, status=status.HTTP_403_FORBIDDEN)
    try:
        return Workspace.objects.get(id=request.workspace_id), None
    except Workspace.DoesNotExist:
        return None, Response({
            'error': 'Workspace không tồn tại.',
            'code': 'WORKSPACE_NOT_FOUND',
        }, status=status.HTTP_404_NOT_FOUND)


def _actor(request) -> str:
    return str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))


def _parse_datetime(value, field_name: str):
    parsed = parse_datetime(str(value or ''))
    if parsed is None:
        raise MLOpsValidationError(f'{field_name} must be an ISO-8601 datetime.')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _model_payload(model: ModelVersion) -> dict:
    return {
        'version': model.version,
        'modelType': model.model_type,
        'status': model.status,
        'artifactUri': model.artifact_uri or model.artifact_dir,
        'artifactSha256': model.artifact_sha256,
        'featureSchemaVersion': model.feature_schema_version,
        'trainingManifestId': str(model.training_manifest_id) if model.training_manifest_id else None,
        'isCrossTenantTraining': model.is_cross_tenant_training,
        'metrics': model.evaluation_metrics_json or {},
        'qualityGate': model.quality_gate_result_json or {},
        'driftStatus': model.drift_status,
        'driftMetrics': model.drift_metrics_json or {},
        'approvedBy': model.approved_by,
        'approvedAt': model.approved_at.isoformat() if model.approved_at else None,
        'activatedAt': model.activated_at.isoformat() if model.activated_at else None,
        'rollbackTarget': model.rollback_target.version if model.rollback_target else None,
        'audit': model.governance_audit_json or [],
        'createdAt': model.created_at.isoformat(),
        'updatedAt': model.updated_at.isoformat(),
    }


def _manifest_payload(manifest: TrainingDatasetManifest) -> dict:
    return {
        'id': str(manifest.id),
        'status': manifest.status,
        'cutoffAt': manifest.cutoff_at.isoformat(),
        'frozenAt': manifest.frozen_at.isoformat(),
        'featureSchemaVersion': manifest.feature_schema_version,
        'includeCrossTenant': manifest.include_cross_tenant,
        'snapshotCount': manifest.snapshot_count,
        'labelDistribution': manifest.label_distribution_json or {},
        'selectionCriteria': manifest.selection_criteria_json or {},
        'snapshotChecksum': manifest.snapshot_checksum,
        'createdAt': manifest.created_at.isoformat(),
    }


@api_view(['GET', 'POST'])
def model_candidates(request):
    workspace, error = _governance_workspace(request)
    if error:
        return error

    if request.method == 'GET':
        models = ModelVersion.objects.filter(workspace=workspace).select_related(
            'training_manifest', 'rollback_target'
        ).order_by('-created_at')[:100]
        return Response({'models': [_model_payload(model) for model in models]})

    manifest = None
    manifest_id = request.data.get('trainingManifestId')
    if manifest_id:
        try:
            manifest = TrainingDatasetManifest.objects.get(id=manifest_id, workspace=workspace)
        except (TrainingDatasetManifest.DoesNotExist, ValueError):
            return Response({'error': 'Training manifest không tồn tại.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        model = ModelGovernanceService.create_candidate(
            workspace,
            version=request.data.get('version', ''),
            model_type=request.data.get('modelType', ''),
            artifact_uri=request.data.get('artifactUri', ''),
            artifact_sha256=request.data.get('artifactSha256', ''),
            feature_schema_version=request.data.get('featureSchemaVersion', ''),
            training_manifest=manifest,
            actor=_actor(request),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model), status=status.HTTP_201_CREATED)


@api_view(['POST'])
def evaluate_model_candidate(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.evaluate_candidate(
            workspace,
            version=version,
            metrics=request.data.get('metrics') or {},
            actor=_actor(request),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['POST'])
def approve_model_candidate(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.approve_for_shadow(
            workspace, version=version, actor=_actor(request)
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['POST'])
def record_model_drift(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.record_drift(
            workspace,
            version=version,
            drift_status=request.data.get('driftStatus'),
            metrics=request.data.get('metrics') or {},
            actor=_actor(request),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['POST'])
def start_model_canary(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.start_canary(
            workspace, version=version, actor=_actor(request)
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['POST'])
def promote_model_candidate(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.promote(
            workspace,
            version=version,
            actor=_actor(request),
            reason=request.data.get('reason', ''),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['POST'])
def rollback_model_candidate(request, version):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        model = ModelGovernanceService.rollback(
            workspace,
            active_version=version,
            target_version=request.data.get('targetVersion', ''),
            actor=_actor(request),
            reason=request.data.get('reason', ''),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_model_payload(model))


@api_view(['GET', 'POST'])
def training_manifests(request):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    if request.method == 'GET':
        manifests = TrainingDatasetManifest.objects.filter(workspace=workspace).order_by('-created_at')[:100]
        return Response({'manifests': [_manifest_payload(manifest) for manifest in manifests]})
    try:
        include_cross_tenant = request.data.get('includeCrossTenant', False)
        if not isinstance(include_cross_tenant, bool):
            raise MLOpsValidationError('includeCrossTenant phải là boolean.')
        manifest = TrainingDatasetService.freeze_manifest(
            workspace,
            cutoff_at=_parse_datetime(request.data.get('cutoffAt'), 'cutoffAt'),
            feature_schema_version=request.data.get(
                'featureSchemaVersion', FeatureSnapshotService.FEATURE_SCHEMA_VERSION
            ),
            include_cross_tenant=include_cross_tenant,
            actor=_actor(request),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_manifest_payload(manifest), status=status.HTTP_201_CREATED)


@api_view(['POST'])
def label_feature_snapshot(request, snapshot_id):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    try:
        snapshot = TenantFeatureSnapshot.objects.get(id=snapshot_id, workspace=workspace)
    except TenantFeatureSnapshot.DoesNotExist:
        return Response({'error': 'Feature snapshot không tồn tại.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        snapshot = FeatureSnapshotService.record_observed_label(
            snapshot,
            risk_level=request.data.get('actualRiskLevel'),
            label_source=request.data.get('labelSource'),
            label_quality=request.data.get('labelQuality'),
            observed_at=_parse_datetime(request.data.get('labelObservedAt'), 'labelObservedAt'),
        )
    except MLOpsValidationError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({
        'id': snapshot.id,
        'trainingEligible': snapshot.training_eligible,
        'labelSource': snapshot.label_source,
        'labelQuality': snapshot.label_quality,
        'labelObservedAt': snapshot.label_observed_at.isoformat(),
    })


@api_view(['POST'])
def set_training_data_opt_in(request):
    workspace, error = _governance_workspace(request)
    if error:
        return error
    enabled = request.data.get('enabled')
    if not isinstance(enabled, bool):
        return Response({'error': 'enabled phải là boolean.'}, status=status.HTTP_400_BAD_REQUEST)
    workspace.training_data_opt_in = enabled
    workspace.save(update_fields=['training_data_opt_in', 'updated_at'])
    return Response({'trainingDataOptIn': workspace.training_data_opt_in})
