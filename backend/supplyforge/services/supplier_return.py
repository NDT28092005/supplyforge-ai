"""Approved, idempotent supplier-return write-back to Odoo."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from supplyforge.models import IntegrationConnection, SupplierReturnRequest, WorkspaceEntitlement
from supplyforge.services.integration_security import decrypt_credentials, entitlement_active
from supplyforge.services.odoo_connector import OdooConnector, OdooConnectorError, relation_id


class SupplierReturnService:
    @staticmethod
    def submit(request_id: int) -> dict:
        with transaction.atomic():
            request = SupplierReturnRequest.objects.select_for_update().select_related('workspace').get(id=request_id)
            if request.status == SupplierReturnRequest.STATUS_COMPLETED:
                return {'status': 'COMPLETED', 'external_return_id': request.external_return_id, 'idempotent': True}
            if request.status == SupplierReturnRequest.STATUS_SUBMITTED:
                # A duplicate Celery delivery must not create a second Odoo
                # return while the first worker is still handling it.
                return {'status': 'SUBMITTED', 'external_return_id': request.external_return_id, 'idempotent': True}
            if request.status != SupplierReturnRequest.STATUS_APPROVED:
                raise ValueError('Chỉ yêu cầu hoàn trả đã được phê duyệt mới có thể gửi sang Odoo.')
            if not entitlement_active(request.workspace_id, WorkspaceEntitlement.FEATURE_SUPPLIER_RETURN_WRITE):
                raise ValueError('Workspace chưa được cấp quyền ghi phiếu hoàn trả sang Odoo.')
            if not request.source_picking_external_id or not request.external_product_id:
                raise ValueError('Cần có mã phiếu nhập và mã sản phẩm Odoo nguồn để tạo phiếu hoàn trả.')
            connection = IntegrationConnection.objects.filter(
                workspace_id=request.workspace_id, provider='ODOO', status='ACTIVE',
            ).order_by('created_at').first()
            if not connection:
                raise ValueError('Không có kết nối Odoo đang hoạt động để gửi phiếu hoàn trả.')
            request.status = SupplierReturnRequest.STATUS_SUBMITTED
            request.last_error = ''
            request.save(update_fields=['status', 'last_error', 'updated_at'])

        try:
            credentials = decrypt_credentials(connection.credential_encrypted)
            connector = OdooConnector(connection.base_url, credentials['database'], credentials['username'], credentials['api_key'])
            picking_id, product_id = int(request.source_picking_external_id), int(request.external_product_id)
            moves = connector.search_read(
                'stock.move', [('picking_id', '=', picking_id), ('product_id', '=', product_id)],
                ['id', 'product_id', 'quantity_done', 'product_uom_qty'], limit=20,
            )
            move = next((row for row in moves if relation_id(row.get('product_id')) == str(product_id)), None)
            if not move:
                raise OdooConnectorError('Không tìm thấy dòng hàng phù hợp trong phiếu nhập Odoo nguồn.')
            wizard_id = connector.execute_supplier_return_write('stock.return.picking', 'create', [{
                'picking_id': picking_id,
                'product_return_moves': [(0, 0, {
                    'product_id': product_id, 'quantity': float(request.quantity), 'move_id': int(move['id']),
                })],
            }])
            result = connector.execute_supplier_return_write('stock.return.picking', 'create_returns', [[wizard_id]])
            external_return_id = str((result or {}).get('res_id') or (result or {}).get('id') or wizard_id)
        except Exception as exc:
            SupplierReturnRequest.objects.filter(id=request_id).update(status='FAILED', last_error=str(exc)[:512], updated_at=timezone.now())
            raise

        SupplierReturnRequest.objects.filter(id=request_id).update(
            status='COMPLETED', external_return_id=external_return_id, last_error='', updated_at=timezone.now(),
        )
        return {'status': 'COMPLETED', 'external_return_id': external_return_id, 'idempotent': False}
