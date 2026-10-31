"""Contract and projection tests for the provider-neutral ERP integration layer."""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationSkuDailyMetric,
    IntegrationSkuMapping,
    IntegrationSkuMappingAudit,
    IntegrationOperationalRiskAssessment,
    Product,
    User,
    Workspace,
    WorkspaceEntitlement,
    WorkspaceMember,
)
from supplyforge.services.integration_security import encrypt_credentials
from supplyforge.services.integration_sync import OdooMetricProjectionService
from supplyforge.services.operational_analytics import OdooOperationalAnalyticsService
from supplyforge.views.auth import generate_access_token


class ERPIntegrationApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(
            email='erp-owner@example.com', role='OWNER', status=User.STATUS_ACTIVE, is_email_verified=True,
        )
        self.workspace = Workspace.objects.create(name='ERP Workspace', slug='erp-workspace', owner=self.owner)
        WorkspaceMember.objects.create(workspace=self.workspace, user=self.owner, role='OWNER')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generate_access_token(self.owner, self.workspace.id)}')
        WorkspaceEntitlement.objects.create(
            workspace=self.workspace,
            feature_code=WorkspaceEntitlement.FEATURE_ERP_INTEGRATIONS,
            is_enabled=True,
        )

    def _connection(self, *, active=False):
        return IntegrationConnection.objects.create(
            workspace=self.workspace,
            provider='ODOO',
            display_name='Odoo main',
            status='ACTIVE' if active else 'DRAFT',
            base_url='https://erp.example.test',
            external_database='production',
            credential_encrypted=encrypt_credentials({
                'database': 'production', 'username': 'service@example.test',
                'api_key': 'not-returned', 'webhook_secret': 'webhook-secret',
            }),
        )

    def test_feature_entitlement_is_required(self):
        WorkspaceEntitlement.objects.filter(workspace=self.workspace).update(is_enabled=False)
        response = self.client.get('/api/v1/integrations/connections/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['error']['code'], 'FEATURE_NOT_ENTITLED')

    def test_owner_can_create_connection_without_exposing_credentials(self):
        response = self.client.post('/api/v1/integrations/connections/', {
            'provider': 'ODOO', 'display_name': 'Odoo Operations',
            'base_url': 'https://erp.example.test/', 'database': 'production',
            'username': 'read-only@example.test', 'api_key': 'super-secret',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertNotIn('api_key', json.dumps(response.data))
        self.assertIn('webhook', response.data)
        connection = IntegrationConnection.objects.get(id=response.data['id'])
        self.assertNotIn('super-secret', connection.credential_encrypted)
        self.assertEqual(connection.base_url, 'https://erp.example.test')

    @patch('supplyforge.tasks.run_integration_sync.delay')
    def test_unauthorized_workspace_cannot_queue_other_connection(self, mock_delay):
        connection = self._connection()
        outsider = User.objects.create(
            email='erp-outsider@example.com', role='OWNER', status=User.STATUS_ACTIVE, is_email_verified=True,
        )
        outsider_workspace = Workspace.objects.create(name='Other', slug='erp-other', owner=outsider)
        WorkspaceMember.objects.create(workspace=outsider_workspace, user=outsider, role='OWNER')
        WorkspaceEntitlement.objects.create(
            workspace=outsider_workspace,
            feature_code=WorkspaceEntitlement.FEATURE_ERP_INTEGRATIONS,
            is_enabled=True,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generate_access_token(outsider, outsider_workspace.id)}')
        response = self.client.post(f'/api/v1/integrations/connections/{connection.id}/runs/validate/', {}, format='json')
        self.assertEqual(response.status_code, 404)
        mock_delay.assert_not_called()

    def test_mapping_list_is_paginated_and_workspace_scoped(self):
        connection = self._connection()
        IntegrationSkuMapping.objects.bulk_create([
            IntegrationSkuMapping(connection=connection, external_sku=f'SKU-{index:02}', external_name='Test')
            for index in range(14)
        ])
        response = self.client.get(f'/api/v1/integrations/connections/{connection.id}/sku-mappings/?page=2&pageSize=10')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['items']), 4)
        self.assertEqual(response.data['pagination']['totalItems'], 14)
        self.assertEqual(response.data['summary']['NEEDS_REVIEW'], 14)

    def _product(self, sku='CAN-001', name='Canonical product'):
        return Product.objects.create(
            id=f'product-{sku.lower()}',
            user_id=str(self.owner.id),
            third_party_id=f'catalog-{sku.lower()}',
            item_sku=sku,
            product_name=name,
        )

    def test_mapping_confirmation_uses_workspace_product_and_records_audit(self):
        connection = self._connection()
        product = self._product()
        mapping = IntegrationSkuMapping.objects.create(
            connection=connection, external_sku='ODOO-001', external_name='Odoo product',
        )
        response = self.client.patch(
            f'/api/v1/integrations/connections/{connection.id}/sku-mappings/{mapping.id}/',
            {
                'action': 'CONFIRM',
                'canonical_product_id': product.id,
                'expected_updated_at': mapping.updated_at.isoformat(),
                'note': 'Đã kiểm tra mã hàng.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        mapping.refresh_from_db()
        self.assertEqual(mapping.status, IntegrationSkuMapping.STATUS_CONFIRMED)
        self.assertEqual(mapping.canonical_product_id, product.id)
        self.assertEqual(mapping.canonical_sku, product.item_sku)
        self.assertEqual(mapping.mapping_method, IntegrationSkuMapping.METHOD_MANUAL)
        self.assertEqual(IntegrationSkuMappingAudit.objects.get(mapping=mapping).action, 'CONFIRMED')

        legacy_response = self.client.patch(
            f'/api/v1/integrations/connections/{connection.id}/sku-mappings/{mapping.id}/',
            {'canonical_sku': 'MADE-UP'}, format='json',
        )
        self.assertEqual(legacy_response.status_code, 400)
        mapping.refresh_from_db()
        self.assertEqual(mapping.canonical_product_id, product.id)

    def test_mapping_prevents_duplicate_target_and_supports_reopen(self):
        connection = self._connection()
        product = self._product('CAN-002')
        first = IntegrationSkuMapping.objects.create(connection=connection, external_sku='ODOO-101')
        second = IntegrationSkuMapping.objects.create(connection=connection, external_sku='ODOO-102')
        path = f'/api/v1/integrations/connections/{connection.id}/sku-mappings/'

        confirmed = self.client.patch(f'{path}{first.id}/', {
            'action': 'CONFIRM', 'canonical_product_id': product.id,
            'expected_updated_at': first.updated_at.isoformat(),
        }, format='json')
        self.assertEqual(confirmed.status_code, 200)

        conflicting = self.client.patch(f'{path}{second.id}/', {
            'action': 'CONFIRM', 'canonical_product_id': product.id,
            'expected_updated_at': second.updated_at.isoformat(),
        }, format='json')
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.data['error']['code'], 'CANONICAL_PRODUCT_ALREADY_LINKED')

        first.refresh_from_db()
        ignored = self.client.patch(f'{path}{first.id}/', {
            'action': 'IGNORE', 'expected_updated_at': first.updated_at.isoformat(),
            'note': 'Không còn quản lý tại kênh này.',
        }, format='json')
        self.assertEqual(ignored.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.status, IntegrationSkuMapping.STATUS_IGNORED)
        self.assertIsNone(first.canonical_product)

        reopened = self.client.patch(f'{path}{first.id}/', {
            'action': 'REOPEN', 'expected_updated_at': first.updated_at.isoformat(),
        }, format='json')
        self.assertEqual(reopened.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.status, IntegrationSkuMapping.STATUS_REVIEW)
        self.assertEqual(IntegrationSkuMappingAudit.objects.filter(mapping=first).count(), 3)

    def test_mapping_candidates_are_scoped_to_the_workspace_catalog(self):
        connection = self._connection()
        product = self._product('CAN-SEARCH', 'Vietnam Warehouse Product')
        Product.objects.create(
            id='product-outsider', user_id='not-this-owner', third_party_id='outside-catalog',
            item_sku='CAN-SEARCH-OUTSIDE', product_name='Outsider product',
        )
        response = self.client.get(
            f'/api/v1/integrations/connections/{connection.id}/sku-candidates/?q=CAN-SEARCH',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['items'], [{
            'id': product.id,
            'item_sku': 'CAN-SEARCH',
            'product_name': 'Vietnam Warehouse Product',
            'stock': None,
            'price': None,
        }])

    def test_operational_source_uses_only_linked_odoo_skus_and_replaces_capital_snapshot(self):
        """Live Odoo facts must not leak into CSV results or include unmapped SKUs."""
        connection = self._connection(active=True)
        critical_product = self._product('CAN-CRITICAL', 'Critical product')
        moving_product = self._product('CAN-MOVING', 'Moving product')
        critical = IntegrationSkuMapping.objects.create(
            connection=connection, external_sku='ODOO-CRITICAL', canonical_product=critical_product,
            canonical_sku=critical_product.item_sku, status=IntegrationSkuMapping.STATUS_CONFIRMED,
        )
        moving = IntegrationSkuMapping.objects.create(
            connection=connection, external_sku='ODOO-MOVING', canonical_product=moving_product,
            canonical_sku=moving_product.item_sku, status=IntegrationSkuMapping.STATUS_AUTO,
        )
        today = timezone.localdate()
        IntegrationSkuDailyMetric.objects.bulk_create([
            IntegrationSkuDailyMetric(connection=connection, external_sku='ODOO-CRITICAL', warehouse_id='10', metric_date=today, on_hand_quantity=10, unit_cost=25),
            IntegrationSkuDailyMetric(connection=connection, external_sku='ODOO-MOVING', warehouse_id='', metric_date=today, sales_quantity=20),
            IntegrationSkuDailyMetric(connection=connection, external_sku='ODOO-MOVING', warehouse_id='10', metric_date=today, on_hand_quantity=1, unit_cost=20),
            # This source SKU deliberately has facts but no approved mapping.
            IntegrationSkuDailyMetric(connection=connection, external_sku='ODOO-UNMAPPED', warehouse_id='10', metric_date=today, on_hand_quantity=999, unit_cost=99),
        ])

        result = OdooOperationalAnalyticsService.refresh(connection)
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(IntegrationOperationalRiskAssessment.objects.filter(snapshot__connection=connection).count(), 2)
        self.assertEqual(
            IntegrationOperationalRiskAssessment.objects.get(mapping=critical).risk_class,
            'CRITICAL',
        )
        self.assertEqual(
            IntegrationOperationalRiskAssessment.objects.get(mapping=moving).risk_class,
            'LOW_RISK',
        )
        # A retry replaces the same materialised source instead of creating a
        # second capital dataset or double-counting the warehouse inventory.
        retry = OdooOperationalAnalyticsService.refresh(connection)
        self.assertEqual(retry['status'], 'READY')

        risk = self.client.get(f'/api/v1/integrations/connections/{connection.id}/operational-risk/')
        summary = self.client.get(f'/api/v1/integrations/connections/{connection.id}/operational-risk/summary/')
        capital = self.client.get(f'/api/v1/integrations/connections/{connection.id}/operational-capital/latest/')
        dashboard = self.client.get(f'/api/v1/integrations/connections/{connection.id}/operational-dashboard/summary/')
        self.assertEqual(risk.status_code, 200)
        self.assertEqual(risk.data['total_count'], 2)
        self.assertEqual(summary.data['critical'], 1)
        self.assertEqual(risk.data['source']['coverage']['scored_skus'], 2)
        self.assertEqual(capital.status_code, 200)
        self.assertEqual(capital.data['total_skus'], 2)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.data['riskCapitalByClassVnd'], {
            'CRITICAL': 250.0,
            'HIGH_RISK': 0.0,
            'MEDIUM_RISK': 0.0,
            'LOW_RISK': 20.0,
        })

    @patch('supplyforge.tasks.process_integration_event.delay')
    def test_signed_webhook_is_idempotent(self, mock_delay):
        connection = self._connection(active=True)
        body = json.dumps({
            'event_id': 'event-100', 'event_type': 'stock.changed',
            'occurred_at': timezone.now().isoformat(),
            'payload': {'sku': 'SKU-100', 'buyer_email': 'must-not-be-stored@example.test'},
        }).encode('utf-8')
        timestamp = timezone.now().isoformat()
        signature = hmac.new(b'webhook-secret', timestamp.encode('utf-8') + b'.' + body, hashlib.sha256).hexdigest()
        path = f'/api/v1/integrations/webhooks/{connection.webhook_token}/'
        response = self.client.post(path, data=body, content_type='application/json', HTTP_X_SUPPLYFORGE_TIMESTAMP=timestamp, HTTP_X_SUPPLYFORGE_SIGNATURE=signature)
        duplicate = self.client.post(path, data=body, content_type='application/json', HTTP_X_SUPPLYFORGE_TIMESTAMP=timestamp, HTTP_X_SUPPLYFORGE_SIGNATURE=signature)

        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()['duplicate'])
        self.assertEqual(duplicate.status_code, 202)
        self.assertTrue(duplicate.json()['duplicate'])
        self.assertEqual(IntegrationEvent.objects.filter(connection=connection).count(), 1)
        event = IntegrationEvent.objects.get(connection=connection)
        self.assertEqual(event.payload, {'sku': 'SKU-100'})
        mock_delay.assert_called_once()

    def test_invalid_webhook_signature_is_rejected(self):
        connection = self._connection(active=True)
        response = self.client.post(
            f'/api/v1/integrations/webhooks/{connection.webhook_token}/',
            data=b'{"event_id":"bad","event_type":"stock.changed"}',
            content_type='application/json',
            HTTP_X_SUPPLYFORGE_TIMESTAMP=timezone.now().isoformat(),
            HTTP_X_SUPPLYFORGE_SIGNATURE='invalid',
        )
        self.assertEqual(response.status_code, 403)


