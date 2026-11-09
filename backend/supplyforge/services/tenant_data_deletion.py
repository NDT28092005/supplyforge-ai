"""Tenant-scoped deletion plan.

This service intentionally never calls ``Model.objects.all().delete()``. A
number of early data models predate workspace foreign keys; those are removed
only through users that are currently members of the requested workspace.
"""

import logging

from django.db import transaction

from supplyforge.models import (
    ActionPlanRecord, ArchivedDataSet, BackgroundJob, CapitalExposureAnalysisRecord,
    CopilotAuditLog, CopilotConversation, DataSource, DatasetVersion,
    DecisionRecord, IngestionSession, InsightAnomaly, InventoryRecord,
    ModelVersion, NotificationRecord, Order, Product, RiskExplanationRecord,
    RiskMonitoringRun, Sku, SlowMovingRiskAssessment,
    TenantFeatureSnapshot, TrainingDatasetManifest, Workspace, WorkspaceMember,
)
from supplyforge.models.integration import IntegrationConnection
from supplyforge.services.storage_backend import StorageBackend

logger = logging.getLogger(__name__)


class TenantDataDeletionService:
    """Preview and execute a deletion plan restricted to one workspace."""

    @staticmethod
    def _workspace(workspace_id: int) -> Workspace:
        return Workspace.objects.get(id=workspace_id)

    @classmethod
    def _legacy_user_ids(cls, workspace: Workspace) -> list[str]:
        """Return direct user identities that may own pre-workspace records."""
        member_ids = list(
            WorkspaceMember.objects.filter(workspace=workspace).values_list('user_id', flat=True)
        )
        if workspace.owner_id:
            member_ids.append(workspace.owner_id)
        return sorted({str(user_id) for user_id in member_ids if user_id})

    @classmethod
    def _unambiguous_legacy_user_ids(cls, workspace: Workspace) -> list[str]:
        """Return users whose unscoped legacy facts can belong only here.

        Old product/order rows have no workspace foreign key. If the same user
        is linked to two workspaces, treating those rows as belonging to either
        one would make deletion cross a tenant boundary. Leave them untouched
        for manual migration instead.
        """
        safe_ids: list[str] = []
        for user_id in cls._legacy_user_ids(workspace):
            member_workspace_ids = set(
                WorkspaceMember.objects.filter(user_id=user_id).values_list('workspace_id', flat=True)
            )
            owner_workspace_ids = set(
                Workspace.objects.filter(owner_id=user_id).values_list('id', flat=True)
            )
            if member_workspace_ids | owner_workspace_ids == {workspace.id}:
                safe_ids.append(user_id)
        return safe_ids

    @classmethod
    def _querysets(cls, workspace: Workspace) -> dict[str, object]:
        """Every queryset in this plan has an explicit tenant lineage."""
        legacy_user_ids = cls._legacy_user_ids(workspace)
        unambiguous_legacy_user_ids = cls._unambiguous_legacy_user_ids(workspace)
        return {
            'raw_data_sessions': IngestionSession.objects.filter(workspace=workspace),
            'processed_data_sources': DataSource.objects.filter(workspace=workspace),
            'dataset_versions': DatasetVersion.objects.filter(workspace=workspace),
            'risk_results': SlowMovingRiskAssessment.objects.filter(session__workspace=workspace),
            'risk_explanations': RiskExplanationRecord.objects.filter(session__workspace=workspace),
            'risk_monitoring_runs': RiskMonitoringRun.objects.filter(session__workspace=workspace),
            'capital_exposure_records': CapitalExposureAnalysisRecord.objects.filter(
                merchant_id=f'workspace:{workspace.id}',
            ) | CapitalExposureAnalysisRecord.objects.filter(
                merchant_id__in=unambiguous_legacy_user_ids,
            ),
            'decision_history_records': DecisionRecord.objects.filter(workspace_id=workspace.id),
            'action_plans': ActionPlanRecord.objects.filter(workspace_id=workspace.id),
            'notifications': NotificationRecord.objects.filter(workspace_id=workspace.id),
            'background_jobs': BackgroundJob.objects.filter(workspace=workspace),
            'feature_snapshots': TenantFeatureSnapshot.objects.filter(workspace=workspace),
            'training_manifests': TrainingDatasetManifest.objects.filter(workspace=workspace),
            'model_versions': ModelVersion.objects.filter(workspace=workspace),
            'workspace_skus': Sku.objects.filter(workspace=workspace),
            'inventory_records': InventoryRecord.objects.filter(sku__workspace=workspace),
            # Prefer direct workspace scope. Only include old unscoped rows
            # when their owner cannot belong to another workspace.
            'legacy_products': Product.objects.filter(workspace=workspace)
            | Product.objects.filter(workspace__isnull=True, user_id__in=unambiguous_legacy_user_ids),
            'legacy_orders': Order.objects.filter(workspace=workspace)
            | Order.objects.filter(workspace__isnull=True, user_id__in=unambiguous_legacy_user_ids),
            'archived_datasets': ArchivedDataSet.objects.filter(
                user_id__in=unambiguous_legacy_user_ids,
                snapshot_json__workspace_id=workspace.id,
            ),
            'copilot_conversations': CopilotConversation.objects.filter(
                tenant_id=f'T{workspace.id:03d}',
            ),
            'copilot_audits': CopilotAuditLog.objects.filter(
                tenant_id=f'T{workspace.id:03d}',
            ),
            'insights': InsightAnomaly.objects.filter(workspace=workspace),
            'integration_connections': IntegrationConnection.objects.filter(workspace=workspace),
        }

    @classmethod
    def preview_tenant_data(cls, workspace_id: int) -> dict:
        workspace = cls._workspace(workspace_id)
        querysets = cls._querysets(workspace)
        counts = {name: queryset.count() for name, queryset in querysets.items()}
        counts['raw_data_files'] = sum(
            1
            for session in querysets['raw_data_sessions']
            for path in (session.storage_path, session.raw_storage_path, session.processed_storage_path)
            if path
        )
        return {
            'workspace_id': workspace.id,
            'workspace_slug': workspace.slug,
            'purge_scope': 'WORKSPACE_AND_DIRECT_MEMBER_LINEAGE',
            'purged_counts': counts,
            'report_cache_files': 0,
        }

    @classmethod
    @transaction.atomic
    def purge_tenant_data(cls, workspace_id: int, user_id: int | None = None) -> dict:
        """Delete only resources in this workspace's explicit lineage."""
        workspace = Workspace.objects.select_for_update().get(id=workspace_id)
        querysets = cls._querysets(workspace)
        counts = {name: queryset.count() for name, queryset in querysets.items()}
        storage_paths = [
            path
            for session in querysets['raw_data_sessions']
            for path in (session.storage_path, session.raw_storage_path, session.processed_storage_path)
            if path
        ]

        # Delete parents whose children are intentionally cascaded, then direct
        # workspace records. No model below is accessed through ``all()``.
        for key in (
            'integration_connections', 'copilot_conversations',
            'copilot_audits', 'decision_history_records', 'action_plans',
            'capital_exposure_records', 'risk_explanations', 'risk_monitoring_runs',
            'raw_data_sessions', 'dataset_versions', 'processed_data_sources',
            'feature_snapshots', 'training_manifests', 'model_versions',
            'inventory_records', 'workspace_skus', 'legacy_orders', 'legacy_products',
            'archived_datasets', 'insights', 'notifications', 'background_jobs',
        ):
            querysets[key].delete()

        deleted_files = 0
        for path in set(storage_paths):
            try:
                StorageBackend.delete(path)
                deleted_files += 1
            except Exception:
                # DB deletion remains authoritative. A retention worker can
                # retry object cleanup without ever widening the tenant scope.
                logger.warning('Could not remove scoped tenant object %s', path, exc_info=True)

        counts['raw_data_files'] = deleted_files
        logger.info(
            'Tenant deletion executed workspace_id=%s actor_id=%s counts=%s',
            workspace.id, user_id, counts,
        )
        return {
            'status': 'SUCCESS',
            'message': 'Dữ liệu thuộc workspace đã được xóa theo phạm vi đã xác nhận.',
            'policy': 'TEN-004_WORKSPACE_SCOPED_PURGE_POLICY',
            'workspace_id': workspace.id,
            'purged_counts': counts,
            'report_cache_files': 0,
        }
