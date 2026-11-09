"""Merchant-readable decision renewal without changing recommendation history."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from supplyforge.models.decision import DecisionAuditEventRecord, DecisionReviewRecord
from supplyforge.services.decision_evidence_freshness import DecisionEvidenceFreshnessService


class DecisionRevalidationError(ValueError):
    """Raised when an unsafe decision is being approved as current."""


class DecisionRevalidationService:
    """Expose and persist the one question a merchant needs before acting.

    The decision and its original evidence remain untouched.  An approval is a
    new append-only record bound to the data that was checked at that moment.
    """

    FIELD_LABELS = {
        'available_quantity': 'Số lượng tồn có thể bán',
        'unit_cost': 'Giá vốn',
        'unit_price': 'Giá bán',
        'lifecycle_status': 'Trạng thái sản phẩm',
        'warehouse_scope': 'Phạm vi kho',
        'recommendation_evidence': 'Ảnh chụp dữ liệu của đề xuất',
    }

    @classmethod
    def _approved_snapshot(cls, decision) -> dict[str, Any] | None:
        record = decision.review_records.filter(
            status=DecisionReviewRecord.STATUS_READY,
            approved_at__isnull=False,
        ).only('current_snapshot_json').first()
        snapshot = record.current_snapshot_json if record else None
        return snapshot if isinstance(snapshot, dict) else None

    @classmethod
    def expected_snapshot(cls, decision) -> dict[str, Any] | None:
        """Prefer the latest explicit merchant re-approval for a future plan."""
        approved = cls._approved_snapshot(decision)
        if approved:
            return approved
        parameters = decision.action_parameters if isinstance(decision.action_parameters, dict) else {}
        snapshot = parameters.get('evidence_snapshot')
        return snapshot if isinstance(snapshot, dict) else None

    @classmethod
    def _evaluation(cls, decision) -> dict[str, Any]:
        expected = cls.expected_snapshot(decision)
        return DecisionEvidenceFreshnessService.evaluate_for_strategy(
            workspace_id=decision.workspace_id,
            sku=decision.sku,
            strategy=decision.action_type,
            expected_snapshot=expected,
        )

    @classmethod
    def _indexed_rows(cls, snapshot: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
        if not isinstance(snapshot, dict):
            return {}
        rows = snapshot.get('records') if isinstance(snapshot.get('records'), list) else []
        return {
            (str(row.get('connection_id') or ''), str(row.get('warehouse_code') or '')): row
            for row in rows
            if isinstance(row, dict)
        }

    @classmethod
    def _change_items(cls, evaluation: dict[str, Any]) -> list[dict[str, str]]:
        expected = cls._indexed_rows(evaluation.get('expected'))
        current = cls._indexed_rows(evaluation.get('current'))
        items: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for token in evaluation.get('changed_fields') or []:
            token = str(token)
            field, _, raw_scope = token.partition(':')
            label = cls.FIELD_LABELS.get(field, 'Dữ liệu nguồn')
            key_parts = raw_scope.split(':', 1)
            scope_key = (key_parts[0], key_parts[1]) if len(key_parts) == 2 else ('', '')
            before, after = expected.get(scope_key, {}), current.get(scope_key, {})
            dedupe_key = (field, raw_scope)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if field == 'warehouse_scope':
                before_value = 'Có trong ảnh chụp trước đó' if before else 'Chưa có trong ảnh chụp trước đó'
                after_value = 'Có trong dữ liệu hiện tại' if after else 'Không còn trong dữ liệu hiện tại'
            elif field == 'recommendation_evidence':
                before_value, after_value = 'Chưa có ảnh chụp hợp lệ', 'Đã có dữ liệu hiện tại để kiểm tra'
            else:
                before_value = str(before.get(field, 'Chưa có'))
                after_value = str(after.get(field, 'Chưa có'))
            scope = raw_scope.split(':')[-1] if raw_scope else ''
            items.append({
                'field': field,
                'label': label,
                'scope': scope,
                'before': before_value,
                'after': after_value,
            })
        return items

    @classmethod
    def passport(cls, decision) -> dict[str, Any]:
        evaluation = cls._evaluation(decision)
        raw_state = evaluation.get('state')
        if raw_state in {'READY', 'NOT_REQUIRED'}:
            merchant_state = DecisionReviewRecord.STATUS_READY
            title = 'Đủ điều kiện thực thi'
        elif raw_state == 'STALE':
            merchant_state = DecisionReviewRecord.STATUS_NEEDS_RECHECK
            title = 'Cần xem lại trước khi thực thi'
        else:
            merchant_state = DecisionReviewRecord.STATUS_DATA_NEEDED
            title = 'Cần bổ sung hoặc kiểm tra dữ liệu'
        latest = decision.review_records.order_by('-created_at').only(
            'id', 'status', 'reviewed_by', 'review_note', 'approved_at', 'created_at'
        ).first()
        expected = evaluation.get('expected') if isinstance(evaluation.get('expected'), dict) else None
        current = evaluation.get('current') if isinstance(evaluation.get('current'), dict) else None
        return {
            'version': 'DECISION_REVALIDATION_V1',
            'decision_id': decision.decision_id,
            'state': merchant_state,
            'title': title,
            'message': evaluation.get('message') or 'Cần kiểm tra dữ liệu trước khi thực thi.',
            # A changed-but-readable Odoo snapshot may be explicitly approved
            # as a *new* basis.  Missing/unverifiable facts never may.
            'can_approve': merchant_state in {
                DecisionReviewRecord.STATUS_READY, DecisionReviewRecord.STATUS_NEEDS_RECHECK,
            } and isinstance(current, dict) and current.get('state') == 'READY',
            'changes': cls._change_items(evaluation),
            'baseline': cls._source_summary(expected),
            'current_data': cls._source_summary(current),
            'last_review': ({
                'review_id': str(latest.id),
                'state': latest.status,
                'reviewed_by': latest.reviewed_by or None,
                'review_note': latest.review_note or None,
                'approved_at': latest.approved_at.isoformat() if latest.approved_at else None,
                'created_at': latest.created_at.isoformat(),
            } if latest else None),
            'boundary': 'Việc kiểm tra này chỉ xác nhận dữ liệu dùng cho phương án còn phù hợp tại thời điểm xem; không tự đổi giá, PO hoặc kết quả kinh doanh.',
        }

    @staticmethod
    def _source_summary(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(snapshot, dict):
            return None
        return {
            'state': snapshot.get('state'),
            'as_of': snapshot.get('source_data_as_of'),
            'observed_at': snapshot.get('source_observed_at'),
            'warehouse_count': snapshot.get('warehouse_count'),
        }

    @classmethod
    def approve(cls, *, decision, actor: str, note: str = '') -> dict[str, Any]:
        passport = cls.passport(decision)
        if not passport['can_approve']:
            raise DecisionRevalidationError(passport['message'])
        if passport['state'] == DecisionReviewRecord.STATUS_NEEDS_RECHECK and len((note or '').strip()) < 8:
            raise DecisionRevalidationError(
                'Dữ liệu đã thay đổi. Hãy nêu ngắn gọn điều đã kiểm tra trước khi xác nhận theo dữ liệu mới.'
            )
        evaluation = cls._evaluation(decision)
        record = DecisionReviewRecord.objects.create(
            decision=decision,
            workspace_id=decision.workspace_id,
            status=DecisionReviewRecord.STATUS_READY,
            baseline_snapshot_json=evaluation.get('expected') or {},
            current_snapshot_json=evaluation.get('current') or {},
            changes_json=passport['changes'],
            summary=(
                'Đã xác nhận lại theo dữ liệu mới.'
                if passport['state'] == DecisionReviewRecord.STATUS_NEEDS_RECHECK
                else passport['message']
            )[:500],
            reviewed_by=(actor or 'merchant')[:128],
            review_note=(note or '').strip(),
            approved_at=timezone.now(),
        )
        DecisionAuditEventRecord.objects.create(
            decision=decision,
            event_type='DECISION_REVALIDATED',
            old_status=decision.status,
            new_status=decision.status,
            actor=(actor or 'merchant')[:128],
            notes=(note or '').strip(),
            metadata={
                'review_id': str(record.id),
                'state': record.status,
                'changed_fields': [item['field'] for item in passport['changes']],
                'current_data_as_of': (evaluation.get('current') or {}).get('source_data_as_of'),
            },
        )
        return cls.passport(decision)
