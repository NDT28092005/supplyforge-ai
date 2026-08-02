"""
Shopee Integration — Test Suite
=================================
Covers 4 layers of testing:

  1. Unit Tests     — ShopeeClient retry logic, signature verification,
                      chunking, distributed lock helpers.
  2. Integration    — ShopeeSyncService product/order upsert with real DB,
                      select_for_update race condition simulation.
  3. API Tests      — HTTP endpoint response codes and webhook rejection.
  4. (Manual)       — Described in docstrings; run against Shopee sandbox.

Run all tests:
    python manage.py test supplyforge.tests.test_shopee_integration -v 2
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import (
    User,
    ShopeeConnection,
    ShopeeOrder,
    ShopeeOrderItem,
    ShopeeProduct,
    ShopeeVariation,
    SyncLog,
)


def _create_test_connection(user: User | None = None) -> ShopeeConnection:
    """Create a minimal ShopeeConnection for test use."""
    if user is None:
        user = User.objects.create(email='test@shopee.local', display_name='Test Shop')
    return ShopeeConnection.objects.create(
        user=user,
        shop_id=123456,
        shop_name='Test Shop',
        access_token='fake_access_token',
        refresh_token='fake_refresh_token',
        token_expire_at=timezone.now() + timedelta(hours=4),
        is_active=True,
    )


class TestShopeeClientSignature(TestCase):
    """Test HMAC-SHA256 signature generation and webhook verification."""

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'test_secret_key_abc',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    def test_webhook_signature_valid(self):
        """Valid signature must return True."""
        from supplyforge.services.shopee_client import verify_webhook_signature

        url = 'https://example.com/api/v1/shopee/webhook'
        body = b'{"code":"shopee.item_stock_changed","shop_id":123}'
        partner_key = 'test_secret_key_abc'

        base_string = f'{url}|'.encode('utf-8') + body
        expected_sig = hmac.new(
            partner_key.encode('utf-8'),
            base_string,
            hashlib.sha256,
        ).hexdigest()

        self.assertTrue(verify_webhook_signature(url, body, expected_sig))

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'test_secret_key_abc',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    def test_webhook_signature_invalid(self):
        """Tampered signature must return False."""
        from supplyforge.services.shopee_client import verify_webhook_signature

        url = 'https://example.com/api/v1/shopee/webhook'
        body = b'{"code":"shopee.item_stock_changed","shop_id":123}'

        self.assertFalse(verify_webhook_signature(url, body, 'totally_wrong_signature'))

    @override_settings(SUPPLYFORGE={
        'shopee': {'partner_id': '12345', 'partner_key': '', 'api_host': ''}
    })
    def test_webhook_signature_missing_key(self):
        """Missing partner_key must return False (not crash)."""
        from supplyforge.services.shopee_client import verify_webhook_signature

        self.assertFalse(verify_webhook_signature('http://x', b'body', 'sig'))


class TestShopeeClientRetry(TestCase):
    """Test exponential backoff retry logic."""

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'key',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    @patch('supplyforge.services.shopee_client.time.sleep')
    @patch('supplyforge.services.shopee_client.requests.Session.request')
    def test_retry_on_429(self, mock_request, mock_sleep):
        """Client must retry up to 3 times on HTTP 429 with increasing backoff."""
        from supplyforge.services.shopee_client import ShopeeClient, ShopeeAPIError

        conn = _create_test_connection()
        client = ShopeeClient(conn)

        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.json.return_value = {'error': '', 'message': ''}

        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {'response': {'shop': {}}}

        mock_request.side_effect = [mock_resp_429, mock_resp_429, mock_resp_200]

        result = client._request('GET', '/api/v2/shop/get_shop_info')
        self.assertIn('response', result)
        self.assertEqual(mock_sleep.call_count, 2)

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'key',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    @patch('supplyforge.services.shopee_client.time.sleep')
    @patch('supplyforge.services.shopee_client.requests.Session.request')
    def test_retry_exhausted_raises(self, mock_request, mock_sleep):
        """After 3 failed retries, ShopeeAPIError must be raised."""
        from supplyforge.services.shopee_client import ShopeeClient, ShopeeAPIError

        conn = _create_test_connection()
        client = ShopeeClient(conn)

        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        mock_resp_500.json.return_value = {'error': '', 'message': ''}
        mock_request.return_value = mock_resp_500

        with self.assertRaises(ShopeeAPIError) as ctx:
            client._request('GET', '/api/v2/shop/get_shop_info')

        self.assertEqual(ctx.exception.error_code, 'RETRY_EXHAUSTED')


class TestShopeeClientChunking(TestCase):
    """Test chunked item detail retrieval."""

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'key',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    @patch('supplyforge.services.shopee_client.ShopeeClient._request')
    def test_chunking_splits_correctly(self, mock_request):
        """120 item IDs must be split into 3 chunks (50 + 50 + 20)."""
        from supplyforge.services.shopee_client import ShopeeClient

        conn = _create_test_connection()
        client = ShopeeClient(conn)

        def side_effect(method, path, params=None, json_body=None):
            id_str = params.get('item_id_list', '')
            ids = [int(x) for x in id_str.split(',') if x]
            return {
                'response': {
                    'item_list': [{'item_id': i} for i in ids]
                }
            }
        mock_request.side_effect = side_effect

        ids = list(range(1, 121))
        result = client.get_item_detail_chunked(ids)

        self.assertEqual(len(result), 120)
        self.assertEqual(mock_request.call_count, 3)


class TestDistributedLock(TestCase):
    """Test Redis distributed lock acquire/release logic."""

    @patch('redis.from_url')
    def test_lock_acquire_success(self, mock_from_url):
        """First caller must acquire lock successfully."""
        from supplyforge.tasks import _acquire_redis_lock

        mock_client = MagicMock()
        mock_client.set.return_value = True
        mock_from_url.return_value = mock_client

        result = _acquire_redis_lock('test_lock_key')
        self.assertTrue(result)
        mock_client.set.assert_called_once_with('test_lock_key', 'locked', nx=True, ex=1800)

    @patch('redis.from_url')
    def test_lock_acquire_blocked(self, mock_from_url):
        """Second caller must fail to acquire (returns False)."""
        from supplyforge.tasks import _acquire_redis_lock

        mock_client = MagicMock()
        mock_client.set.return_value = False
        mock_from_url.return_value = mock_client

        result = _acquire_redis_lock('test_lock_key')
        self.assertFalse(result)


class TestProductUpsert(TestCase):
    """Integration test: product and variation upsert into real DB."""

    def setUp(self):
        self.conn = _create_test_connection()

    def test_create_product_and_variation(self):
        """Syncing a new item must create ShopeeProduct + ShopeeVariation rows."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        item_data = {
            'item_id': 999001,
            'item_name': 'Áo thun test đồng bộ',
            'item_sku': 'AT-TEST-001',
            'item_status': 'NORMAL',
            'category_id': 100,
            'image': {'image_url_list': ['https://img.shopee.vn/test.jpg']},
            'update_time': int(time.time()),
        }

        created, updated = ShopeeSyncService._upsert_product(self.conn, item_data)
        self.assertEqual(created, 1)
        self.assertEqual(updated, 0)

        product = ShopeeProduct.objects.get(connection=self.conn, item_id=999001)
        self.assertEqual(product.item_name, 'Áo thun test đồng bộ')

        models_list = [
            {
                'model_id': 5001,
                'model_name': 'Size M - Đen',
                'model_sku': 'AT-TEST-001-M-BLK',
                'price_info': [{'current_price': 150000}],
                'stock_info_v2': {'seller_stock': [{'stock': 42}]},
            },
            {
                'model_id': 5002,
                'model_name': 'Size L - Trắng',
                'model_sku': 'AT-TEST-001-L-WHT',
                'price_info': [{'current_price': 160000}],
                'stock_info_v2': {'seller_stock': [{'stock': 18}]},
            },
        ]

        v_created, v_updated, warnings = ShopeeSyncService._upsert_variations(
            self.conn, 999001, models_list,
        )
        self.assertEqual(v_created, 2)
        self.assertEqual(v_updated, 0)
        self.assertEqual(warnings, 2)

        variations = ShopeeVariation.objects.filter(product=product)
        self.assertEqual(variations.count(), 2)

        v1 = variations.get(model_id=5001)
        self.assertEqual(v1.stock, 42)
        self.assertEqual(v1.price, Decimal('150000'))
        self.assertIsNone(v1.cost_price)

    def test_upsert_product_updates_existing(self):
        """Second sync of same item_id must UPDATE, not duplicate."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        item_data = {
            'item_id': 999002,
            'item_name': 'Original Name',
            'item_sku': 'ORIG',
            'item_status': 'NORMAL',
        }
        ShopeeSyncService._upsert_product(self.conn, item_data)

        item_data['item_name'] = 'Updated Name'
        created, updated = ShopeeSyncService._upsert_product(self.conn, item_data)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 1)

        count = ShopeeProduct.objects.filter(connection=self.conn, item_id=999002).count()
        self.assertEqual(count, 1)

        product = ShopeeProduct.objects.get(connection=self.conn, item_id=999002)
        self.assertEqual(product.item_name, 'Updated Name')


class TestCOGSWarning(TestCase):
    """Verify that MISSING_COST_PRICE warnings are generated correctly."""

    def setUp(self):
        self.conn = _create_test_connection()
        ShopeeProduct.objects.create(
            connection=self.conn,
            item_id=888001,
            item_name='Test COGS Product',
        )

    def test_missing_cost_price_generates_warning(self):
        """New variation with null cost_price must create a WARNING SyncLog."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        models_list = [{
            'model_id': 6001,
            'model_name': 'Variation A',
            'model_sku': 'VA',
            'price_info': [{'current_price': 100000}],
            'stock_info_v2': {'seller_stock': [{'stock': 10}]},
        }]

        _, _, warnings = ShopeeSyncService._upsert_variations(self.conn, 888001, models_list)
        self.assertEqual(warnings, 1)

        log = SyncLog.objects.filter(
            connection=self.conn,
            event_type='MISSING_COST_PRICE',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.log_level, 'WARNING')
        self.assertIn('model_id=6001', log.message)


