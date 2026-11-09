"""Revalidate price-sensitive decisions against the latest Odoo inventory facts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from django.db.models import Q
from django.utils import timezone

from supplyforge.models import IntegrationConnection, InventoryRecord


class DecisionEvidenceFreshnessService:
    """Keep a recommendation from becoming an unsafe execution instruction.

    A decision remains immutable.  This service records the Odoo facts used at
    recommendation time and compares them with live, verified inventory facts
    before a price action is approved or started.
    """

    SNAPSHOT_VERSION = 'ODOO_DECISION_EVIDENCE_V1'
    PRICE_STRATEGIES = {'DISCOUNT', 'CLEARANCE', 'PROMOTION'}
    MAX_EVIDENCE_AGE_DAYS = 1

    @classmethod
    def is_price_sensitive(cls, strategy: str | None) -> bool:
        return str(strategy or '').upper() in cls.PRICE_STRATEGIES

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        return format(value, 'f') if value is not None else None

    @classmethod
    def capture(cls, *, workspace_id: int, sku: str) -> dict[str, Any]:
        return cls.capture_many(workspace_id=workspace_id, skus=[sku]).get(
            str(sku), cls._unavailable('NO_ODOO_EVIDENCE', 'Không có bằng chứng tồn kho Odoo cho SKU này.')
        )

    @classmethod
    def capture_many(cls, *, workspace_id: int, skus: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Capture evidence in bounded batches rather than issuing one query per SKU."""
        canonical_skus = sorted({str(sku).strip() for sku in skus if str(sku).strip()})
        result = {
            sku: cls._unavailable('NO_ODOO_EVIDENCE', 'Không có bằng chứng tồn kho Odoo cho SKU này.')
            for sku in canonical_skus
        }
        if not canonical_skus:
            return result

        active_connection_ids = {
            str(connection_id)
            for connection_id in IntegrationConnection.objects.filter(
                workspace_id=workspace_id,
                provider=IntegrationConnection.PROVIDER_ODOO,
                status=IntegrationConnection.STATUS_ACTIVE,
            ).values_list('id', flat=True)
        }
        if not active_connection_ids:
            return {
                sku: cls._unavailable(
                    'NO_ACTIVE_ODOO_CONNECTION',
                    'Chưa có kết nối Odoo đang hoạt động để tái xác nhận dữ liệu.',
                )
                for sku in canonical_skus
            }

        # SQLite has a conservative parameter limit; chunking also keeps this
        # bounded for workspaces with a large decision queue.
        records_by_sku: dict[str, list[InventoryRecord]] = defaultdict(list)
        for start in range(0, len(canonical_skus), 500):
            chunk = canonical_skus[start:start + 500]
            rows = InventoryRecord.objects.filter(
                sku__workspace_id=workspace_id,
                canonical_sku__in=chunk,
            ).filter(
                Q(source_lineage_json__provider='ODOO')
                | Q(source_snapshot_id__startswith='ODOO:')
            ).order_by(
                'canonical_sku', 'warehouse_code', '-record_date', '-source_observed_at', '-updated_at', '-id',
            )
            latest: dict[tuple[str, str, str], InventoryRecord] = {}
            for row in rows.iterator(chunk_size=2_000):
                lineage = row.source_lineage_json if isinstance(row.source_lineage_json, dict) else {}
                connection_id = str(lineage.get('connection_id') or '')
                if not connection_id or connection_id not in active_connection_ids:
                    continue
                key = (row.canonical_sku, connection_id, row.warehouse_code or 'UNSPECIFIED')
                latest.setdefault(key, row)
            for (canonical_sku, _, _), row in latest.items():
                records_by_sku[canonical_sku].append(row)

        for sku in canonical_skus:
            rows = records_by_sku.get(sku, [])
            if rows:
                result[sku] = cls._snapshot_from_records(rows)
        return result

    @classmethod
    def evaluate_decision(cls, decision) -> dict[str, Any]:
        """Compare recommendation evidence to fresh Odoo evidence."""
        parameters = decision.action_parameters if isinstance(decision.action_parameters, dict) else {}
        return cls.evaluate_for_strategy(
            workspace_id=decision.workspace_id,
            sku=decision.sku,
            strategy=decision.action_type,
            expected_snapshot=parameters.get('evidence_snapshot'),
        )

    @classmethod
    def evaluate_for_strategy(
        cls, *, workspace_id: int, sku: str, strategy: str, expected_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not cls.is_price_sensitive(strategy):
            return cls._not_required()
        current = cls.capture(workspace_id=workspace_id, sku=sku)
        if expected_snapshot is None:
            if current.get('state') == 'READY':
                return {
                    'state': 'READY',
                    'code': 'CURRENT_EVIDENCE_READY',
                    'message': 'Đã xác nhận tồn kho, giá vốn và giá bán từ Odoo.',
                    'current': current,
                    'expected': None,
                    'changed_fields': [],
                }
            return cls._compare(expected=None, current=current)
        return cls._compare(expected=expected_snapshot, current=current)

    @classmethod
    def evaluate_plan(cls, plan) -> dict[str, Any]:
        """Compare current facts to the snapshot accepted for this plan."""
        parameters = plan.action_parameters if isinstance(plan.action_parameters, dict) else {}
        expected = parameters.get('execution_evidence_snapshot')
        if not plan.decision_id and expected is None:
            return cls._not_required()
        if not expected and plan.decision_id:
            from supplyforge.models import DecisionRecord
            decision = DecisionRecord.objects.filter(
                decision_id=plan.decision_id,
                workspace_id=plan.workspace_id,
            ).only('action_parameters').first()
            expected = (decision.action_parameters or {}).get('evidence_snapshot') if decision else None
        return cls.evaluate_for_strategy(
            workspace_id=plan.workspace_id,
            sku=plan.sku,
            strategy=plan.strategy,
            expected_snapshot=expected,
        )

    @classmethod
    def snapshot_for_execution(cls, *, workspace_id: int, sku: str) -> dict[str, Any]:
        """Expose a fresh snapshot for persistence only after a successful gate."""
        return cls.capture(workspace_id=workspace_id, sku=sku)

    @classmethod
    def controlled_override_allowed(cls, evaluation: dict[str, Any]) -> bool:
        return evaluation.get('state') == 'STALE' and evaluation.get('current', {}).get('state') == 'READY'

    @classmethod
    def _compare(cls, *, expected: Any, current: dict[str, Any]) -> dict[str, Any]:
        if current.get('state') != 'READY':
            return {
                'state': 'BLOCKED',
                'code': 'CURRENT_ODOO_EVIDENCE_UNAVAILABLE',
                'message': 'Không thể xác nhận tồn kho, giá vốn và giá bán mới nhất từ Odoo.',
                'current': current,
                'expected': expected if isinstance(expected, dict) else None,
                'changed_fields': [],
            }
        if not isinstance(expected, dict) or expected.get('state') != 'READY':
            return {
                'state': 'STALE',
                'code': 'DECISION_EVIDENCE_MISSING',
                'message': 'Đề xuất chưa có ảnh chụp dữ liệu Odoo đã xác thực. Hãy làm mới đề xuất trước khi thực thi.',
                'current': current,
                'expected': expected if isinstance(expected, dict) else None,
                'changed_fields': ['recommendation_evidence'],
            }
        if expected.get('fingerprint') == current.get('fingerprint'):
            return {
                'state': 'READY',
                'code': 'EVIDENCE_CURRENT',
                'message': 'Dữ liệu Odoo vẫn khớp với ảnh chụp dùng để lập kế hoạch.',
                'current': current,
                'expected': expected,
                'changed_fields': [],
            }
        return {
            'state': 'STALE',
            'code': 'ODOO_FACTS_CHANGED',
            'message': 'Tồn kho, giá vốn hoặc giá bán Odoo đã thay đổi kể từ lúc lập đề xuất.',
            'current': current,
            'expected': expected,
            'changed_fields': cls._changed_fields(expected, current),
        }

    @classmethod
    def _snapshot_from_records(cls, records: list[InventoryRecord]) -> dict[str, Any]:
        today = timezone.localdate()
        reasons: list[dict[str, str]] = []
        rows: list[dict[str, Any]] = []
        record_dates: list[date] = []
        observed_values = []
        for record in records:
            lineage = record.source_lineage_json if isinstance(record.source_lineage_json, dict) else {}
            connection_id = str(lineage.get('connection_id') or '')
            warehouse = (record.warehouse_code or 'UNSPECIFIED').strip() or 'UNSPECIFIED'
            quantity = record.available_quantity
            if quantity is None or quantity < 0:
                reasons.append({'code': 'AVAILABLE_QUANTITY_INVALID', 'warehouse': warehouse})
            if record.cost_price is None or record.cost_price < 0:
                reasons.append({'code': 'UNIT_COST_INVALID', 'warehouse': warehouse})
            if record.selling_price is None or record.selling_price <= 0:
                reasons.append({'code': 'UNIT_PRICE_INVALID', 'warehouse': warehouse})
            if not record.as_of_verified:
                reasons.append({'code': 'INVENTORY_NOT_VERIFIED', 'warehouse': warehouse})
            if not record.record_date or (today - record.record_date).days > cls.MAX_EVIDENCE_AGE_DAYS:
                reasons.append({'code': 'INVENTORY_STALE', 'warehouse': warehouse})
            if not record.source_snapshot_id:
                reasons.append({'code': 'SOURCE_LINEAGE_MISSING', 'warehouse': warehouse})
            record_dates.append(record.record_date)
            if record.source_observed_at:
                observed_values.append(record.source_observed_at)
            rows.append({
                'connection_id': connection_id,
                'warehouse_code': warehouse,
                'available_quantity': cls._decimal_text(quantity),
                'unit_cost': cls._decimal_text(record.cost_price),
                'unit_price': cls._decimal_text(record.selling_price),
                'lifecycle_status': record.lifecycle_status,
                'record_date': record.record_date.isoformat(),
                'source_snapshot_id': record.source_snapshot_id,
            })
        rows.sort(key=lambda row: (row['connection_id'], row['warehouse_code']))
        fingerprint_input = [
            {
                key: row[key]
                for key in ('connection_id', 'warehouse_code', 'available_quantity', 'unit_cost', 'unit_price', 'lifecycle_status')
            }
            for row in rows
        ]
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_input, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        return {
            'version': cls.SNAPSHOT_VERSION,
            'state': 'READY' if not reasons else 'UNAVAILABLE',
            'captured_at': timezone.now().isoformat(),
            'source_data_as_of': min(record_dates).isoformat() if record_dates else None,
            'source_observed_at': max(observed_values).isoformat() if observed_values else None,
            'warehouse_count': len(rows),
            'records': rows,
            'fingerprint': fingerprint,
            'reasons': reasons,
        }

    @classmethod
    def _changed_fields(cls, expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
        def index(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
            return {
                (str(row.get('connection_id') or ''), str(row.get('warehouse_code') or '')): row
                for row in snapshot.get('records', [])
                if isinstance(row, dict)
            }

        prior, latest = index(expected), index(current)
        changed: list[str] = []
        for key in sorted(set(prior) | set(latest)):
            before, after = prior.get(key), latest.get(key)
            label = f'{key[0]}:{key[1]}'
            if not before or not after:
                changed.append(f'warehouse_scope:{label}')
                continue
            for field in ('available_quantity', 'unit_cost', 'unit_price', 'lifecycle_status'):
                if before.get(field) != after.get(field):
                    changed.append(f'{field}:{label}')
        return changed

    @classmethod
    def _unavailable(cls, code: str, message: str) -> dict[str, Any]:
        return {
            'version': cls.SNAPSHOT_VERSION,
            'state': 'UNAVAILABLE',
            'captured_at': timezone.now().isoformat(),
            'source_data_as_of': None,
            'source_observed_at': None,
            'warehouse_count': 0,
            'records': [],
            'fingerprint': None,
            'reasons': [{'code': code, 'message': message}],
        }

    @staticmethod
    def _not_required() -> dict[str, Any]:
        return {
            'state': 'NOT_REQUIRED',
            'code': 'NOT_PRICE_SENSITIVE',
            'message': 'Phương án này không thay đổi giá nên không cần tái xác nhận giá Odoo.',
            'current': None,
            'expected': None,
            'changed_fields': [],
        }
