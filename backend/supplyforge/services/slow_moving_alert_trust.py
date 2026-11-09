"""Merchant-trust contracts for slow-moving alerts.

The rules in this module never change an alert score or outcome label. They
only establish whether a merchant has a trustworthy explanation, whether a
closed alert has truly changed enough to reopen, and which business context
makes stock safe to assess.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.db.models import Q
from django.utils import timezone

from supplyforge.models import (
    SlowMovingAlertAttentionEvent,
    SlowMovingAlertPassport,
    SlowMovingAlertState,
    SlowMovingAssessmentRun,
    SlowMovingSkuContext,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ATTENTION_POLICY_PATH = PROJECT_ROOT / 'config' / 'slow_moving_alert_attention_policy.json'


class SlowMovingAlertTrustError(ValueError):
    """Raised when a trust-contract input is invalid or unsafe to use."""


def _canonical(value: Any) -> str:
    return str(value or '').strip().upper()


def _number(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Retain only decisions facts that merchant copy is allowed to explain."""
    return {
        'risk_class': str(snapshot.get('risk_class') or ''),
        'priority_score': _number(snapshot.get('priority_score')),
        'stock_quantity': _number(snapshot.get('stock_quantity')),
        'sold_30d': _number(snapshot.get('sold_30d')),
        'sales_velocity_90d': _number(snapshot.get('sales_velocity_90d')),
        'days_without_order': _number(snapshot.get('days_without_order')),
        'returned_30d': _number(snapshot.get('returned_30d')),
        'eligibility_status': str(snapshot.get('eligibility_status') or ''),
        'catalog_context': snapshot.get('catalog_context') or {},
        'source_data_as_of': snapshot.get('source_data_as_of'),
        'source_scope_fingerprint': str(snapshot.get('source_scope_fingerprint') or ''),
    }


