"""Plain-language data and merchant-feedback summary for Decision Center."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.db.models import Count

from supplyforge.models.decision import DecisionAuditEventRecord, DecisionRecord
from supplyforge.models.action_plan import ActionPlanEventRecord, ActionPlanRecord


class DecisionTrustReportService:
    """Report only persisted facts; never infer whether a decision was right."""

    FEEDBACK_LABELS = {
        'ALREADY_HAS_PLAN': 'Đã có phương án xử lý khác',
        'DATA_DOES_NOT_MATCH': 'Dữ liệu thực tế chưa khớp',
        'KEEP_PRICE_OR_STOCK': 'Cần giữ giá hoặc giữ hàng',
        'SUPPLIER_OR_PO_LOCKED': 'PO hoặc nhà cung cấp chưa thể thay đổi',
        'TIMING_NOT_RIGHT': 'Chưa đúng thời điểm',
        'OTHER': 'Lý do khác',
    }
    RECENT_FEEDBACK_LIMIT = 1_000
    OVERRIDE_LABELS = {
        'OWN_PLAN': 'Đã có kế hoạch xử lý phù hợp hơn',
        'STOCK_OR_PRICE_CHANGED': 'Tồn kho hoặc mức giá thực tế đã thay đổi',
        'SUPPLIER_CONSTRAINT': 'Điều kiện nhà cung cấp hoặc PO không cho phép',
        'SEASONAL_OR_STRATEGIC': 'Cần giữ hàng hoặc giữ giá theo kế hoạch kinh doanh',
        'OTHER': 'Lý do khác',
    }

    @classmethod
    def _current(cls, workspace_id: int):
        return DecisionRecord.objects.filter(
            workspace_id=workspace_id,
            assessment_run__status='COMPLETED',
            assessment_run__is_current=True,
        ).exclude(status='SUPERSEDED')

    @classmethod
    def build(cls, *, workspace_id: int) -> dict[str, Any]:
        current = cls._current(workspace_id)
        total = current.count()
        ready = current.filter(evidence_state='READY').count()
        needs_data = current.filter(evidence_state='DATA_NEEDED').count()
        source_check = max(0, total - ready - needs_data)
        if not total:
            state = 'NO_CURRENT_DATA'
            title = 'Chưa có dữ liệu đánh giá hiện hành'
            message = 'Nạp hoặc làm mới dữ liệu bán hàng và tồn kho trước khi dùng hàng chờ quyết định.'
        elif needs_data or source_check:
            state = 'CHECK_DATA'
            title = 'Cần kiểm tra dữ liệu trước khi áp dụng một số phương án'
            message = 'Các SKU thiếu dữ liệu vẫn được hiển thị để bổ sung, nhưng không nên dùng số kịch bản để ra quyết định.'
        else:
            state = 'READY_FOR_REVIEW'
            title = 'Dữ liệu hiện có đủ để rà soát phương án'
            message = 'Vẫn cần người phụ trách kiểm tra phạm vi kho, kênh và điều kiện thực tế trước khi triển khai.'

        since = timezone.now() - timedelta(days=90)
        events = DecisionAuditEventRecord.objects.filter(
            decision__workspace_id=workspace_id,
            event_type='DECISION_REJECTED',
            timestamp__gte=since,
        ).order_by('-timestamp').values_list('metadata', flat=True)[:cls.RECENT_FEEDBACK_LIMIT]
        feedback = Counter()
        sampled = 0
        for metadata in events:
            sampled += 1
            payload = metadata if isinstance(metadata, dict) else {}
            merchant_feedback = payload.get('merchant_feedback') if isinstance(payload.get('merchant_feedback'), dict) else {}
            reason = str(merchant_feedback.get('reason') or '').upper()
            if reason in cls.FEEDBACK_LABELS:
                feedback[reason] += 1
        feedback_items = [
            {'label': cls.FEEDBACK_LABELS[reason], 'count': count}
            for reason, count in feedback.most_common(4)
        ]
        override_rows = ActionPlanRecord.objects.filter(
            workspace_id=workspace_id,
            strategy_override_reason_code__gt='',
            created_at__gte=since,
        ).values('strategy_override_reason_code').annotate(count=Count('plan_id')).order_by('-count', 'strategy_override_reason_code')[:4]
        for row in override_rows:
            label = cls.OVERRIDE_LABELS.get(str(row['strategy_override_reason_code']), '')
            if label:
                feedback_items.append({'label': label, 'count': int(row['count'])})
        return {
            'version': 'DECISION_DATA_STATUS_V1',
            'state': state,
            'title': title,
            'message': message,
            'counts': {
                'current_decisions': total,
                'ready_for_review': ready,
                'needs_data': needs_data,
                'needs_source_check': source_check,
            },
            'merchant_feedback': {
                'period_days': 90,
                'sampled_rejections': sampled,
                'plan_changes_recorded': sum(int(row['count']) for row in override_rows),
                'items': feedback_items,
                'message': (
                    'Các lý do merchant đã ghi nhận khi chưa chọn gợi ý. Dùng để cải thiện cách làm và dữ liệu, không dùng để đánh giá đúng/sai tự động.'
                    if feedback_items else 'Chưa có đủ lý do merchant ghi nhận trong 90 ngày gần đây.'
                ),
            },
            'boundary': 'Tình trạng này cho biết dữ liệu có đủ để rà soát hay không; không phải cam kết về doanh số hoặc kết quả tài chính.',
        }

    @classmethod
    def learning_report(cls, *, workspace_id: int, days: int = 7) -> dict[str, Any]:
        """Summarise operational friction, never learn policy from sparse feedback."""
        days = max(1, min(int(days), 90))
        since = timezone.now() - timedelta(days=days)
        feedback = Counter()
        feedback_events = DecisionAuditEventRecord.objects.filter(
            decision__workspace_id=workspace_id,
            event_type='DECISION_REJECTED',
            timestamp__gte=since,
        ).values_list('metadata', flat=True)
        feedback_total = 0
        for metadata in feedback_events.iterator(chunk_size=500):
            value = metadata if isinstance(metadata, dict) else {}
            merchant = value.get('merchant_feedback') if isinstance(value.get('merchant_feedback'), dict) else {}
            reason = str(merchant.get('reason') or '').upper()
            if reason in cls.FEEDBACK_LABELS:
                feedback[reason] += 1
                feedback_total += 1

        overrides = Counter()
        plans = ActionPlanRecord.objects.filter(workspace_id=workspace_id, created_at__gte=since)
        for code in plans.exclude(strategy_override_reason_code='').values_list('strategy_override_reason_code', flat=True):
            if str(code) in cls.OVERRIDE_LABELS:
                overrides[str(code)] += 1

        blocker_events = Counter()
        for metadata in ActionPlanEventRecord.objects.filter(
            plan__workspace_id=workspace_id,
            timestamp__gte=since,
            event_type__in=['DATA_EVIDENCE_OVERRIDE', 'TASK_UPDATED'],
        ).values_list('event_type', 'metadata').iterator(chunk_size=500):
            event_type, event_metadata = metadata
            if event_type == 'DATA_EVIDENCE_OVERRIDE':
                blocker_events['Cần xem lại dữ liệu trước khi thực hiện'] += 1
            elif isinstance(event_metadata, dict) and event_metadata.get('status') == 'SKIPPED':
                blocker_events['Có bước checklist không thực hiện'] += 1

        completed = ActionPlanRecord.objects.filter(
            workspace_id=workspace_id, status='COMPLETED', completed_at__gte=since,
        )
        observed = completed.filter(observed_outcome__status='OBSERVED').count()
        partial = completed.filter(observed_outcome__status='PARTIAL').count()
        unavailable = completed.count() - observed - partial
        return {
            'version': 'DECISION_LEARNING_REPORT_V1',
            'period': {'days': days, 'from': since.date().isoformat(), 'to': timezone.localdate().isoformat()},
            'merchant_choices': {
                'recorded_count': feedback_total,
                'items': [{'label': cls.FEEDBACK_LABELS[key], 'count': count} for key, count in feedback.most_common(5)],
                'message': 'Lý do merchant ghi nhận khi chưa chọn phương án; không dùng để tự đánh giá đúng/sai.',
            },
            'plan_changes': {
                'recorded_count': sum(overrides.values()),
                'items': [{'label': cls.OVERRIDE_LABELS[key], 'count': count} for key, count in overrides.most_common(5)],
            },
            'operational_blockers': {
                'recorded_count': sum(blocker_events.values()),
                'items': [{'label': label, 'count': count} for label, count in blocker_events.most_common(5)],
            },
            'outcome_coverage': {
                'completed_plans': completed.count(),
                'odoo_observed': observed,
                'odoo_partial': partial,
                'not_reconciled': unavailable,
                'message': 'Đây là mức độ có số liệu để đối chiếu, không phải kết luận phương án đã tạo ra kết quả.',
            },
            'boundary': 'Báo cáo giúp cải thiện dữ liệu và cách làm. Nó không tự thay đổi giá, quy tắc cảnh báo hoặc kế hoạch đang chạy.',
        }
