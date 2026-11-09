"""Regression coverage for evidence-first execution and financial guardrails."""

from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from supplyforge.models import (
    ActionPlanRecord, InventoryRecord, PurchaseOrder, Sku, Supplier,
    SupplierReturnRequest, User, Workspace,
)
from supplyforge.services.action_execution import ActionExecutionService
from supplyforge.services.pricing_guardrails import PricingGuardrailService
from supplyforge.services.procurement_planning import ProcurementPlanningService
from supplyforge.services.supplier_return import SupplierReturnService
from supplyforge.views.operations_views import (
    PurchaseOrderListCreateView, SupplierReturnApprovalView, SupplierReturnRequestView,
)


class BusinessOperationsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='business-operations@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(
            name='Business operations', slug='business-operations', owner=self.owner,
        )
        self.factory = APIRequestFactory()

    def _request(self, view, payload):
        request = self.factory.post('/api/v1/procurement/', payload, format='json')
        request.tenant_context_validated = True
        request.workspace_id = self.workspace.id
        request.user_role = User.ROLE_OWNER
        request.user_email = self.owner.email
        return view.as_view()(request)

    def test_required_task_needs_evidence_or_explicit_skip_reason(self):
        plan = ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, campaign_name='Discount test', sku='SKU-OPS-1',
            strategy='DISCOUNT', owner='Owner', start_date=date.today(), due_date=date.today(),
        )
        tasks = ActionExecutionService.create_checklist(plan)
        self.assertGreater(len(tasks), 0)
        with self.assertRaisesRegex(ValueError, 'bằng chứng'):
            ActionExecutionService.update_task(
                task=tasks[0], status='COMPLETED', actor='owner@example.test',
            )
        evidence = ActionExecutionService.add_evidence(
            task=tasks[0], evidence_type='LINK', title='Giá đã cập nhật',
            reference_url='https://merchant.example/campaign', note='', actor='owner@example.test',
        )
        self.assertEqual(evidence.task_id, tasks[0].id)
        ActionExecutionService.update_task(task=tasks[0], status='COMPLETED', actor='owner@example.test')
        tasks[0].refresh_from_db()
        self.assertEqual(tasks[0].status, 'COMPLETED')
        with self.assertRaisesRegex(ValueError, 'lý do'):
            ActionExecutionService.update_task(task=tasks[1], status='SKIPPED', actor='owner@example.test', skipped_reason='')

    def test_pricing_and_procurement_withhold_when_governed_inputs_are_missing(self):
        pricing = PricingGuardrailService.build(
            workspace_id=self.workspace.id, sku='SKU-MISSING', channel='Shopee', duration_days=14,
        )
        self.assertEqual(pricing['status'], 'DATA_UNAVAILABLE')
        self.assertEqual(pricing['options'], [])
        self.assertIn('Tồn kho đã xác thực', pricing['missing_inputs'])

        procurement = ProcurementPlanningService.plan_sku(
            workspace_id=self.workspace.id, sku='SKU-MISSING', horizon_days=90,
        )
        self.assertEqual(procurement['status'], 'DATA_UNAVAILABLE')
        self.assertIn('Điều khoản nhà cung cấp', procurement['missing_inputs'])

    def test_pricing_does_not_choose_an_arbitrary_warehouse(self):
        sku = Sku.objects.create(workspace=self.workspace, original_name='SKU-MULTI', normalized_name='SKU-MULTI')
        for warehouse in ('WH-HCM', 'WH-HN'):
            InventoryRecord.objects.create(
                sku=sku, canonical_sku='SKU-MULTI', warehouse_code=warehouse,
                record_date=date.today(), quantity=10, available_quantity=10,
                cost_price=70_000, selling_price=100_000, lifecycle_status='ACTIVE',
                as_of_verified=True,
            )
        pricing = PricingGuardrailService.build(
            workspace_id=self.workspace.id, sku='SKU-MULTI', channel='Web', duration_days=14,
        )
        self.assertEqual(pricing['status'], 'DATA_UNAVAILABLE')
        self.assertIn('Phạm vi kho cụ thể (SKU đang có ở nhiều kho)', pricing['missing_inputs'])
        self.assertEqual(pricing['lineage']['available_warehouses'], ['WH-HCM', 'WH-HN'])

    def test_historical_warehouse_does_not_create_false_current_scope_conflict(self):
        sku = Sku.objects.create(workspace=self.workspace, original_name='SKU-MOVED', normalized_name='SKU-MOVED')
        InventoryRecord.objects.create(
            sku=sku, canonical_sku='SKU-MOVED', warehouse_code='WH-HN',
            record_date=date(2026, 1, 1), quantity=10, available_quantity=10,
            cost_price=70_000, selling_price=100_000, lifecycle_status='ACTIVE', as_of_verified=True,
        )
        InventoryRecord.objects.create(
            sku=sku, canonical_sku='SKU-MOVED', warehouse_code='WH-HCM',
            record_date=date(2026, 2, 1), quantity=10, available_quantity=10,
            cost_price=70_000, selling_price=100_000, lifecycle_status='ACTIVE', as_of_verified=True,
        )

        inventory, warehouses = ProcurementPlanningService._latest_inventory(self.workspace.id, 'SKU-MOVED')
        self.assertEqual(inventory.warehouse_code, 'WH-HCM')
        self.assertEqual(warehouses, ['WH-HCM'])
        _, price_warehouses = PricingGuardrailService._inventory(self.workspace.id, 'SKU-MOVED')
        self.assertEqual(price_warehouses, ['WH-HCM'])

    def test_purchase_order_invalid_payload_never_persists_header_or_lines(self):
        supplier = Supplier.objects.create(workspace=self.workspace, name='NCC A')
        response = self._request(PurchaseOrderListCreateView, {
            'supplier_id': supplier.id,
            'po_number': 'PO-INVALID',
            'ordered_at': '2026-10-01',
            'expected_receipt_date': '2026-09-30',
            'lines': [{'sku': 'SKU-1', 'ordered_quantity': 10}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PurchaseOrder.objects.filter(workspace=self.workspace, po_number='PO-INVALID').exists())

    def test_supplier_return_validates_workspace_before_creating_record(self):
        supplier = Supplier.objects.create(workspace=self.workspace, name='NCC A')
        foreign_owner = User.objects.create(email='other-operations@example.test', status=User.STATUS_ACTIVE, is_email_verified=True, role=User.ROLE_OWNER)
        foreign_workspace = Workspace.objects.create(name='Other operations', slug='other-operations', owner=foreign_owner)
        foreign_supplier = Supplier.objects.create(workspace=foreign_workspace, name='NCC B')
        foreign_po = PurchaseOrder.objects.create(workspace=foreign_workspace, supplier=foreign_supplier, po_number='PO-OTHER')
        response = self._request(SupplierReturnRequestView, {
            'supplier_id': supplier.id,
            'purchase_order_id': foreign_po.id,
            'sku': 'SKU-1',
            'quantity': 1,
            'reason': 'Hàng bị lỗi khi nhận',
            'idempotency_key': 'cross-workspace-return',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SupplierReturnRequest.objects.filter(workspace=self.workspace).exists())

    def test_supplier_return_idempotency_key_cannot_mask_different_request(self):
        supplier = Supplier.objects.create(workspace=self.workspace, name='NCC A')
        payload = {
            'supplier_id': supplier.id,
            'sku': 'SKU-1',
            'quantity': 1,
            'reason': 'Hàng bị lỗi khi nhận',
            'idempotency_key': 'return-request-1',
        }
        response = self._request(SupplierReturnRequestView, payload)
        self.assertEqual(response.status_code, 201)
        response = self._request(SupplierReturnRequestView, {**payload, 'quantity': 2})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SupplierReturnRequest.objects.filter(workspace=self.workspace).count(), 1)

    @patch('supplyforge.tasks.submit_supplier_return_request.delay')
    def test_supplier_return_approval_is_owner_controlled_and_idempotent_for_workers(self, delay):
        supplier = Supplier.objects.create(workspace=self.workspace, name='NCC A')
        record = SupplierReturnRequest.objects.create(
            workspace=self.workspace, supplier=supplier, canonical_sku='SKU-1', quantity=1,
            reason='Hàng bị lỗi khi nhận', idempotency_key='return-approval-1',
            status=SupplierReturnRequest.STATUS_PENDING_APPROVAL,
        )
        request = self.factory.post('/api/v1/procurement/supplier-returns/approve/', {}, format='json')
        request.tenant_context_validated = True
        request.workspace_id = self.workspace.id
        request.user_role = User.ROLE_OPERATOR
        denied = SupplierReturnApprovalView.as_view()(request, request_id=record.id)
        self.assertEqual(denied.status_code, 403)

        request = self.factory.post('/api/v1/procurement/supplier-returns/approve/', {}, format='json')
        request.tenant_context_validated = True
        request.workspace_id = self.workspace.id
        request.user_role = User.ROLE_OWNER
        request.user_email = self.owner.email
        approved = SupplierReturnApprovalView.as_view()(request, request_id=record.id)
        self.assertEqual(approved.status_code, 200)
        delay.assert_called_once_with(record.id)

        record.refresh_from_db()
        record.status = SupplierReturnRequest.STATUS_SUBMITTED
        record.save(update_fields=['status'])
        self.assertEqual(SupplierReturnService.submit(record.id)['status'], 'SUBMITTED')
