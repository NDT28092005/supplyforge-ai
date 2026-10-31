"""Read-only XML-RPC adapter for Odoo Online and self-hosted deployments."""

from __future__ import annotations

import socket
import xmlrpc.client
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import urlparse


class OdooConnectorError(RuntimeError):
    """A safe, user-actionable failure while reading the merchant's Odoo."""


class _TimeoutTransport(xmlrpc.client.Transport):
    timeout = 20

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    timeout = 20

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


def relation_id(value) -> str:
    """Return the stable identifier from Odoo's many2one representation."""
    if isinstance(value, (list, tuple)) and value:
        return str(value[0])
    if value not in (None, False, ''):
        return str(value)
    return ''


def relation_name(value) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return str(value[1] or '')
    return ''


class OdooConnector:
    """Odoo service-account client with an explicit read-only method surface."""

    PAGE_SIZE = 500
    IN_CLAUSE_SIZE = 500

    def __init__(self, base_url: str, database: str, username: str, api_key: str):
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {'http', 'https'}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise OdooConnectorError('Odoo URL phải là HTTP(S) hợp lệ, không chứa thông tin xác thực trong URL.')
        path = parsed.path.rstrip('/')
        self.base_url = f'{parsed.scheme}://{parsed.netloc}{path}'
        self.scheme = parsed.scheme
        self.database = database
        self.username = username
        self.api_key = api_key
        self._uid: int | None = None

    @property
    def _transport(self):
        return _TimeoutSafeTransport() if self.scheme == 'https' else _TimeoutTransport()

    def _proxy(self, service: str):
        return xmlrpc.client.ServerProxy(
            f'{self.base_url}/xmlrpc/2/{service}',
            transport=self._transport,
            allow_none=True,
        )

    def _authenticate(self) -> int:
        common = self._proxy('common')
        try:
            uid = common.authenticate(self.database, self.username, self.api_key, {})
        except (OSError, socket.timeout, xmlrpc.client.Error) as exc:
            raise OdooConnectorError('Không thể kết nối hoặc xác thực Odoo.') from exc
        if not uid:
            raise OdooConnectorError('Odoo từ chối thông tin xác thực hoặc tài khoản dịch vụ không hoạt động.')
        self._uid = int(uid)
        return self._uid

    def validate(self) -> dict:
        uid = self._authenticate()
        try:
            version = self._proxy('common').version()
        except (OSError, socket.timeout, xmlrpc.client.Error) as exc:
            raise OdooConnectorError('Không thể đọc phiên bản máy chủ Odoo.') from exc
        return {'uid': uid, 'server_version': str(version.get('server_version', 'unknown'))}

    def execute_kw(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None):
        """Only permits Odoo read methods, protecting against write-back by design."""
        if method not in {'search', 'search_read', 'read', 'fields_get'}:
            raise OdooConnectorError('Adapter Odoo chỉ hỗ trợ thao tác đọc dữ liệu.')
        uid = self._uid or self._authenticate()
        try:
            return self._proxy('object').execute_kw(
                self.database,
                uid,
                self.api_key,
                model,
                method,
                args or [],
                kwargs or {},
            )
        except (OSError, socket.timeout, xmlrpc.client.Error) as exc:
            raise OdooConnectorError(f'Không thể đọc mô hình Odoo {model}.') from exc

    def search_read(self, model: str, domain: list, fields: list[str], *, limit: int = PAGE_SIZE, offset: int = 0, order: str = 'id asc') -> list[dict]:
        return self.execute_kw(
            model,
            'search_read',
            [domain],
            {'fields': fields, 'limit': min(max(1, limit), self.PAGE_SIZE), 'offset': max(0, offset), 'order': order},
        )

    def iter_search_read(self, model: str, domain: list, fields: list[str], *, max_records: int = 50_000, order: str = 'id asc') -> Iterator[dict]:
        """Bounded pagination prevents a single tenant run exhausting a worker."""
        offset = 0
        yielded = 0
        while yielded < max_records:
            page_size = min(self.PAGE_SIZE, max_records - yielded)
            page = self.search_read(model, domain, fields, limit=page_size, offset=offset, order=order)
            if not page:
                return
            for item in page:
                yield item
                yielded += 1
            if len(page) < page_size:
                return
            offset += len(page)

    def discover(self) -> dict:
        companies = self.search_read('res.company', [], ['id', 'name'])
        warehouses = self.search_read('stock.warehouse', [], ['id', 'name', 'company_id', 'lot_stock_id'])
        return {'companies': companies, 'warehouses': warehouses}

    def read_products(self, company_id: str, *, max_records: int = 50_000) -> list[dict]:
        domain = [('active', '=', True)]
        if company_id:
            domain.append(('company_id', 'in', [False, int(company_id)]))
        return list(self.iter_search_read(
            'product.product', domain,
            ['id', 'default_code', 'name', 'list_price', 'standard_price', 'write_date'],
            max_records=max_records,
        ))

    def read_inventory(self, warehouses: list[dict], *, max_records: int = 50_000) -> list[dict]:
        """Return current available stock per selected warehouse without reservations."""
        result: list[dict] = []
        remaining = max_records
        for warehouse in warehouses:
            root_location = relation_id(warehouse.get('lot_stock_id'))
            warehouse_id = str(warehouse.get('id') or '')
            if not root_location or not warehouse_id or remaining <= 0:
                continue
            rows = list(self.iter_search_read(
                'stock.quant', [('location_id', 'child_of', int(root_location))],
                ['id', 'product_id', 'quantity', 'reserved_quantity', 'write_date'],
                max_records=remaining,
            ))
            for row in rows:
                row['_warehouse_id'] = warehouse_id
                row['_warehouse_name'] = str(warehouse.get('name') or '')
            result.extend(rows)
            remaining -= len(rows)
        return result

    def read_sales_lines(self, company_id: str, since: datetime, *, max_records: int = 50_000) -> tuple[str, list[dict]]:
        """Read paid POS lines first, then delivered sales orders as a fallback.

        Both sources omit customer fields. A deployment must grant access to
        at least one source for sales features to be available.
        """
        since_text = since.strftime('%Y-%m-%d %H:%M:%S')
        company_domain = [('company_id', '=', int(company_id))] if company_id else []
        pos_read_succeeded = False
        try:
            order_domain = company_domain + [('date_order', '>=', since_text), ('state', 'in', ['paid', 'done', 'invoiced'])]
            orders = list(self.iter_search_read(
                'pos.order', order_domain, ['id', 'date_order', 'state', 'write_date'], max_records=max_records,
            ))
            order_dates = {str(item['id']): item.get('date_order') for item in orders}
            if order_dates:
                return 'POS', self._read_order_lines('pos.order.line', order_dates, 'qty', 'price_subtotal_incl', max_records)
            pos_read_succeeded = True
        except OdooConnectorError:
            pass
        try:
            order_domain = company_domain + [('date_order', '>=', since_text), ('state', 'in', ['sale', 'done'])]
            orders = list(self.iter_search_read(
                'sale.order', order_domain, ['id', 'date_order', 'state', 'write_date'], max_records=max_records,
            ))
            order_dates = {str(item['id']): item.get('date_order') for item in orders}
            return 'SALES_ORDER', self._read_order_lines('sale.order.line', order_dates, 'qty_delivered', 'price_subtotal', max_records)
        except OdooConnectorError:
            if pos_read_succeeded:
                return 'POS', []
            raise

    def _read_order_lines(self, model: str, order_dates: dict[str, str], quantity_field: str, revenue_field: str, max_records: int) -> list[dict]:
        records: list[dict] = []
        order_ids = list(order_dates.keys())
        for start in range(0, len(order_ids), self.IN_CLAUSE_SIZE):
            ids = [int(value) for value in order_ids[start:start + self.IN_CLAUSE_SIZE]]
            if not ids:
                continue
            rows = self.iter_search_read(
                model, [('order_id', 'in', ids)],
                ['id', 'order_id', 'product_id', quantity_field, revenue_field, 'write_date'],
                max_records=max(0, max_records - len(records)),
            )
            for row in rows:
                row['_order_date'] = order_dates.get(relation_id(row.get('order_id')))
                row['_quantity_field'] = quantity_field
                row['_revenue_field'] = revenue_field
                records.append(row)
                if len(records) >= max_records:
                    return records
        return records

    def read_receipt_moves(self, company_id: str, since: datetime, *, max_records: int = 50_000) -> list[dict]:
        """Read completed incoming stock movements, when Inventory is available."""
        incoming_types = self.search_read('stock.picking.type', [('code', '=', 'incoming')], ['id', 'company_id'])
        type_ids = [int(item['id']) for item in incoming_types if not company_id or relation_id(item.get('company_id')) == str(company_id)]
        if not type_ids:
            return []
        domain = [
            ('state', '=', 'done'),
            ('date', '>=', since.strftime('%Y-%m-%d %H:%M:%S')),
            ('picking_type_id', 'in', type_ids),
        ]
        try:
            return list(self.iter_search_read(
                'stock.move', domain,
                ['id', 'product_id', 'quantity_done', 'date', 'write_date', 'picking_type_id'],
                max_records=max_records,
            ))
        except OdooConnectorError:
            # Odoo 17 renamed the effective quantity field on some models.
            return list(self.iter_search_read(
                'stock.move', domain,
                ['id', 'product_id', 'quantity', 'date', 'write_date', 'picking_type_id'],
                max_records=max_records,
            ))
