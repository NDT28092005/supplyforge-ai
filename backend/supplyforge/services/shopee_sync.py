"""
Shopee Integration — Application Services
============================================
Clean Architecture service layer sitting between Controllers (views)
and the data access / external API layers.

Key design decisions:
  - All DB writes use bulk_create / bulk_update for performance.
  - select_for_update() is applied when mutating stock or order status
    to prevent race conditions between webhooks and polling tasks.
  - Every variation synced without a cost_price generates a WARNING-level
    SyncLog entry with event_type='MISSING_COST_PRICE' so that downstream
    modules can prompt the user to supply COGS data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from supplyforge.models import (
    ShopeeConnection,
    ShopeeOrder,
    ShopeeOrderItem,
    ShopeeProduct,
    ShopeeVariation,
    SyncLog,
)
from supplyforge.services.shopee_client import ShopeeClient

logger = logging.getLogger(__name__)


class ShopeeSyncService:
    """Orchestrates sync operations between Shopee API and local database."""

    # ──────────────────────────────────────────────────────────────
    # Product + Variation Sync
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def sync_products(
        connection_id: int,
        time_from: int,
        time_to: int,
    ) -> dict[str, int]:
        """
        Delta-sync products and their variations from Shopee.
        """
        connection = ShopeeConnection.objects.get(id=connection_id)
        client = ShopeeClient(connection)

        sync_log = SyncLog.objects.create(
            connection=connection,
            sync_type='PRODUCT',
            log_level='INFO',
            event_type='SYNC_STARTED',
            message=f'Delta sync products [{time_from} → {time_to}]',
            started_at=timezone.now(),
        )

        stats: dict[str, int] = {
            'products_created': 0,
            'products_updated': 0,
            'variations_created': 0,
            'variations_updated': 0,
            'cost_warnings': 0,
        }

        try:
            # ── Step 1: Collect all item_ids via paginated list endpoint ──
            all_item_ids: list[int] = []
            offset = 0
            has_more = True

            while has_more:
                resp = client.get_item_list(
                    offset=offset,
                    page_size=100,
                    update_time_from=time_from,
                    update_time_to=time_to,
                )
                items = resp.get('response', {}).get('item', [])
                all_item_ids.extend(item['item_id'] for item in items)
                has_more = resp.get('response', {}).get('has_next_page', False)
                offset += len(items)

            if not all_item_ids:
                sync_log.log_level = 'INFO'
                sync_log.event_type = 'SYNC_COMPLETED'
                sync_log.message = 'No updated products found in the time window.'
                sync_log.finished_at = timezone.now()
                sync_log.save()
                return stats

            # ── Step 2: Chunk and fetch item details (max 50 per request) ──
            item_details = client.get_item_detail_chunked(all_item_ids)

            # ── Step 3 & 4: Upsert products and variations ──
            for item_data in item_details:
                p_created, p_updated = ShopeeSyncService._upsert_product(
                    connection, item_data,
                )
                stats['products_created'] += p_created
                stats['products_updated'] += p_updated

                # Fetch variation details per item
                model_resp = client.get_model_list(item_data['item_id'])
                models_list = model_resp.get('response', {}).get('model', [])

                v_created, v_updated, v_warnings = ShopeeSyncService._upsert_variations(
                    connection, item_data['item_id'], models_list,
                )
                stats['variations_created'] += v_created
                stats['variations_updated'] += v_updated
                stats['cost_warnings'] += v_warnings

            # ── Finalize sync log ──
            sync_log.log_level = 'INFO'
            sync_log.event_type = 'SYNC_COMPLETED'
            sync_log.message = f'Products synced successfully. Stats: {stats}'
            sync_log.records_processed = len(item_details)
            sync_log.records_created = stats['products_created'] + stats['variations_created']
            sync_log.records_updated = stats['products_updated'] + stats['variations_updated']
            sync_log.finished_at = timezone.now()
            sync_log.save()

        except Exception as exc:
            sync_log.log_level = 'ERROR'
            sync_log.event_type = 'SYNC_FAILED'
            sync_log.message = str(exc)
            sync_log.finished_at = timezone.now()
            sync_log.save()
            logger.exception('[ShopeeSyncService] Product sync failed for connection=%d', connection_id)
            raise

        return stats

    @staticmethod
    def _upsert_product(
        connection: ShopeeConnection,
        item_data: dict[str, Any],
    ) -> tuple[int, int]:
        """
        Create or update a single ShopeeProduct row.
        Returns (created_count, updated_count) — always (1,0) or (0,1).
        """
        item_id = item_data['item_id']
        defaults = {
            'item_name': item_data.get('item_name', ''),
            'item_sku': item_data.get('item_sku', ''),
            'item_status': item_data.get('item_status', 'NORMAL'),
            'category_id': item_data.get('category_id'),
            'image_url': (
                item_data.get('image', {}).get('image_url_list', [''])[0]
                if item_data.get('image') else ''
            ),
            'shopee_updated_at': (
                datetime.utcfromtimestamp(item_data['update_time'])
                if item_data.get('update_time') else None
            ),
        }

        _, created = ShopeeProduct.objects.update_or_create(
            connection=connection,
            item_id=item_id,
            defaults=defaults,
        )
        return (1, 0) if created else (0, 1)

    @staticmethod
    def _upsert_variations(
        connection: ShopeeConnection,
        item_id: int,
        models_list: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        """
        Bulk upsert variations for a given product.
        Returns (created_count, updated_count, cost_warning_count).
        """
        try:
            product = ShopeeProduct.objects.get(
                connection=connection, item_id=item_id,
            )
        except ShopeeProduct.DoesNotExist:
            logger.warning('[ShopeeSyncService] Product item_id=%d not found, skipping variations.', item_id)
            return (0, 0, 0)

        created_count = 0
        updated_count = 0
        cost_warning_count = 0

        for model_data in models_list:
            model_id = model_data.get('model_id', 0)
            price_info = model_data.get('price_info', [{}])
            current_price = Decimal(str(price_info[0].get('current_price', 0))) if price_info else Decimal('0')
            stock_info = model_data.get('stock_info_v2', {})
            current_stock = stock_info.get('seller_stock', [{}])
            stock_qty = current_stock[0].get('stock', 0) if current_stock else 0

            defaults = {
                'model_name': model_data.get('model_name', ''),
                'model_sku': model_data.get('model_sku', ''),
                'price': current_price,
                'stock': stock_qty,
            }

            variation, created = ShopeeVariation.objects.update_or_create(
                product=product,
                model_id=model_id,
                defaults=defaults,
            )

            if created:
                created_count += 1
                # ── COGS Warning: cost_price is always NULL from Shopee ──
                if variation.cost_price is None:
                    cost_warning_count += 1
                    SyncLog.objects.create(
                        connection=connection,
                        sync_type='PRODUCT',
                        log_level='WARNING',
                        event_type='MISSING_COST_PRICE',
                        message=(
                            f'Variation model_id={model_id} (item_id={item_id}) '
                            f'synced without cost_price. '
                            f'User action required: supply COGS manually.'
                        ),
                    )
            else:
                updated_count += 1

        return (created_count, updated_count, cost_warning_count)

    # ──────────────────────────────────────────────────────────────
    # Order Sync
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def sync_orders(
        connection_id: int,
        time_from: int,
        time_to: int,
    ) -> dict[str, int]:
        """
        Delta-sync orders from Shopee.  Uses cursor-based pagination.
        """
        connection = ShopeeConnection.objects.get(id=connection_id)
        client = ShopeeClient(connection)

        sync_log = SyncLog.objects.create(
            connection=connection,
            sync_type='ORDER',
            log_level='INFO',
            event_type='SYNC_STARTED',
            message=f'Delta sync orders [{time_from} → {time_to}]',
            started_at=timezone.now(),
        )

        stats: dict[str, int] = {
            'orders_created': 0,
            'orders_updated': 0,
            'items_created': 0,
        }

        try:
            # ── Paginate order list ──
            all_order_sns: list[str] = []
            cursor = ''
            has_more = True

            while has_more:
                resp = client.get_order_list(
                    time_from=time_from,
                    time_to=time_to,
                    cursor=cursor,
                )
                order_list = resp.get('response', {}).get('order_list', [])
                all_order_sns.extend(o['order_sn'] for o in order_list)
                has_more = resp.get('response', {}).get('more', False)
                cursor = resp.get('response', {}).get('next_cursor', '')

            if not all_order_sns:
                sync_log.event_type = 'SYNC_COMPLETED'
                sync_log.message = 'No updated orders found in the time window.'
                sync_log.finished_at = timezone.now()
                sync_log.save()
                return stats

            # ── Fetch details in chunks of 50 ──
            for i in range(0, len(all_order_sns), 50):
                chunk = all_order_sns[i : i + 50]
                detail_resp = client.get_order_detail(chunk)
                orders = detail_resp.get('response', {}).get('order_list', [])

                for order_data in orders:
                    o_created, o_updated, items_c = ShopeeSyncService._upsert_order(
                        connection, order_data,
                    )
                    stats['orders_created'] += o_created
                    stats['orders_updated'] += o_updated
                    stats['items_created'] += items_c

            sync_log.event_type = 'SYNC_COMPLETED'
            sync_log.message = f'Orders synced successfully. Stats: {stats}'
            sync_log.records_processed = len(all_order_sns)
            sync_log.records_created = stats['orders_created']
            sync_log.records_updated = stats['orders_updated']
            sync_log.finished_at = timezone.now()
            sync_log.save()

        except Exception as exc:
            sync_log.log_level = 'ERROR'
            sync_log.event_type = 'SYNC_FAILED'
            sync_log.message = str(exc)
            sync_log.finished_at = timezone.now()
            sync_log.save()
            logger.exception('[ShopeeSyncService] Order sync failed for connection=%d', connection_id)
            raise

        return stats

    @staticmethod
    @transaction.atomic
    def _upsert_order(
        connection: ShopeeConnection,
        order_data: dict[str, Any],
    ) -> tuple[int, int, int]:
        """
        Create or update a single order.  Wrapped in @transaction.atomic.
        Uses select_for_update() for race condition avoidance.
        """
        order_sn = order_data['order_sn']

        defaults = {
            'order_status': order_data.get('order_status', 'UNPAID'),
            'total_amount': Decimal(str(order_data.get('total_amount', 0))),
            'buyer_username': order_data.get('buyer_username', ''),
            'shipping_carrier': order_data.get('shipping_carrier', ''),
            'order_created_at': (
                datetime.utcfromtimestamp(order_data['create_time'])
                if order_data.get('create_time') else None
            ),
            'order_updated_at': (
                datetime.utcfromtimestamp(order_data['update_time'])
                if order_data.get('update_time') else None
            ),
        }

        # ── Try to lock existing row first (race condition prevention) ──
        existing = (
            ShopeeOrder.objects
            .select_for_update()
            .filter(order_sn=order_sn)
            .first()
        )

        items_created = 0

        if existing:
            for field, value in defaults.items():
                setattr(existing, field, value)
            existing.save()
            return (0, 1, 0)
        else:
            order = ShopeeOrder.objects.create(
                connection=connection,
                order_sn=order_sn,
                **defaults,
            )

            items_data = order_data.get('item_list', [])
            order_items = [
                ShopeeOrderItem(
                    order=order,
                    item_id=item.get('item_id', 0),
                    model_id=item.get('model_id'),
                    item_name=item.get('item_name', ''),
                    item_sku=item.get('item_sku', ''),
                    model_sku=item.get('model_sku', ''),
                    quantity=item.get('model_quantity_purchased', 0),
                    price=Decimal(str(item.get('model_discounted_price', 0))),
                )
                for item in items_data
            ]
            if order_items:
                ShopeeOrderItem.objects.bulk_create(order_items)
                items_created = len(order_items)

            return (1, 0, items_created)

    # ──────────────────────────────────────────────────────────────
    # Webhook Handlers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def update_stock_from_webhook(
        shop_id: int,
        item_id: int,
        model_id: int,
        new_stock: int,
    ) -> None:
        """Handle a stock-changed webhook push from Shopee."""
        try:
            connection = ShopeeConnection.objects.get(shop_id=shop_id, is_active=True)
        except ShopeeConnection.DoesNotExist:
            logger.warning('[Webhook] No active connection for shop_id=%d', shop_id)
            return

        try:
            product = ShopeeProduct.objects.get(
                connection=connection, item_id=item_id,
            )
        except ShopeeProduct.DoesNotExist:
            logger.warning('[Webhook] Product item_id=%d not found for shop_id=%d', item_id, shop_id)
            return

        variation = (
            ShopeeVariation.objects
            .select_for_update()
            .filter(product=product, model_id=model_id)
            .first()
        )

        if variation is None:
            logger.warning(
                '[Webhook] Variation model_id=%d not found under item_id=%d',
                model_id, item_id,
            )
            return

        old_stock = variation.stock
        variation.stock = new_stock
        variation.save(update_fields=['stock', 'updated_at'])

        SyncLog.objects.create(
            connection=connection,
            sync_type='STOCK_WEBHOOK',
            log_level='INFO',
            event_type='STOCK_UPDATED',
            message=(
                f'Variation model_id={model_id}: stock {old_stock} → {new_stock} '
                f'(via webhook)'
            ),
            records_updated=1,
        )

    @staticmethod
    @transaction.atomic
    def update_order_status_from_webhook(
        shop_id: int,
        order_sn: str,
        new_status: str,
    ) -> None:
        """Handle an order-status-update webhook push from Shopee."""
        try:
            connection = ShopeeConnection.objects.get(shop_id=shop_id, is_active=True)
        except ShopeeConnection.DoesNotExist:
            logger.warning('[Webhook] No active connection for shop_id=%d', shop_id)
            return

        order = (
            ShopeeOrder.objects
            .select_for_update()
            .filter(order_sn=order_sn)
            .first()
        )

        if order is None:
            logger.warning('[Webhook] Order order_sn=%s not found', order_sn)
            return

        old_status = order.order_status
        order.order_status = new_status
        order.save(update_fields=['order_status', 'updated_at'])

        SyncLog.objects.create(
            connection=connection,
            sync_type='ORDER_WEBHOOK',
            log_level='INFO',
            event_type='ORDER_STATUS_UPDATED',
            message=f'Order {order_sn}: status {old_status} → {new_status} (via webhook)',
            records_updated=1,
        )
