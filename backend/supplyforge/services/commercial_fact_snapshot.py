"""Immutable, scope-matched commercial facts for merchant decisions.

Decision services used to independently query the latest risk row, product row
or inventory row.  That looks convenient but can mix a price from one date
with stock from another warehouse.  This module creates a compact snapshot from
the assessment run's already verified evidence instead.  It is deliberately a
fact contract, not a forecast or an execution command.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CommercialFactSnapshotService:
    VERSION = 'COMMERCIAL_FACT_SNAPSHOT_V1'

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, '') else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_assessment(cls, assessment) -> dict[str, Any]:
        """Freeze decision inputs from one immutable operational assessment.

        The operational run is mandatory for generated decisions. Legacy
        research rows are reported as data unavailable rather than upgraded by
        reading mutable product/inventory tables.
        """
        evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
        run = getattr(assessment, 'assessment_run', None)
        if not run:
            return cls._unavailable('ASSESSMENT_RUN_MISSING', 'Đề xuất tự động cần một lần đánh giá vận hành có thể đối soát.')

        inventory_readiness = evidence.get('inventory_readiness') or {}
        stock = cls._number(evidence.get('stock_quantity'))
        unit_cost = cls._number(evidence.get('unit_cost'))
        unit_price = cls._number(evidence.get('unit_price'))
        capital_exposure = cls._number(evidence.get('capital_exposure_vnd'))
        velocity_30d = cls._number(evidence.get('sales_velocity_30d'))
        velocity_90d = cls._number(evidence.get('sales_velocity_90d'))
        source_scope = run.source_scope if isinstance(run.source_scope, dict) else {}

        reasons: list[dict[str, str]] = []
        if assessment.assessment_status != 'COMPLETE':
            reasons.append({'code': 'ASSESSMENT_NOT_COMPLETE', 'message': 'SKU chưa qua điều kiện đánh giá vận hành.'})
        if inventory_readiness.get('status') != 'READY':
            reasons.append({'code': 'INVENTORY_NOT_READY', 'message': 'Tồn kho hoặc giá vốn đã xác thực chưa đầy đủ.'})
        if stock is None or stock < 0:
            reasons.append({'code': 'STOCK_UNAVAILABLE', 'message': 'Chưa có tồn kho khả dụng hợp lệ.'})
        if unit_cost is None or unit_cost < 0:
            reasons.append({'code': 'UNIT_COST_UNAVAILABLE', 'message': 'Chưa có giá vốn hợp lệ.'})
        if unit_price is None or unit_price <= 0:
            reasons.append({'code': 'UNIT_PRICE_UNAVAILABLE', 'message': 'Chưa có giá bán hợp lệ.'})
        if not run.source_scope_fingerprint:
            reasons.append({'code': 'SOURCE_SCOPE_MISSING', 'message': 'Thiếu phạm vi nguồn dữ liệu để đối soát.'})

        fact_payload = {
            'source_type': run.source_type,
            'source_key': run.source_key,
            'source_scope_fingerprint': run.source_scope_fingerprint,
            'source_snapshot_fingerprint': run.source_snapshot_fingerprint,
            'analysis_as_of': run.analysis_as_of.isoformat(),
            'source_freshness': run.source_freshness,
            'source_scope': source_scope,
            'policy_version': run.policy_version,
            'policy_checksum': run.policy_checksum,
            'assessment_id': str(assessment.id),
            'assessment_run_id': str(run.id),
            'sku': assessment.sku,
            'canonical_sku': assessment.canonical_sku_id,
            'inventory': {
                'available_quantity': stock,
                'unit_cost': unit_cost,
                'unit_price': unit_price,
                'capital_exposure': capital_exposure,
                'record_date': inventory_readiness.get('record_date'),
                'warehouse_count': inventory_readiness.get('warehouse_count'),
                'lifecycle_status': inventory_readiness.get('lifecycle_status'),
            },
            'demand': {
                'sold_30d': cls._number(evidence.get('sold_30d')),
                'sold_90d': cls._number(evidence.get('sold_90d')),
                'sales_velocity_30d': velocity_30d,
                'sales_velocity_90d': velocity_90d,
                'source_coverage_days': evidence.get('source_coverage_days'),
                'sku_observed_days': evidence.get('sku_observed_days'),
                'last_qualified_sale_at': evidence.get('last_qualified_sale_at'),
            },
            'risk': {
                'risk_class': assessment.risk_class,
                'priority_score': assessment.risk_score,
                'score_semantics': evidence.get('score_semantics', 'UNDECLARED'),
                'risk_probability': assessment.risk_probability,
                'calibration_version': assessment.calibration_version,
            },
            'readiness': {
                'inventory_observed': inventory_readiness.get('status') == 'READY',
                'financial_inputs_complete': all(value is not None and value >= 0 for value in (stock, unit_cost, unit_price)),
                'demand_observed': velocity_30d is not None or velocity_90d is not None,
                'demand_positive': any(value is not None and value > 0 for value in (velocity_30d, velocity_90d)),
            },
        }
        serialized = json.dumps(fact_payload, sort_keys=True, separators=(',', ':'), default=str)
        return {
            'version': cls.VERSION,
            'state': 'READY' if not reasons else 'DATA_NEEDED',
            'fingerprint': hashlib.sha256(serialized.encode('utf-8')).hexdigest(),
            'reasons': reasons,
            **fact_payload,
        }

    @classmethod
    def _unavailable(cls, code: str, message: str) -> dict[str, Any]:
        return {
            'version': cls.VERSION,
            'state': 'DATA_NEEDED',
            'fingerprint': None,
            'reasons': [{'code': code, 'message': message}],
        }