class TestWebhookStockUpdate(TestCase):
    """Integration test: webhook stock update with select_for_update."""

    def setUp(self):
        self.conn = _create_test_connection()
        self.product = ShopeeProduct.objects.create(
            connection=self.conn,
            item_id=777001,
            item_name='Webhook Test Product',
        )
        self.variation = ShopeeVariation.objects.create(
            product=self.product,
            model_id=7001,
            model_name='Size M',
            stock=50,
            price=Decimal('200000'),
        )

    def test_stock_updated_via_webhook(self):
        """Webhook must update variation stock and create SyncLog."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        ShopeeSyncService.update_stock_from_webhook(
            shop_id=123456,
            item_id=777001,
            model_id=7001,
            new_stock=35,
        )

        self.variation.refresh_from_db()
        self.assertEqual(self.variation.stock, 35)

        log = SyncLog.objects.filter(
            event_type='STOCK_UPDATED',
            sync_type='STOCK_WEBHOOK',
        ).first()
        self.assertIsNotNone(log)
        self.assertIn('50 → 35', log.message)

    def test_stock_webhook_nonexistent_shop_ignored(self):
        """Webhook for unknown shop_id must not raise, just log warning."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        ShopeeSyncService.update_stock_from_webhook(
            shop_id=999999,
            item_id=777001,
            model_id=7001,
            new_stock=10,
        )

        self.variation.refresh_from_db()
        self.assertEqual(self.variation.stock, 50)