class FakeOdooConnector:
    def validate(self):
        return {'uid': 7, 'server_version': '17.0'}

    def discover(self):
        return {
            'companies': [{'id': 1, 'name': 'Merchant Co'}],
            'warehouses': [{'id': 10, 'name': 'HCM', 'company_id': [1, 'Merchant Co'], 'lot_stock_id': [50, 'HCM Stock']}],
        }

    def read_products(self, company_id, max_records):
        return [{'id': 101, 'default_code': 'BEAN-01', 'name': 'Arabica Bean', 'list_price': 100000, 'standard_price': 60000, 'write_date': '2026-10-01 10:00:00'}]

    def read_sales_lines(self, company_id, since, max_records):
        return 'POS', [
            {'id': 501, 'product_id': [101, 'Arabica Bean'], 'qty': 3, 'price_subtotal_incl': 300000,
             '_order_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'), '_quantity_field': 'qty', '_revenue_field': 'price_subtotal_incl', 'write_date': '2026-10-02 10:00:00'},
            {'id': 502, 'product_id': [101, 'Arabica Bean'], 'qty': -1, 'price_subtotal_incl': -100000,
             '_order_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'), '_quantity_field': 'qty', '_revenue_field': 'price_subtotal_incl', 'write_date': '2026-10-02 10:00:00'},
        ]

    def read_receipt_moves(self, company_id, since, max_records):
        return [{'id': 601, 'product_id': [101, 'Arabica Bean'], 'quantity_done': 12, 'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'), 'write_date': '2026-10-01 10:00:00'}]

    def read_inventory(self, warehouses, max_records):
        return [{'id': 701, 'product_id': [101, 'Arabica Bean'], 'quantity': 20, 'reserved_quantity': 2, 'write_date': '2026-10-03 10:00:00', '_warehouse_id': '10', '_warehouse_name': 'HCM'}]


