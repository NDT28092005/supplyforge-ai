"""Low-cardinality Prometheus metrics for SupplyForge business operations.

The collector reads persisted read models on each Prometheus scrape.  It is
intentionally portfolio-wide: workspace, SKU, customer and request values are
never used as labels, preventing tenant or PII cardinality from entering the
metrics backend.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from django.db.models import Count
from django.utils import timezone
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)


RISK_CLASSES = ('CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK')
PRIORITY_TIERS = ('P1', 'P2', 'P3', 'P4')
NOTIFICATION_SEVERITIES = ('CRITICAL', 'HIGH', 'WARNING', 'INFO')
ACTIONABLE_DECISION_STATUSES = ('GENERATED', 'RECOMMENDED', 'REVIEWED')


class BusinessSnapshotCollector:
    """Export the current portfolio state without relying on worker memory."""

    def describe(self):
        yield GaugeMetricFamily(
            'supplyforge_business_snapshot_up',
            'Whether the latest business snapshot query completed successfully.',
        )
        yield GaugeMetricFamily(
            'supplyforge_business_active_datasets',
            'Number of currently active dataset versions.',
        )
        yield GaugeMetricFamily(
            'supplyforge_business_dataset_freshness_days',
            'Maximum age in days of an active dataset.',
        )
        yield GaugeMetricFamily(
            'supplyforge_business_dataset_quality_score',
            'Quality score of active datasets on the 0-100 scale.',
            labels=['stat'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_portfolio_skus',
            'Current active portfolio SKU count by slow-moving risk class.',
            labels=['risk_class'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_capital_exposure_vnd',
            'Current active portfolio capital exposure in VND.',
            labels=['metric'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_action_backlog_total',
            'Actionable decision backlog by priority tier.',
            labels=['priority_tier'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_unread_notifications_total',
            'Unread business notifications by severity.',
            labels=['severity'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_erp_connections_total',
            'ERP integration connections by lifecycle status.',
            labels=['status'],
        )
        yield GaugeMetricFamily(
            'supplyforge_business_erp_sync_age_seconds',
            'Maximum age in seconds of the last successful active ERP sync.',
        )
        yield GaugeMetricFamily(
            'supplyforge_business_erp_unmapped_skus_total',
            'Total ERP SKUs awaiting a canonical mapping.',
        )

    def collect(self):
        snapshot_up = GaugeMetricFamily(
            'supplyforge_business_snapshot_up',
            'Whether the latest business snapshot query completed successfully.',
        )
        active_datasets = GaugeMetricFamily(
            'supplyforge_business_active_datasets',
            'Number of currently active dataset versions.',
        )
        freshness_days = GaugeMetricFamily(
            'supplyforge_business_dataset_freshness_days',
            'Maximum age in days of an active dataset.',
        )
        quality_score = GaugeMetricFamily(
            'supplyforge_business_dataset_quality_score',
            'Quality score of active datasets on the 0-100 scale.',
            labels=['stat'],
        )
        portfolio_skus = GaugeMetricFamily(
            'supplyforge_business_portfolio_skus',
            'Current active portfolio SKU count by slow-moving risk class.',
            labels=['risk_class'],
        )
        capital_exposure = GaugeMetricFamily(
            'supplyforge_business_capital_exposure_vnd',
            'Current active portfolio capital exposure in VND.',
            labels=['metric'],
        )
        action_backlog = GaugeMetricFamily(
            'supplyforge_business_action_backlog_total',
            'Actionable decision backlog by priority tier.',
            labels=['priority_tier'],
        )
        unread_notifications = GaugeMetricFamily(
            'supplyforge_business_unread_notifications_total',
            'Unread business notifications by severity.',
            labels=['severity'],
        )
        erp_connections = GaugeMetricFamily(
            'supplyforge_business_erp_connections_total',
            'ERP integration connections by lifecycle status.',
            labels=['status'],
        )
        erp_sync_age = GaugeMetricFamily(
            'supplyforge_business_erp_sync_age_seconds',
            'Maximum age in seconds of the last successful active ERP sync.',
        )
        erp_unmapped_skus = GaugeMetricFamily(
            'supplyforge_business_erp_unmapped_skus_total',
            'Total ERP SKUs awaiting a canonical mapping.',
        )

        try:
            # Imports are deferred so Django can build its app registry before
            # Prometheus calls the collector.
            from supplyforge.models import (
                CapitalExposureAnalysisRecord,
                DatasetVersion,
                DecisionRecord,
                NotificationRecord,
                SlowMovingRiskAssessment,
                IntegrationConnection,
                IntegrationSkuMapping,
            )

            versions = list(
                DatasetVersion.objects.filter(
                    status=DatasetVersion.STATUS_ACTIVE,
                ).values(
                    'ingestion_session_id',
                    'workspace_id',
                    'version_label',
                    'data_as_of',
                    'ingestion_session__quality_score',
                )
            )
            active_session_ids = [item['ingestion_session_id'] for item in versions]
            active_workspace_ids = [item['workspace_id'] for item in versions]

            active_datasets.add_metric([], len(versions))
            ages = []
            now = timezone.now()
            quality_scores = []
            for version in versions:
                data_as_of = version['data_as_of']
                score = version['ingestion_session__quality_score']
                if data_as_of:
                    ages.append(max(0.0, (now - data_as_of).total_seconds() / 86400))
                if score is not None:
                    quality_scores.append(float(score))
            freshness_days.add_metric([], max(ages, default=0.0))
            quality_score.add_metric(['average'], sum(quality_scores) / len(quality_scores) if quality_scores else 0.0)
            quality_score.add_metric(['minimum'], min(quality_scores, default=0.0))

            dataset_keys = [f'session:{session_id}' for session_id in active_session_ids]
            capital_rows = list(CapitalExposureAnalysisRecord.objects.filter(
                status='COMPLETED',
                dataset_version__in=dataset_keys,
            ).values(
                'dataset_version',
                'risk_distribution',
                'total_inventory_value',
                'total_risk_weighted_exposure',
                'total_probability_adjusted_exposure',
                'total_opportunity_cost',
            ))
            capital = {
                'total_inventory': sum(row['total_inventory_value'] or 0 for row in capital_rows),
                'risk_weighted': sum(row['total_risk_weighted_exposure'] or 0 for row in capital_rows),
                'probability_adjusted': sum(
                    row['total_probability_adjusted_exposure'] or 0 for row in capital_rows
                ),
                'opportunity_cost': sum(row['total_opportunity_cost'] or 0 for row in capital_rows),
            }
            for metric, value in {
                'inventory_value': capital['total_inventory'],
                'risk_weighted_exposure': capital['risk_weighted'],
                'probability_adjusted_exposure': capital['probability_adjusted'],
                'opportunity_cost': capital['opportunity_cost'],
            }.items():
                capital_exposure.add_metric([metric], float(value or 0.0))

            # The capital analysis is the worker-built aggregate read model. It
            # avoids counting every SKU-level risk row on each metrics scrape.
            risk_counts = defaultdict(int)
            analyzed_dataset_keys = set()
            for analysis in capital_rows:
                analyzed_dataset_keys.add(analysis['dataset_version'])
                for item in analysis['risk_distribution'] or []:
                    risk_class = item.get('group') or item.get('risk_class')
                    if risk_class in RISK_CLASSES:
                        risk_counts[risk_class] += int(item.get('sku_count') or 0)

            # A just-published dataset may not yet have reached the worker that
            # builds capital analysis. Use a scoped fallback only for those
            # incomplete sessions, never a portfolio-wide risk-table scan.
            missing_session_ids = [
                session_id
                for session_id in active_session_ids
                if f'session:{session_id}' not in analyzed_dataset_keys
            ]
            if missing_session_ids:
                for row in (
                    SlowMovingRiskAssessment.objects.filter(session_id__in=missing_session_ids)
                    .values('risk_class')
                    .annotate(total=Count('id'))
                ):
                    risk_counts[row['risk_class']] += row['total']
            for risk_class in RISK_CLASSES:
                portfolio_skus.add_metric([risk_class], risk_counts[risk_class])

            active_versions_by_workspace = defaultdict(set)
            for version in versions:
                active_versions_by_workspace[version['workspace_id']].add(
                    version['version_label']
                )
            backlog_counts = {
                priority_tier: 0 for priority_tier in PRIORITY_TIERS
            }
            # Version labels repeat between workspaces (for example, many
            # tenants have v1.0). Aggregate by workspace/version first, then
            # match the exact active pair in Python instead of cross-matching.
            for row in (
                DecisionRecord.objects.filter(
                    workspace_id__in=active_workspace_ids,
                    status__in=ACTIONABLE_DECISION_STATUSES,
                )
                .values('workspace_id', 'dataset_version', 'priority_tier')
                .annotate(total=Count('id'))
            ):
                if row['dataset_version'] in active_versions_by_workspace[row['workspace_id']]:
                    backlog_counts[row['priority_tier']] = (
                        backlog_counts.get(row['priority_tier'], 0) + row['total']
                    )
            for priority_tier in PRIORITY_TIERS:
                action_backlog.add_metric([priority_tier], backlog_counts.get(priority_tier, 0))

            notification_counts = {
                row['severity']: row['total']
                for row in NotificationRecord.objects.filter(
                    workspace_id__in=active_workspace_ids,
                    is_read=False,
                ).values('severity').annotate(total=Count('id'))
            }
            for severity in NOTIFICATION_SEVERITIES:
                unread_notifications.add_metric([severity], notification_counts.get(severity, 0))

            erp_statuses = ('DRAFT', 'VALIDATING', 'ACTIVE', 'PAUSED', 'ERROR', 'DISCONNECTED')
            erp_counts = {
                row['status']: row['total']
                for row in IntegrationConnection.objects.values('status').annotate(total=Count('id'))
            }
            for integration_status in erp_statuses:
                erp_connections.add_metric([integration_status], erp_counts.get(integration_status, 0))
            last_syncs = list(IntegrationConnection.objects.filter(
                status='ACTIVE',
                last_successful_sync_at__isnull=False,
            ).values_list('last_successful_sync_at', flat=True))
            erp_sync_age.add_metric([], max(
                (max(0.0, (now - value).total_seconds()) for value in last_syncs),
                default=0.0,
            ))
            erp_unmapped_skus.add_metric([], IntegrationSkuMapping.objects.filter(status='NEEDS_REVIEW').count())

            snapshot_up.add_metric([], 1)
        except Exception:
            # A metrics scrape must not make the Django endpoint unavailable.
            logger.exception('Business snapshot metrics collection failed.')
            snapshot_up.add_metric([], 0)
            active_datasets.add_metric([], 0)
            freshness_days.add_metric([], 0)
            quality_score.add_metric(['average'], 0)
            quality_score.add_metric(['minimum'], 0)
            for risk_class in RISK_CLASSES:
                portfolio_skus.add_metric([risk_class], 0)
            for metric in (
                'inventory_value',
                'risk_weighted_exposure',
                'probability_adjusted_exposure',
                'opportunity_cost',
            ):
                capital_exposure.add_metric([metric], 0)
            for priority_tier in PRIORITY_TIERS:
                action_backlog.add_metric([priority_tier], 0)
            for severity in NOTIFICATION_SEVERITIES:
                unread_notifications.add_metric([severity], 0)
            for integration_status in ('DRAFT', 'VALIDATING', 'ACTIVE', 'PAUSED', 'ERROR', 'DISCONNECTED'):
                erp_connections.add_metric([integration_status], 0)
            erp_sync_age.add_metric([], 0)
            erp_unmapped_skus.add_metric([], 0)

        yield snapshot_up
        yield active_datasets
        yield freshness_days
        yield quality_score
        yield portfolio_skus
        yield capital_exposure
        yield action_backlog
        yield unread_notifications
        yield erp_connections
        yield erp_sync_age
        yield erp_unmapped_skus


_REGISTERED = False


def register_business_snapshot_collector() -> None:
    """Register exactly once per process, including Django's development reload."""
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        REGISTRY.register(BusinessSnapshotCollector())
    except ValueError:
        # The parent process may already have registered it before an autoreload.
        logger.debug('Business snapshot collector was already registered.')
    _REGISTERED = True