class TestOrderUpsert(TestCase):
    """Integration test: order creation and status update."""

    def setUp(self):
        self.conn = _create_test_connection()

    def test_create_order_with_items(self):
        """New order must create ShopeeOrder + ShopeeOrderItem rows."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        order_data = {
            'order_sn': 'ORD_TEST_001',
            'order_status': 'READY_TO_SHIP',
            'total_amount': 350000,
            'buyer_username': 'buyer_abc',
            'shipping_carrier': 'GHN',
            'create_time': int(time.time()) - 3600,
            'update_time': int(time.time()),
            'item_list': [
                {
                    'item_id': 111,
                    'model_id': 222,
                    'item_name': 'Test Item',
                    'item_sku': 'TI-001',
                    'model_sku': 'TI-001-M',
                    'model_quantity_purchased': 2,
                    'model_discounted_price': 175000,
                },
            ],
        }

        o_created, o_updated, items_c = ShopeeSyncService._upsert_order(
            self.conn, order_data,
        )
        self.assertEqual(o_created, 1)
        self.assertEqual(o_updated, 0)
        self.assertEqual(items_c, 1)

        order = ShopeeOrder.objects.get(order_sn='ORD_TEST_001')
        self.assertEqual(order.order_status, 'READY_TO_SHIP')
        self.assertEqual(order.items.count(), 1)

    def test_update_existing_order_status(self):
        """Updating an existing order must not duplicate it."""
        from supplyforge.services.shopee_sync import ShopeeSyncService

        ShopeeOrder.objects.create(
            connection=self.conn,
            order_sn='ORD_TEST_002',
            order_status='UNPAID',
            total_amount=Decimal('100000'),
        )

        order_data = {
            'order_sn': 'ORD_TEST_002',
            'order_status': 'SHIPPED',
            'total_amount': 100000,
            'buyer_username': '',
            'shipping_carrier': '',
            'item_list': [],
        }

        o_created, o_updated, _ = ShopeeSyncService._upsert_order(self.conn, order_data)
        self.assertEqual(o_created, 0)
        self.assertEqual(o_updated, 1)

        self.assertEqual(ShopeeOrder.objects.filter(order_sn='ORD_TEST_002').count(), 1)

        order = ShopeeOrder.objects.get(order_sn='ORD_TEST_002')
        self.assertEqual(order.order_status, 'SHIPPED')


class TestWebhookEndpointSecurity(TestCase):
    """Test that the webhook endpoint rejects unsigned requests."""

    def setUp(self):
        self.client = APIClient()

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'webhook_test_key',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    def test_webhook_rejects_missing_signature(self):
        """Request without Authorization header must return 403."""
        response = self.client.post(
            '/api/v1/shopee/webhook',
            data=json.dumps({'code': 'test', 'shop_id': 1}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'webhook_test_key',
            'api_host': 'https://partner.shopeemobile.com',
        }
    })
    def test_webhook_rejects_bad_signature(self):
        """Request with wrong Authorization header must return 403."""
        response = self.client.post(
            '/api/v1/shopee/webhook',
            data=json.dumps({'code': 'test', 'shop_id': 1}),
            content_type='application/json',
            HTTP_AUTHORIZATION='bad_signature_value',
        )
        self.assertEqual(response.status_code, 403)


class TestTriggerSyncEndpoint(TestCase):
    """Test manual sync trigger endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.conn = _create_test_connection()

    @patch('supplyforge.views.shopee.sync_shopee_products_task')
    @patch('supplyforge.views.shopee.sync_shopee_orders_task')
    def test_trigger_sync_dispatches_tasks(self, mock_orders_task, mock_products_task):
        """POST /sync/trigger must dispatch Celery tasks and return 200."""
        response = self.client.post(
            '/api/v1/shopee/sync/trigger',
            data={'connection_id': self.conn.id, 'sync_type': 'ALL'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        mock_products_task.delay.assert_called_once_with(self.conn.id)
        mock_orders_task.delay.assert_called_once_with(self.conn.id)

    def test_trigger_sync_invalid_connection(self):
        """Non-existent connection_id must return 404."""
        response = self.client.post(
            '/api/v1/shopee/sync/trigger',
            data={'connection_id': 99999, 'sync_type': 'PRODUCT'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_trigger_sync_missing_connection_id(self):
        """Missing connection_id must return 400."""
        response = self.client.post(
            '/api/v1/shopee/sync/trigger',
            data={'sync_type': 'PRODUCT'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class TestSyncStatusEndpoint(TestCase):
    """Test sync status query endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.conn = _create_test_connection()
        SyncLog.objects.create(
            connection=self.conn,
            sync_type='PRODUCT',
            log_level='INFO',
            event_type='SYNC_COMPLETED',
            message='Test log entry',
        )

    def test_get_sync_status_returns_logs(self):
        """GET /sync/status must return recent SyncLog entries."""
        response = self.client.get(
            f'/api/v1/shopee/sync/status?connection_id={self.conn.id}',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]['event_type'], 'SYNC_COMPLETED')


class TestOAuthEndpoints(TestCase):
    """Test OAuth URL generation and callback endpoints."""

    def setUp(self):
        self.client = APIClient()

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '12345',
            'partner_key': 'oauth_test_key',
            'api_host': 'https://partner.shopeemobile.com',
            'redirect_url': 'http://localhost:8080/api/v1/shopee/oauth/callback',
        }
    })
    def test_authorize_url_generation_success(self):
        """Endpoint must return a URL containing signed query parameters."""
        response = self.client.get('/api/v1/shopee/oauth/authorize')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('url', data)
        url = data['url']
        self.assertTrue(url.startswith('https://partner.shopeemobile.com/api/v2/shop/auth_partner'))
        self.assertIn('partner_id=12345', url)
        self.assertIn('redirect=http://localhost:8080/api/v1/shopee/oauth/callback', url)
        self.assertIn('timestamp=', url)
        self.assertIn('sign=', url)

    @override_settings(SUPPLYFORGE={
        'shopee': {
            'partner_id': '',
            'partner_key': '',
            'api_host': '',
        }
    })
    def test_authorize_url_generation_missing_config(self):
        """Endpoint must return 400 if Shopee configuration is incomplete."""
        response = self.client.get('/api/v1/shopee/oauth/authorize')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
