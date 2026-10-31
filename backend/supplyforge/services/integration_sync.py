"""Provider-neutral projection of read-only ERP data into daily SKU metrics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from supplyforge.models import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationSkuDailyMetric,
    IntegrationSkuMapping,
    Product,
)
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.services.odoo_connector import OdooConnector, OdooConnectorError, relation_id, relation_name


MAX_RECORDS_PER_RUN = 50_000
INITIAL_HISTORY_DAYS = 365
INCREMENTAL_LOOKBACK_DAYS = 30
UNALLOCATED_WAREHOUSE_ID = ''
UNALLOCATED_WAREHOUSE_NAME = 'Chưa phân bổ kho'


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal('0')


def _timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_datetime(str(value or ''))
    if not parsed:
        return None
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def _date(value) -> datetime.date:
    parsed = _timestamp(value)
    return timezone.localdate(parsed) if parsed else timezone.localdate()


def _sku_for_product(product: dict | None, product_id: str, fallback_name: str = '') -> tuple[str, str]:
    product = product or {}
    sku = str(product.get('_supplyforge_sku') or product.get('default_code') or '').strip()
    if not sku:
        sku = f'odoo-{product_id}'
    return sku[:255], str(product.get('name') or fallback_name or sku)[:512]


class OdooMetricProjectionService:
    """Projects Odoo facts without altering the workspace's CSV data source.

    The projection rebuilds a bounded rolling window from Odoo's current
    source state. This handles modified and cancelled source documents without
    double-counting and makes each run safe to retry.
    """

    def __init__(self, connection: IntegrationConnection, connector: OdooConnector):
        self.connection = connection
        self.connector = connector

    def validate_and_discover(self) -> dict:
        return {
            'validation': self.connector.validate(),
            'discovery': self.connector.discover(),
            'mode': 'READ_ONLY',
            'refresh': '15_MINUTES_PULL',
        }

    def sync(self, run_type: str) -> dict:
        if not self.connection.external_company_id:
            raise OdooConnectorError('Hãy chọn một công ty Odoo trước khi bắt đầu đồng bộ.')
        if not self.connection.warehouse_ids:
            raise OdooConnectorError('Hãy chọn tối thiểu một kho Odoo trước khi bắt đầu đồng bộ.')

        validation = self.connector.validate()
        discovery = self.connector.discover()
        selected_warehouses = self._selected_warehouses(discovery['warehouses'])
        if not selected_warehouses:
            raise OdooConnectorError('Các kho đã chọn không còn tồn tại hoặc không thuộc công ty Odoo đã chọn.')

        if run_type == 'RECONCILIATION':
            reconciliation = self._reconcile(selected_warehouses)
            return {
                'validation': validation,
                'mode': 'READ_ONLY',
                'reconciliation': reconciliation,
                'selected_warehouse_count': len(selected_warehouses),
            }

        today = timezone.localdate()
        since_date = self._window_start(run_type, today)
        since_dt = timezone.make_aware(datetime.combine(since_date, datetime.min.time()))
        products = self.connector.read_products(self.connection.external_company_id, max_records=MAX_RECORDS_PER_RUN)
        product_by_id = self._index_products(products)
        sales_source, sales_lines = self.connector.read_sales_lines(
            self.connection.external_company_id,
            since_dt,
            max_records=MAX_RECORDS_PER_RUN,
        )
        try:
            receipt_moves = self.connector.read_receipt_moves(
                self.connection.external_company_id,
                since_dt,
                max_records=MAX_RECORDS_PER_RUN,
            )
            receipt_warning = ''
        except OdooConnectorError:
            # Receipt context is useful but must not make a sale/inventory sync fail.
            receipt_moves = []
            receipt_warning = 'Không thể đọc phiếu nhập kho; dữ liệu bán và tồn vẫn được cập nhật.'
        inventory_quants = self.connector.read_inventory(selected_warehouses, max_records=MAX_RECORDS_PER_RUN)

        metrics = self._aggregate_metrics(
            product_by_id=product_by_id,
            sales_lines=sales_lines,
            receipt_moves=receipt_moves,
            inventory_quants=inventory_quants,
            today=today,
        )
        mappings = self._upsert_mappings(products)
        event_counts = self._record_source_events(products, sales_lines, receipt_moves, inventory_quants)
        written = self._replace_window(since_date, metrics)
        CachePolicy.bump_workspace_version(self.connection.workspace_id)

        return {
            'validation': validation,
            'mode': 'READ_ONLY',
            'history_start': since_date.isoformat(),
            'history_days': (today - since_date).days + 1,
            'sales_source': sales_source,
            'products_read': len(products),
            'sales_lines_read': len(sales_lines),
            'receipt_moves_read': len(receipt_moves),
            'inventory_quants_read': len(inventory_quants),
            'daily_metrics_written': written,
            'mappings': mappings,
            'source_events': event_counts,
            'selected_warehouse_count': len(selected_warehouses),
            'warning': receipt_warning or None,
            'feature_refresh': 'CACHE_INVALIDATED_ONLY',
        }

    def _window_start(self, run_type: str, today):
        if run_type == 'INITIAL':
            return today - timedelta(days=INITIAL_HISTORY_DAYS)
        previous = self.connection.last_successful_sync_at
        if previous:
            return min(timezone.localdate(previous), today) - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)
        return today - timedelta(days=INCREMENTAL_LOOKBACK_DAYS)

    def _selected_warehouses(self, warehouses: list[dict]) -> list[dict]:
        selected = {str(value) for value in self.connection.warehouse_ids}
        company = str(self.connection.external_company_id)
        return [
            warehouse for warehouse in warehouses
            if str(warehouse.get('id')) in selected
            and relation_id(warehouse.get('company_id')) == company
        ]

    def _aggregate_metrics(self, *, product_by_id, sales_lines, receipt_moves, inventory_quants, today) -> dict:
        facts: dict[tuple[str, str, object], dict] = {}

        def fact_for(sku, product_id, name, warehouse_id, warehouse_name, metric_date):
            key = (sku, warehouse_id, metric_date)
            if key not in facts:
                product = product_by_id.get(product_id, {})
                facts[key] = {
                    'external_sku': sku,
                    'external_product_id': product_id,
                    'external_name': name,
                    'warehouse_id': warehouse_id,
                    'warehouse_name': warehouse_name,
                    'metric_date': metric_date,
                    'sales_quantity': Decimal('0'),
                    'returned_quantity': Decimal('0'),
                    'receipt_quantity': Decimal('0'),
                    'revenue': Decimal('0'),
                    'on_hand_quantity': None,
                    'unit_cost': _decimal(product.get('standard_price')) if product.get('standard_price') not in (None, False) else None,
                    'unit_price': _decimal(product.get('list_price')) if product.get('list_price') not in (None, False) else None,
                    'source_updated_at': None,
                    'source_metadata': {'source': 'odoo'},
                }
            return facts[key]

        for line in sales_lines:
            product_id = relation_id(line.get('product_id'))
            if not product_id:
                continue
            sku, name = _sku_for_product(product_by_id.get(product_id), product_id, relation_name(line.get('product_id')))
            item = fact_for(sku, product_id, name, UNALLOCATED_WAREHOUSE_ID, UNALLOCATED_WAREHOUSE_NAME, _date(line.get('_order_date')))
            quantity = _decimal(line.get(line.get('_quantity_field', 'qty')))
            revenue = _decimal(line.get(line.get('_revenue_field', 'price_subtotal')))
            if quantity < 0:
                item['returned_quantity'] += abs(quantity)
            else:
                item['sales_quantity'] += quantity
            item['revenue'] += revenue
            item['source_updated_at'] = max(filter(None, [item['source_updated_at'], _timestamp(line.get('write_date'))]), default=None)

        for move in receipt_moves:
            product_id = relation_id(move.get('product_id'))
            if not product_id:
                continue
            sku, name = _sku_for_product(product_by_id.get(product_id), product_id, relation_name(move.get('product_id')))
            item = fact_for(sku, product_id, name, UNALLOCATED_WAREHOUSE_ID, UNALLOCATED_WAREHOUSE_NAME, _date(move.get('date')))
            item['receipt_quantity'] += _decimal(move.get('quantity_done', move.get('quantity')))
            item['source_updated_at'] = max(filter(None, [item['source_updated_at'], _timestamp(move.get('write_date'))]), default=None)

        quant_totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal('0'))
        quant_updated: dict[tuple[str, str], datetime | None] = {}
        quant_names: dict[tuple[str, str], tuple[str, str, str]] = {}
        for quant in inventory_quants:
            product_id = relation_id(quant.get('product_id'))
            warehouse_id = str(quant.get('_warehouse_id') or '')
            if not product_id or not warehouse_id:
                continue
            sku, name = _sku_for_product(product_by_id.get(product_id), product_id, relation_name(quant.get('product_id')))
            key = (product_id, warehouse_id)
            quant_totals[key] += _decimal(quant.get('quantity')) - _decimal(quant.get('reserved_quantity'))
            quant_names[key] = (sku, name, str(quant.get('_warehouse_name') or ''))
            observed = _timestamp(quant.get('write_date'))
            quant_updated[key] = max(filter(None, [quant_updated.get(key), observed]), default=None)

        for (product_id, warehouse_id), quantity in quant_totals.items():
            sku, name, warehouse_name = quant_names[(product_id, warehouse_id)]
            item = fact_for(sku, product_id, name, warehouse_id, warehouse_name, today)
            item['on_hand_quantity'] = quantity
            item['source_updated_at'] = max(filter(None, [item['source_updated_at'], quant_updated[(product_id, warehouse_id)]]), default=None)

        return facts

    @staticmethod
    def _index_products(products: list[dict]) -> dict[str, dict]:
        """Avoid ambiguous daily-metric keys when an Odoo code is reused."""
        codes = Counter(str(item.get('default_code') or '').strip() for item in products)
        indexed = {}
        for item in products:
            product_id = str(item['id'])
            code = str(item.get('default_code') or '').strip()
            item = dict(item)
            item['_supplyforge_sku'] = code if code and codes[code] == 1 else f'odoo-{product_id}'
            indexed[product_id] = item
        return indexed

    def _upsert_mappings(self, products: list[dict]) -> dict:
        indexed_products = self._index_products(products)
        sku_details = {
            _sku_for_product(product, product_id)[0]: _sku_for_product(product, product_id)[1]
            for product_id, product in indexed_products.items()
        }
        existing = {
            item.external_sku: item
            for item in IntegrationSkuMapping.objects.filter(
                connection=self.connection,
                external_sku__in=sku_details,
            )
        }
        owner_id = str(self.connection.workspace.owner_id or '')
        canonical_products: dict[str, Product | None] = {}
        if owner_id and sku_details:
            # Exact matching is only safe when the merchant catalog contains
            # one unambiguous product for the source SKU.
            matches = Product.objects.filter(
                user_id=owner_id,
                item_sku__in=sku_details,
            ).only('id', 'item_sku')
            for product in matches:
                sku = str(product.item_sku or '')
                canonical_products[sku] = product if sku not in canonical_products else None
        updates = []
        creates = []
        auto_mapped = 0
        review = 0
        for sku, name in sku_details.items():
            current = existing.get(sku)
            matched_product = canonical_products.get(sku)
            if current:
                changed = False
                if current.external_name != name:
                    current.external_name = name
                    changed = True
                # A previously unresolved SKU can safely be auto-linked after
                # the matching CSV catalog has been imported.
                if current.status == IntegrationSkuMapping.STATUS_REVIEW and matched_product:
                    current.canonical_product = matched_product
                    current.canonical_sku = sku
                    current.status = IntegrationSkuMapping.STATUS_AUTO
                    current.mapping_method = IntegrationSkuMapping.METHOD_AUTO
                    current.confirmed_at = timezone.now()
                    current.ignored_at = None
                    changed = True
                    auto_mapped += 1
                if changed:
                    updates.append(current)
                continue
            matched = bool(matched_product)
            creates.append(IntegrationSkuMapping(
                connection=self.connection,
                external_sku=sku,
                external_name=name,
                canonical_product=matched_product,
                canonical_sku=sku if matched else '',
                status='AUTO_MAPPED' if matched else 'NEEDS_REVIEW',
                mapping_method=IntegrationSkuMapping.METHOD_AUTO if matched else '',
                confirmed_at=timezone.now() if matched else None,
            ))
            auto_mapped += int(matched)
            review += int(not matched)
        if updates:
            IntegrationSkuMapping.objects.bulk_update(updates, ['external_name', 'updated_at'], batch_size=1_000)
        if creates:
            IntegrationSkuMapping.objects.bulk_create(creates, batch_size=1_000, ignore_conflicts=True)
        return {'created': len(creates), 'auto_mapped': auto_mapped, 'needs_review': review}

    def _record_source_events(self, products, sales_lines, receipt_moves, inventory_quants) -> dict:
        """Store compact, PII-free source evidence with deterministic IDs."""
        counts = {'created': 0, 'duplicate': 0}
        records = [
            ('PRODUCT', item, str(item.get('id') or '')) for item in products
        ] + [
            ('SALE_LINE', item, str(item.get('id') or '')) for item in sales_lines
        ] + [
            ('RECEIPT_MOVE', item, str(item.get('id') or '')) for item in receipt_moves
        ] + [
            ('STOCK_QUANT', item, str(item.get('id') or '')) for item in inventory_quants
        ]
        candidates = []
        for event_type, record, source_id in records:
            if not source_id:
                continue
            updated = str(record.get('write_date') or record.get('_order_date') or record.get('date') or '')
            external_id = f'odoo:{event_type}:{source_id}:{updated}'[:255]
            payload = {
                'source_id': source_id,
                'sku': relation_id(record.get('product_id')) or str(record.get('default_code') or ''),
                'occurred_at': updated or None,
            }
            checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()
            candidates.append((external_id, IntegrationEvent(
                connection=self.connection,
                external_event_id=external_id,
                event_type=event_type,
                occurred_at=_timestamp(updated),
                payload=payload,
                payload_checksum=checksum,
                status='PROCESSED',
                processed_at=timezone.now(),
            )))
        existing_ids = set()
        for start in range(0, len(candidates), 1_000):
            external_ids = [value[0] for value in candidates[start:start + 1_000]]
            existing_ids.update(IntegrationEvent.objects.filter(
                connection=self.connection,
                external_event_id__in=external_ids,
            ).values_list('external_event_id', flat=True))
        new_events = [event for external_id, event in candidates if external_id not in existing_ids]
        if new_events:
            IntegrationEvent.objects.bulk_create(new_events, batch_size=1_000, ignore_conflicts=True)
        counts['created'] = len(new_events)
        counts['duplicate'] = len(candidates) - len(new_events)
        return counts

    def _replace_window(self, since_date, facts: dict) -> int:
        rows = []
        for values in facts.values():
            rows.append(IntegrationSkuDailyMetric(connection=self.connection, **values))
        with transaction.atomic():
            IntegrationSkuDailyMetric.objects.filter(connection=self.connection, metric_date__gte=since_date).delete()
            IntegrationSkuDailyMetric.objects.bulk_create(rows, batch_size=1_000)
        return len(rows)

    def _reconcile(self, selected_warehouses: list[dict]) -> dict:
        products = self.connector.read_products(self.connection.external_company_id, max_records=MAX_RECORDS_PER_RUN)
        product_by_id = {str(item['id']): item for item in products}
        inventory = self.connector.read_inventory(selected_warehouses, max_records=MAX_RECORDS_PER_RUN)
        observed = Decimal('0')
        for quant in inventory:
            observed += _decimal(quant.get('quantity')) - _decimal(quant.get('reserved_quantity'))
        projected = IntegrationSkuDailyMetric.objects.filter(
            connection=self.connection,
            metric_date=timezone.localdate(),
            on_hand_quantity__isnull=False,
        )
        projected_total = sum((item.on_hand_quantity or Decimal('0') for item in projected), Decimal('0'))
        return {
            'inventory_quants_read': len(inventory),
            'product_count': len(product_by_id),
            'odoo_on_hand_quantity': float(observed),
            'projected_on_hand_quantity': float(projected_total),
            'quantity_variance': float(observed - projected_total),
            'status': 'MATCHED' if observed == projected_total else 'VARIANCE_DETECTED',
        }