class SlowMovingAlertAttentionPolicy:
    """Loads a small versioned policy; unsafe/missing values fail closed."""

    @classmethod
    def load(cls) -> tuple[dict[str, Any], str]:
        try:
            raw = ATTENTION_POLICY_PATH.read_bytes()
            policy = json.loads(raw.decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SlowMovingAlertTrustError('Không đọc được chính sách nhắc việc cảnh báo.') from exc
        required = {'version', 'recheck_days', 'feedback_remediation_due_days', 'digest_max_items', 'material_change', 'notification'}
        if required.difference(policy) or not isinstance(policy.get('material_change'), dict):
            raise SlowMovingAlertTrustError('Chính sách nhắc việc cảnh báo thiếu thông tin bắt buộc.')
        try:
            if int(policy['recheck_days']) < 1 or int(policy['feedback_remediation_due_days']) < 1:
                raise ValueError
            if int(policy['digest_max_items']) < 1:
                raise ValueError
            change = policy['material_change']
            if float(change['priority_score_delta']) <= 0:
                raise ValueError
            if not 0 <= float(change['stock_increase_ratio']) <= 1:
                raise ValueError
            if not 0 <= float(change['velocity_drop_ratio']) <= 1:
                raise ValueError
            if int(change['days_without_order_increase']) < 1:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise SlowMovingAlertTrustError('Ngưỡng thay đổi cảnh báo không hợp lệ.') from exc
        return policy, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CatalogContextResolution:
    availability: str
    catalog_role: str
    related_canonical_sku: str
    conversion_quantity: float | None
    status: str
    reasons: list[str]
    context_id: str | None
    evidence_reference: str

    def as_evidence(self) -> dict[str, Any]:
        return {
            'availability': self.availability,
            'catalog_role': self.catalog_role,
            'related_canonical_sku': self.related_canonical_sku or None,
            'conversion_quantity': self.conversion_quantity,
            'status': self.status,
            'reasons': self.reasons,
            'context_id': self.context_id,
            'evidence_reference': self.evidence_reference or None,
        }


class SlowMovingCatalogContextResolver:
    """Resolve merchant declarations without a per-SKU query in a worker."""

    def __init__(self, *, workspace_id: int, source_key: str, as_of: datetime):
        self.workspace_id = int(workspace_id)
        self.source_key = str(source_key or '')
        self.as_of = as_of
        self._rows_by_sku: dict[str, list[SlowMovingSkuContext]] = {}
        self._expired_rows_by_sku: dict[str, list[SlowMovingSkuContext]] = {}
        active_query = SlowMovingSkuContext.objects.filter(
            workspace_id=self.workspace_id,
            effective_from__lte=as_of,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of))
        for row in active_query.order_by('canonical_sku', '-effective_from', '-created_at').iterator(chunk_size=2_000):
            self._rows_by_sku.setdefault(_canonical(row.canonical_sku), []).append(row)
        # A manual declaration is an expiring override, not a permanent
        # license to keep excluding (or including) a SKU. Keep expired rows
        # separate so the normal legacy default remains available for SKU
        # without any merchant declaration, while an expired override becomes
        # an explicit data-needed state.
        expired_query = SlowMovingSkuContext.objects.filter(
            workspace_id=self.workspace_id,
            effective_from__lte=as_of,
            effective_to__lt=as_of,
        )
        for row in expired_query.order_by('canonical_sku', '-effective_to', '-created_at').iterator(chunk_size=2_000):
            self._expired_rows_by_sku.setdefault(_canonical(row.canonical_sku), []).append(row)

    def _best_scope_match(
        self, rows: list[SlowMovingSkuContext], *, warehouse: str, channel: str,
    ) -> SlowMovingSkuContext | None:
        selected: SlowMovingSkuContext | None = None
        selected_rank = -1
        for row in rows:
            if row.source_key and row.source_key != self.source_key:
                continue
            if row.warehouse_code and row.warehouse_code != warehouse:
                continue
            if row.channel and row.channel != channel:
                continue
            # A scope-specific declaration takes precedence over a general
            # one; each collection is already ordered newest-first.
            rank = (4 if row.source_key else 0) + (2 if row.warehouse_code else 0) + (1 if row.channel else 0)
            if rank > selected_rank:
                selected, selected_rank = row, rank
        return selected

    def resolve(self, *, canonical_sku: str, warehouse_code: str = '', channel: str = '') -> CatalogContextResolution:
        sku = _canonical(canonical_sku)
        warehouse = str(warehouse_code or '').strip()
        selected = self._best_scope_match(
            self._rows_by_sku.get(sku, []), warehouse=warehouse, channel=channel,
        )
        if selected is None:
            expired = self._best_scope_match(
                self._expired_rows_by_sku.get(sku, []), warehouse=warehouse, channel=channel,
            )
            if expired and (expired.provenance_json or {}).get('source') == 'merchant-api':
                return CatalogContextResolution(
                    availability=SlowMovingSkuContext.AVAILABILITY_UNKNOWN,
                    catalog_role=expired.catalog_role,
                    related_canonical_sku=_canonical(expired.related_canonical_sku),
                    conversion_quantity=_number(expired.conversion_quantity),
                    status='DATA_NEEDED',
                    reasons=['CATALOG_CONTEXT_EXPIRED'],
                    context_id=str(expired.id),
                    evidence_reference=expired.evidence_reference,
                )
            # Legacy inventory has no special declaration. It is kept usable as
            # a normal standalone SKU, while any explicitly unknown context
            # below fails safe instead of being silently treated as sellable.
            return CatalogContextResolution(
                availability=SlowMovingSkuContext.AVAILABILITY_SELLABLE,
                catalog_role=SlowMovingSkuContext.ROLE_STANDALONE,
                related_canonical_sku='', conversion_quantity=None,
                status='READY', reasons=[], context_id=None, evidence_reference='',
            )
        role = selected.catalog_role
        availability = selected.availability
        relation_requires_proof = role in {
            SlowMovingSkuContext.ROLE_BUNDLE,
            SlowMovingSkuContext.ROLE_COMPONENT,
            SlowMovingSkuContext.ROLE_REPLACEMENT,
        }
        conversion = _number(selected.conversion_quantity)
        reasons: list[str] = []
        status = 'READY'
        if availability == SlowMovingSkuContext.AVAILABILITY_UNKNOWN or role == SlowMovingSkuContext.ROLE_UNKNOWN:
            status = 'DATA_NEEDED'
            reasons.append('CATALOG_CONTEXT_UNCONFIRMED')
        elif availability != SlowMovingSkuContext.AVAILABILITY_SELLABLE:
            status = 'NOT_SELLABLE'
            reasons.append(f'INVENTORY_{availability}')
        elif role == SlowMovingSkuContext.ROLE_END_OF_LIFE:
            status = 'NOT_SELLABLE'
            reasons.append('PRODUCT_END_OF_LIFE')
        elif relation_requires_proof and (not _canonical(selected.related_canonical_sku) or conversion is None or conversion <= 0):
            status = 'DATA_NEEDED'
            reasons.append('CATALOG_RELATION_UNCONFIRMED')
        return CatalogContextResolution(
            availability=availability,
            catalog_role=role,
            related_canonical_sku=_canonical(selected.related_canonical_sku),
            conversion_quantity=conversion,
            status=status,
            reasons=reasons,
            context_id=str(selected.id),
            evidence_reference=selected.evidence_reference,
        )