class ERPProjectionTests(TestCase):
    def setUp(self):
        owner = User.objects.create(email='projection@example.com', role='OWNER', status=User.STATUS_ACTIVE, is_email_verified=True)
        self.workspace = Workspace.objects.create(name='Projection', slug='erp-projection', owner=owner)
        self.connection = IntegrationConnection.objects.create(
            workspace=self.workspace,
            provider='ODOO', display_name='Odoo', status='ACTIVE', base_url='https://erp.example.test',
            external_database='production', external_company_id='1', external_company_name='Merchant Co',
            warehouse_ids=['10'], warehouse_names=['HCM'], credential_encrypted='unused',
            last_successful_sync_at=timezone.now() - timedelta(days=1),
        )

    def test_projection_rebuilds_window_without_double_counting(self):
        service = OdooMetricProjectionService(self.connection, FakeOdooConnector())
        first = service.sync('INITIAL')
        second = service.sync('INITIAL')

        self.assertEqual(first['daily_metrics_written'], second['daily_metrics_written'])
        self.assertEqual(IntegrationSkuDailyMetric.objects.filter(connection=self.connection).count(), first['daily_metrics_written'])
        sales = IntegrationSkuDailyMetric.objects.get(connection=self.connection, external_sku='BEAN-01', warehouse_id='')
        inventory = IntegrationSkuDailyMetric.objects.get(connection=self.connection, external_sku='BEAN-01', warehouse_id='10')
        self.assertEqual(sales.sales_quantity, Decimal('3'))
        self.assertEqual(sales.returned_quantity, Decimal('1'))
        self.assertEqual(sales.revenue, Decimal('200000'))
        self.assertEqual(inventory.on_hand_quantity, Decimal('18'))
        self.assertEqual(IntegrationSkuMapping.objects.filter(connection=self.connection, status='NEEDS_REVIEW').count(), 1)
        self.assertGreater(second['source_events']['duplicate'], 0)
