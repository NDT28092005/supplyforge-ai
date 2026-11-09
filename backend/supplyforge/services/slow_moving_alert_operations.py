"""Feedback follow-up and merchant-facing health read model for slow-moving alerts."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from supplyforge.models import (
    SlowMovingAlertAttentionEvent,
    SlowMovingAlertDigestDelivery,
    SlowMovingAlertFeedback,
    SlowMovingAlertState,
    SlowMovingAssessmentRun,
    SlowMovingFeedbackRemediation,
)
from supplyforge.services.slow_moving_alert_trust import SlowMovingAlertAttentionPolicy


class SlowMovingFeedbackRemediationService:
    """Makes merchant feedback visible work without feeding it into scoring."""

    REASON_DETAILS = {
        SlowMovingAlertFeedback.REASON_DATA_INCORRECT: (
            SlowMovingFeedbackRemediation.TYPE_DATA,
            'Xác minh số liệu bán, tồn kho hoặc hàng trả',
            'Kiểm tra dữ liệu nguồn trước khi dùng cảnh báo này để ra quyết định.',
        ),
        SlowMovingAlertFeedback.REASON_STOCK_MOVED: (
            SlowMovingFeedbackRemediation.TYPE_DATA,
            'Xác minh tồn kho đã được chuyển hoặc điều chỉnh',
            'Đối soát kho, phiếu chuyển và ảnh chụp tồn kho mới nhất.',
        ),
        SlowMovingAlertFeedback.REASON_MAPPING_ISSUE: (
            SlowMovingFeedbackRemediation.TYPE_DATA,
            'Kiểm tra liên kết SKU, kho hoặc kênh bán',
            'Xác nhận SKU và kho trong nguồn dữ liệu đang đúng phạm vi.',
        ),
        SlowMovingAlertFeedback.REASON_SEASONAL: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận sản phẩm theo mùa',
            'Bổ sung thời gian bán theo mùa và ngày cần xem lại.',
        ),
        SlowMovingAlertFeedback.REASON_REPLACEMENT_SKU: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận SKU thay thế',
            'Xác nhận SKU thay thế và quy tắc theo dõi tồn kho liên quan.',
        ),
        SlowMovingAlertFeedback.REASON_DISPLAY_STOCK: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận hàng trưng bày hoặc không bán được',
            'Cập nhật trạng thái hàng để cảnh báo sau không coi đây là tồn có thể bán.',
        ),
        SlowMovingAlertFeedback.REASON_BUNDLE_COMPONENT: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận quan hệ gói hàng hoặc linh kiện',
            'Khai báo SKU liên quan và quy tắc quy đổi trước khi đánh giá lại.',
        ),
        SlowMovingAlertFeedback.REASON_NON_SELLABLE_STOCK: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận tồn kho chưa thể bán',
            'Xác nhận hàng giữ chỗ, hỏng hoặc đang kiểm kê theo từng kho.',
        ),
        SlowMovingAlertFeedback.REASON_PREORDER_OR_CONSIGNMENT: (
            SlowMovingFeedbackRemediation.TYPE_CATALOG,
            'Xác nhận hàng đặt trước hoặc ký gửi',
            'Cập nhật trạng thái hàng và phạm vi theo dõi phù hợp.',
        ),
        SlowMovingAlertFeedback.REASON_PLANNED_CAMPAIGN: (
            SlowMovingFeedbackRemediation.TYPE_OPERATIONS,
            'Theo dõi chương trình bán đã lên lịch',
            'Ghi ngày chạy chương trình và ngày kiểm tra lại sau khi có số liệu.',
        ),
    }

    @classmethod
    def create_from_feedback(
        cls, feedback: SlowMovingAlertFeedback, *, owner_label: str = '',
    ) -> SlowMovingFeedbackRemediation | None:
        details = cls.REASON_DETAILS.get(feedback.reason)
        if not details:
            return None
        remediation_type, title, detail = details
        policy, _ = SlowMovingAlertAttentionPolicy.load()
        due_at = timezone.now() + timedelta(days=int(policy['feedback_remediation_due_days']))
        # A newer feedback event for the same currently open reason should be
        # safe to retry and should not create a queue full of duplicates.
        open_key = f'{feedback.workspace_id}:{feedback.alert_state_id}:{feedback.reason}:open'
        remediation, created = SlowMovingFeedbackRemediation.objects.get_or_create(
            open_key=open_key,
            defaults={
                'workspace_id': feedback.workspace_id,
                'alert_state_id': feedback.alert_state_id,
                'feedback': feedback,
                'remediation_type': remediation_type,
                'title': title,
                'detail': detail,
                'owner_label': owner_label[:128],
                'due_at': due_at,
                'evidence_reference': feedback.evidence_reference,
            },
        )
        if not created and remediation.status in {
            SlowMovingFeedbackRemediation.STATUS_COMPLETED,
            SlowMovingFeedbackRemediation.STATUS_CANCELLED,
        }:
            # An old closed item must never be overwritten. A fresh feedback
            # opens a new accountable item under a time-stamped key.
            remediation = SlowMovingFeedbackRemediation.objects.create(
                workspace_id=feedback.workspace_id,
                alert_state_id=feedback.alert_state_id,
                feedback=feedback,
                open_key=f'{open_key}:{feedback.id}',
                remediation_type=remediation_type,
                title=title,
                detail=detail,
                owner_label=owner_label[:128],
                due_at=due_at,
                evidence_reference=feedback.evidence_reference,
            )
        return remediation


class SlowMovingAlertDigestService:
    """Prepare one concise in-app review digest per assigned owner and day.

    This service deliberately does *not* send email, Slack or Zalo.  Those
    channels require consent and a provider-specific delivery contract.  The
    ledger gives the in-app queue an idempotent hand-off and leaves unassigned
    alerts in the team queue rather than guessing a recipient.
    """

    @classmethod
    def prepare_in_app_digests(
        cls, *, workspace_id: int, source_key: str = 'CSV', delivery_date: date | None = None,
    ) -> dict[str, int]:
        policy, _ = SlowMovingAlertAttentionPolicy.load()
        day = delivery_date or timezone.localdate()
        start = timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())
        end = start + timedelta(days=1)
        max_items = int(policy['digest_max_items'])
        due_alerts = SlowMovingAlertState.objects.filter(
            workspace_id=workspace_id,
            source_key=source_key,
            status__in=[
                SlowMovingAlertState.STATUS_OPEN,
                SlowMovingAlertState.STATUS_ACKNOWLEDGED,
            ],
        ).filter(
            Q(last_detected_at__gte=start, last_detected_at__lt=end)
            | Q(next_review_at__lte=end)
        )
        unassigned_count = due_alerts.filter(owner_label='').count()
        due_alerts = due_alerts.exclude(owner_label='')
        owners = due_alerts.order_by().values_list('owner_label', flat=True).distinct()
        created = existing = included_alerts = 0
        for owner_label in owners.iterator(chunk_size=500):
            alerts = list(
                due_alerts.filter(owner_label=owner_label)
                .order_by('next_review_at', '-last_detected_at', 'canonical_sku')
                .values_list('id', flat=True)[:max_items]
            )
            if not alerts:
                continue
            owner_digest = __import__('hashlib').sha256(
                str(owner_label).encode('utf-8')
            ).hexdigest()[:24]
            delivery, was_created = SlowMovingAlertDigestDelivery.objects.get_or_create(
                idempotency_key=f'in-app:{workspace_id}:{source_key}:{day.isoformat()}:{owner_digest}',
                defaults={
                    'workspace_id': workspace_id,
                    'source_key': source_key,
                    'owner_label': owner_label,
                    'delivery_date': day,
                    'status': SlowMovingAlertDigestDelivery.STATUS_QUEUED,
                    'alert_ids_json': [str(alert_id) for alert_id in alerts],
                },
            )
            created += int(was_created)
            existing += int(not was_created)
            included_alerts += len(delivery.alert_ids_json or [])
        return {
            'delivery_date': day.isoformat(),
            'digests_created': created,
            'digests_existing': existing,
            'alerts_in_digests': included_alerts,
            'unassigned_alerts_stay_in_team_queue': unassigned_count,
        }

    @staticmethod
    def complete(
        remediation: SlowMovingFeedbackRemediation, *, actor: str,
        outcome_note: str, evidence_reference: str = '', cancelled: bool = False,
    ) -> SlowMovingFeedbackRemediation:
        if not outcome_note.strip():
            raise ValueError('Cần nêu kết quả hoặc lý do không thực hiện.')
        remediation.status = (
            SlowMovingFeedbackRemediation.STATUS_CANCELLED
            if cancelled else SlowMovingFeedbackRemediation.STATUS_COMPLETED
        )
        remediation.outcome_note = outcome_note.strip()[:800]
        remediation.evidence_reference = (evidence_reference or remediation.evidence_reference)[:512]
        remediation.completed_by = actor[:128]
        remediation.completed_at = timezone.now()
        remediation.save(update_fields=[
            'status', 'outcome_note', 'evidence_reference', 'completed_by',
            'completed_at', 'updated_at',
        ])
        return remediation


class SlowMovingAlertHealthService:
    """A plain-language operational view, separate from quality mathematics."""

    @classmethod
    def report(cls, *, workspace_id: int, source_key: str = 'CSV') -> dict[str, Any]:
        current_run = SlowMovingAssessmentRun.objects.filter(
            workspace_id=workspace_id,
            source_key=source_key,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
        ).order_by('-completed_at').first()
        now = timezone.now()
        alerts = SlowMovingAlertState.objects.filter(
            workspace_id=workspace_id, source_key=source_key,
        )
        visible = alerts.exclude(status=SlowMovingAlertState.STATUS_RESOLVED)
        by_status = {
            row['status']: row['total']
            for row in alerts.values('status').annotate(total=Count('id'))
        }
        needs_owner = visible.filter(owner_label='').count()
        overdue_review = visible.filter(next_review_at__lt=now).count()
        reopened_since = now - timedelta(days=30)
        reopened = SlowMovingAlertAttentionEvent.objects.filter(
            workspace_id=workspace_id,
            alert_state__source_key=source_key,
            event_type=SlowMovingAlertAttentionEvent.TYPE_REOPENED,
            created_at__gte=reopened_since,
        ).count()
        # A lead looking at one source must not see workload generated by a
        # different CSV import or Odoo connection. The alert is the immutable
        # source link for a remediation item.
        remediations = SlowMovingFeedbackRemediation.objects.filter(
            workspace_id=workspace_id,
            alert_state__source_key=source_key,
        )
        remediation_status = {
            row['status']: row['total']
            for row in remediations.values('status').annotate(total=Count('id'))
        }
        overdue_remediations = remediations.filter(
            status__in=[
                SlowMovingFeedbackRemediation.STATUS_OPEN,
                SlowMovingFeedbackRemediation.STATUS_IN_PROGRESS,
            ],
            due_at__lt=now,
        ).count()
        blocker_counts = Counter()
        if current_run:
            blocker_counts.update((current_run.summary or {}).get('eligibility_status_counts') or {})
        freshness = (current_run.source_freshness or {}) if current_run else {}
        quality: dict[str, Any] = {'state': 'INSUFFICIENT_EVIDENCE'}
        try:
            from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService
            quality = SlowMovingQualityMonitoringService.report(
                workspace_id=workspace_id, source_key=source_key,
            )
        except Exception:
            quality = {'state': 'QUALITY_UNAVAILABLE'}
        return {
            'source_key': source_key,
            'source': {
                'has_current_run': bool(current_run),
                'data_as_of': current_run.analysis_as_of.isoformat() if current_run else None,
                'completed_at': current_run.completed_at.isoformat() if current_run and current_run.completed_at else None,
                'freshness': freshness,
            },
            'alerts': {
                'total_active': visible.count(),
                'by_status': by_status,
                'needs_owner': needs_owner,
                'overdue_review': overdue_review,
                'reopened_last_30_days': reopened,
            },
            'data_blockers': dict(sorted(blocker_counts.items())),
            'remediation': {
                'by_status': remediation_status,
                'overdue': overdue_remediations,
            },
            # The UI deliberately displays this as evidence availability, not
            # an accuracy score. Detailed metrics remain in the quality view.
            'outcome_evidence': {
                'state': quality.get('state'),
                'matured_eligible_skus': (quality.get('metrics') or {}).get('matured_eligible_skus'),
                'pending_outcome_count': (quality.get('metrics') or {}).get('pending_outcome_count'),
                'blocked_outcome_count': (quality.get('metrics') or {}).get('blocked_outcome_count'),
                'confounded_outcome_count': (quality.get('metrics') or {}).get('confounded_outcome_count'),
            },
        }