class SlowMovingAlertTrustService:
    """Computes explainable change and records immutable alert events."""

    RISK_ORDER = {'LOW_RISK': 0, 'MEDIUM_RISK': 1, 'HIGH_RISK': 2, 'CRITICAL': 3}

    @classmethod
    def snapshot_for_assessment(cls, assessment, run: SlowMovingAssessmentRun) -> dict[str, Any]:
        evidence = dict(getattr(assessment, 'evidence', None) or {})
        score = getattr(assessment, 'risk_score', None)
        return _normalise_snapshot({
            'risk_class': getattr(assessment, 'risk_class', ''),
            'priority_score': evidence.get('priority_score', score),
            'stock_quantity': evidence.get('stock_quantity'),
            'sold_30d': evidence.get('sold_30d'),
            'sales_velocity_90d': evidence.get('sales_velocity_90d'),
            'days_without_order': evidence.get('dsls'),
            'returned_30d': evidence.get('returned_30d'),
            'eligibility_status': evidence.get('eligibility_status'),
            'catalog_context': evidence.get('catalog_context'),
            'source_data_as_of': evidence.get('source_data_as_of') or run.analysis_as_of.isoformat(),
            'source_scope_fingerprint': evidence.get('source_scope_fingerprint') or run.source_scope_fingerprint,
        })

    @staticmethod
    def fingerprint(snapshot: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(_normalise_snapshot(snapshot), sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
        ).hexdigest()

    @classmethod
    def changed_facts(cls, previous: dict[str, Any], current: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
        previous = _normalise_snapshot(previous or {})
        current = _normalise_snapshot(current or {})
        if not previous or not previous.get('source_scope_fingerprint'):
            return []
        if previous.get('source_scope_fingerprint') != current.get('source_scope_fingerprint'):
            return [{'code': 'SCOPE_NOT_COMPARABLE', 'label': 'Chưa đủ dữ liệu để so sánh cùng phạm vi', 'material': False}]
        threshold = policy['material_change']
        changes: list[dict[str, Any]] = []

        before_risk = cls.RISK_ORDER.get(previous.get('risk_class'), -1)
        after_risk = cls.RISK_ORDER.get(current.get('risk_class'), -1)
        if after_risk > before_risk:
            changes.append({'code': 'RISK_CLASS_WORSENED', 'label': 'Mức cần ưu tiên đã tăng', 'before': previous.get('risk_class'), 'after': current.get('risk_class'), 'material': True})
        before_score, after_score = previous.get('priority_score'), current.get('priority_score')
        if before_score is not None and after_score is not None and after_score - before_score >= float(threshold['priority_score_delta']):
            changes.append({'code': 'PRIORITY_INCREASED', 'label': 'Mức ưu tiên tăng rõ rệt', 'before': before_score, 'after': after_score, 'material': True})
        before_stock, after_stock = previous.get('stock_quantity'), current.get('stock_quantity')
        minimum_stock_change = float(threshold['stock_increase_units'])
        if before_stock is not None and after_stock is not None:
            growth = after_stock - before_stock
            base = max(1.0, abs(before_stock))
            if growth >= minimum_stock_change and growth / base >= float(threshold['stock_increase_ratio']):
                changes.append({'code': 'SELLABLE_STOCK_INCREASED', 'label': 'Tồn có thể bán tăng', 'before': before_stock, 'after': after_stock, 'material': True})
        before_velocity, after_velocity = previous.get('sales_velocity_90d'), current.get('sales_velocity_90d')
        if before_velocity is not None and after_velocity is not None and before_velocity > 0:
            if (before_velocity - after_velocity) / before_velocity >= float(threshold['velocity_drop_ratio']):
                changes.append({'code': 'SALES_VELOCITY_DROPPED', 'label': 'Tốc độ bán giảm', 'before': before_velocity, 'after': after_velocity, 'material': True})
        before_days, after_days = previous.get('days_without_order'), current.get('days_without_order')
        if before_days is not None and after_days is not None and after_days - before_days >= int(threshold['days_without_order_increase']):
            changes.append({'code': 'NO_ORDER_PERIOD_LONGER', 'label': 'Số ngày chưa có đơn tăng', 'before': before_days, 'after': after_days, 'material': True})
        if previous.get('catalog_context') != current.get('catalog_context'):
            changes.append({'code': 'CATALOG_CONTEXT_CHANGED', 'label': 'Tình trạng hàng hóa đã thay đổi', 'before': previous.get('catalog_context'), 'after': current.get('catalog_context'), 'material': True})
        if previous.get('eligibility_status') != current.get('eligibility_status'):
            changes.append({'code': 'ELIGIBILITY_CHANGED', 'label': 'Tình trạng dữ liệu đánh giá đã thay đổi', 'before': previous.get('eligibility_status'), 'after': current.get('eligibility_status'), 'material': True})
        return changes

    @staticmethod
    def has_material_change(changes: list[dict[str, Any]]) -> bool:
        return any(bool(change.get('material')) for change in changes)

    @classmethod
    def event_type_for(cls, *, prior_status: str, status: str, changes: list[dict[str, Any]], opened_now: bool) -> str | None:
        if status == SlowMovingAlertState.STATUS_DATA_BLOCKED:
            return SlowMovingAlertPassport.EVENT_DATA_BLOCKED
        if prior_status == SlowMovingAlertState.STATUS_RESOLVED and status in {
            SlowMovingAlertState.STATUS_CANDIDATE, SlowMovingAlertState.STATUS_OPEN,
        }:
            return SlowMovingAlertPassport.EVENT_REOPENED
        if opened_now:
            return SlowMovingAlertPassport.EVENT_OPENED
        if cls.has_material_change(changes):
            return SlowMovingAlertPassport.EVENT_WORSENED
        return None

    @classmethod
    def passport_copy(cls, *, event_type: str, changes: list[dict[str, Any]], current: dict[str, Any]) -> tuple[str, str, str, str]:
        material_labels = [str(change.get('label')) for change in changes if change.get('material')]
        reason = '; '.join(material_labels[:2])
        if event_type == SlowMovingAlertPassport.EVENT_OPENED:
            return (
                'Cảnh báo đã được xác nhận',
                'Sản phẩm xuất hiện trong hai lần kiểm tra liên tiếp với tín hiệu bán chậm và tồn vẫn có thể bán.',
                'Kiểm tra số tồn có thể bán và chọn phương án an toàn trước khi thực hiện.',
                'Kiểm tra lại khi có lần đồng bộ dữ liệu mới hoặc sau 7 ngày.',
            )
        if event_type == SlowMovingAlertPassport.EVENT_REOPENED:
            return (
                'Cảnh báo cần được xem lại',
                f'Cảnh báo được mở lại vì {reason or "dữ liệu vận hành đã thay đổi đáng kể"}.',
                'Xem số liệu thay đổi trước khi tiếp tục một phương án cũ.',
                'Kiểm tra lại khi nguồn dữ liệu cập nhật hoặc điều kiện bán thay đổi.',
            )
        if event_type == SlowMovingAlertPassport.EVENT_DATA_BLOCKED:
            return (
                'Cần bổ sung dữ liệu trước khi xử lý',
                'Hệ thống không thể xác nhận phạm vi hàng có thể bán hoặc lịch sử dữ liệu cho lần đánh giá này.',
                'Kiểm tra dữ liệu tồn kho, trạng thái hàng và liên kết SKU.',
                'Kiểm tra lại sau khi dữ liệu nguồn được xác nhận.',
            )
        return (
            'Tình trạng bán chậm thay đổi',
            f'Lý do cần xem hôm nay: {reason or "một số số liệu vận hành đã thay đổi"}.',
            'Xem số liệu trước và sau rồi kiểm tra lại phương án đang dự định.',
            'Kiểm tra lại khi có đồng bộ mới hoặc sau 7 ngày.',
        )

    @classmethod
    def create_passport(
        cls, *, run: SlowMovingAssessmentRun, alert: SlowMovingAlertState,
        assessment=None, event_type: str | None, previous: dict[str, Any],
        current: dict[str, Any], changes: list[dict[str, Any]],
    ) -> SlowMovingAlertPassport | None:
        if not event_type:
            return None
        existing = SlowMovingAlertPassport.objects.filter(alert_state=alert, assessment_run=run).first()
        if existing:
            return existing
        title, summary, next_step, recheck = cls.passport_copy(
            event_type=event_type, changes=changes, current=current,
        )
        passport = SlowMovingAlertPassport.objects.create(
            workspace_id=run.workspace_id,
            alert_state=alert,
            assessment_run=run,
            assessment=assessment if getattr(assessment, '_meta', None) and assessment._meta.model_name == 'slowmovingriskassessment' else None,
            event_type=event_type,
            source_scope_fingerprint=run.source_scope_fingerprint,
            previous_facts_json=_normalise_snapshot(previous),
            current_facts_json=_normalise_snapshot(current),
            changed_facts_json=changes,
            title=title,
            summary=summary,
            safe_next_step=next_step,
            recheck_condition=recheck,
        )
        event_map = {
            SlowMovingAlertPassport.EVENT_OPENED: SlowMovingAlertAttentionEvent.TYPE_OPENED,
            SlowMovingAlertPassport.EVENT_WORSENED: SlowMovingAlertAttentionEvent.TYPE_WORSENED,
            SlowMovingAlertPassport.EVENT_REOPENED: SlowMovingAlertAttentionEvent.TYPE_REOPENED,
            SlowMovingAlertPassport.EVENT_DATA_BLOCKED: SlowMovingAlertAttentionEvent.TYPE_DATA_BLOCKED,
        }
        attention_type = event_map.get(event_type)
        if attention_type and not SlowMovingAlertAttentionEvent.objects.filter(
            alert_state=alert, assessment_run=run, event_type=attention_type,
        ).exists():
            SlowMovingAlertAttentionEvent.objects.create(
                workspace_id=run.workspace_id,
                alert_state=alert,
                assessment_run=run,
                passport=passport,
                event_type=attention_type,
                reason_codes=[str(change.get('code')) for change in changes if change.get('code')],
                policy_version=run.policy_version,
            )
        return passport

    @classmethod
    def next_review(cls, *, now: datetime | None = None, policy: dict[str, Any] | None = None) -> datetime:
        if policy is None:
            policy, _ = SlowMovingAlertAttentionPolicy.load()
        return (now or timezone.now()) + timedelta(days=int(policy['recheck_days']))
