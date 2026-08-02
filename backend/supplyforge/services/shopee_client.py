"""
Shopee Open API SDK Client
============================
Thin wrapper around ``requests`` that handles:
  1. HMAC-SHA256 request signing (required by Shopee Open Platform).
  2. Automatic token refresh on 401 responses.
  3. Exponential Backoff Retry for 429 (Rate Limit) and 5xx errors.
  4. Chunked batch item detail retrieval (max 50 item_ids per request).

Usage:
    client = ShopeeClient(connection)
    items  = client.get_item_list(update_time_from=..., update_time_to=...)
    detail = client.get_item_detail_chunked(item_ids=[...])
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0
ITEM_DETAIL_CHUNK_SIZE = 50  # Shopee hard limit per request


class ShopeeAPIError(Exception):
    """Raised when the Shopee API returns a non-recoverable error."""

    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(f'Shopee API [{status_code}] {error_code}: {message}')


class ShopeeClient:
    """
    Low-level HTTP client for Shopee Open API v2.

    Parameters
    ----------
    connection : ShopeeConnection model instance
        Provides shop_id, access_token, refresh_token.
    """

    def __init__(self, connection: Any) -> None:
        cfg = settings.SUPPLYFORGE.get('shopee', {})
        self.partner_id: int = int(cfg.get('partner_id', 0))
        self.partner_key: str = cfg.get('partner_key', '')
        self.api_host: str = cfg.get('api_host', 'https://partner.shopeemobile.com')

        self.connection = connection
        self.shop_id: int = connection.shop_id
        self.access_token: str = connection.access_token
        self.refresh_token: str = connection.refresh_token
        self.session = requests.Session()

    # ──────────────────────────────────────────────────────────────
    # Authentication helpers
    # ──────────────────────────────────────────────────────────────

    def _generate_sign(self, api_path: str, timestamp: int) -> str:
        """
        Generate HMAC-SHA256 signature.
        Sign string = partner_id + api_path + timestamp + access_token + shop_id
        """
        base_string = (
            f'{self.partner_id}{api_path}{timestamp}'
            f'{self.access_token}{self.shop_id}'
        )
        return hmac.new(
            self.partner_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

    def _common_params(self, api_path: str) -> dict[str, Any]:
        """Build the mandatory query parameters for every Shopee request."""
        ts = int(time.time())
        return {
            'partner_id': self.partner_id,
            'timestamp': ts,
            'access_token': self.access_token,
            'shop_id': self.shop_id,
            'sign': self._generate_sign(api_path, ts),
        }

    def _refresh_access_token(self) -> None:
        """
        Exchange refresh_token for a new access_token.
        Called automatically when the API returns HTTP 401 / error 'error_auth'.
        """
        api_path = '/api/v2/auth/access_token/get'
        ts = int(time.time())

        # Sign for token refresh uses partner_id + path + timestamp (no shop/token)
        sign_string = f'{self.partner_id}{api_path}{ts}'
        sign = hmac.new(
            self.partner_key.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        payload = {
            'refresh_token': self.refresh_token,
            'partner_id': self.partner_id,
            'shop_id': self.shop_id,
        }

        resp = self.session.post(
            f'{self.api_host}{api_path}',
            params={'partner_id': self.partner_id, 'timestamp': ts, 'sign': sign},
            json=payload,
            timeout=15,
        )
        data = resp.json()

        if data.get('error'):
            raise ShopeeAPIError(resp.status_code, data['error'], data.get('message', ''))

        # Persist new tokens back to database
        self.access_token = data['access_token']
        self.refresh_token = data['refresh_token']
        expire_in = data.get('expire_in', 14400)

        self.connection.access_token = self.access_token
        self.connection.refresh_token = self.refresh_token
        self.connection.token_expire_at = timezone.now() + timedelta(seconds=expire_in)
        self.connection.save(update_fields=['access_token', 'refresh_token', 'token_expire_at', 'updated_at'])

        logger.info('[ShopeeClient] Token refreshed for shop_id=%s', self.shop_id)

    # ──────────────────────────────────────────────────────────────
    # Core HTTP method with Retry + Backoff
    # ──────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        api_path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request against the Shopee API with:
          - HMAC-SHA256 request signing.
          - Automatic token refresh on 401 / error_auth.
          - Exponential Backoff Retry (max 3 attempts) for 429 and 5xx.
        """
        url = f'{self.api_host}{api_path}'
        backoff = INITIAL_BACKOFF_SECONDS
        token_refreshed = False

        for attempt in range(1, MAX_RETRIES + 1):
            query = self._common_params(api_path)
            if params:
                query.update(params)

            try:
                resp = self.session.request(
                    method,
                    url,
                    params=query,
                    json=json_body,
                    timeout=30,
                )
            except requests.RequestException as exc:
                logger.warning(
                    '[ShopeeClient] Network error (attempt %d/%d): %s',
                    attempt, MAX_RETRIES, exc,
                )
                if attempt == MAX_RETRIES:
                    raise ShopeeAPIError(0, 'NETWORK_ERROR', str(exc))
                time.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue

            # ── Token expired → refresh once then retry ──
            if resp.status_code == 401 or (
                resp.status_code == 200
                and resp.json().get('error') == 'error_auth'
            ):
                if not token_refreshed:
                    logger.info('[ShopeeClient] 401 received, refreshing token...')
                    self._refresh_access_token()
                    token_refreshed = True
                    continue
                raise ShopeeAPIError(401, 'AUTH_FAILED', 'Token refresh did not resolve 401.')

            # ── Rate limit (429) or server error (5xx) → backoff ──
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning(
                    '[ShopeeClient] HTTP %d (attempt %d/%d), retrying in %.1fs',
                    resp.status_code, attempt, MAX_RETRIES, backoff,
                )
                if attempt == MAX_RETRIES:
                    raise ShopeeAPIError(
                        resp.status_code,
                        'RETRY_EXHAUSTED',
                        f'Still failing after {MAX_RETRIES} retries.',
                    )
                time.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER
                continue

            # ── Success or client error ──
            data = resp.json()
            if data.get('error'):
                raise ShopeeAPIError(resp.status_code, data['error'], data.get('message', ''))
            return data

        # Should not reach here, but guard anyway
        raise ShopeeAPIError(0, 'UNKNOWN', 'Unexpected exit from retry loop.')

    # ──────────────────────────────────────────────────────────────
    # Public API methods
    # ──────────────────────────────────────────────────────────────

    def get_shop_info(self) -> dict[str, Any]:
        """GET /api/v2/shop/get_shop_info"""
        return self._request('GET', '/api/v2/shop/get_shop_info')

    def get_item_list(
        self,
        offset: int = 0,
        page_size: int = 100,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
    ) -> dict[str, Any]:
        """
        GET /api/v2/product/get_item_list
        Supports delta sync via update_time_from / update_time_to.
        """
        params: dict[str, Any] = {
            'offset': offset,
            'page_size': page_size,
            'item_status': 'NORMAL',
        }
        if update_time_from is not None:
            params['update_time_from'] = update_time_from
            params['update_time_to'] = update_time_to or int(time.time())

        return self._request('GET', '/api/v2/product/get_item_list', params=params)

    def get_item_detail(self, item_id_list: list[int]) -> dict[str, Any]:
        """
        GET /api/v2/product/get_item_base_info
        Shopee hard limit: max 50 item_ids per request.
        For lists > 50, use ``get_item_detail_chunked()`` instead.
        """
        if len(item_id_list) > ITEM_DETAIL_CHUNK_SIZE:
            raise ValueError(
                f'item_id_list exceeds Shopee limit of {ITEM_DETAIL_CHUNK_SIZE}. '
                f'Use get_item_detail_chunked() instead.'
            )
        params = {'item_id_list': ','.join(str(i) for i in item_id_list)}
        return self._request('GET', '/api/v2/product/get_item_base_info', params=params)

    def get_item_detail_chunked(self, item_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieve item details in chunks of 50 to respect Shopee API limits.
        """
        all_items: list[dict[str, Any]] = []

        for i in range(0, len(item_ids), ITEM_DETAIL_CHUNK_SIZE):
            chunk = item_ids[i : i + ITEM_DETAIL_CHUNK_SIZE]
            logger.debug(
                '[ShopeeClient] get_item_detail chunk %d–%d of %d',
                i, i + len(chunk), len(item_ids),
            )
            resp = self.get_item_detail(chunk)
            items = resp.get('response', {}).get('item_list', [])
            all_items.extend(items)

        return all_items

    def get_model_list(self, item_id: int) -> dict[str, Any]:
        """GET /api/v2/product/get_model_list — returns variations for one item."""
        return self._request(
            'GET',
            '/api/v2/product/get_model_list',
            params={'item_id': item_id},
        )

    def get_order_list(
        self,
        time_range_field: str = 'update_time',
        time_from: int = 0,
        time_to: int | None = None,
        page_size: int = 100,
        cursor: str = '',
    ) -> dict[str, Any]:
        """GET /api/v2/order/get_order_list — paginated delta sync."""
        params: dict[str, Any] = {
            'time_range_field': time_range_field,
            'time_from': time_from,
            'time_to': time_to or int(time.time()),
            'page_size': page_size,
            'order_status': 'ALL',
        }
        if cursor:
            params['cursor'] = cursor
        return self._request('GET', '/api/v2/order/get_order_list', params=params)

    def get_order_detail(self, order_sn_list: list[str]) -> dict[str, Any]:
        """GET /api/v2/order/get_order_detail — max 50 per request."""
        params = {'order_sn_list': ','.join(order_sn_list)}
        return self._request('GET', '/api/v2/order/get_order_detail', params=params)


# ──────────────────────────────────────────────────────────────────
# Static helpers for webhook signature verification
# ──────────────────────────────────────────────────────────────────

def verify_webhook_signature(url: str, body: bytes, received_signature: str) -> bool:
    """
    Verify that an incoming webhook request was genuinely sent by Shopee.

    Shopee signs webhooks as HMAC-SHA256( partner_key, url + "|" + body ).
    The signature is sent in the ``Authorization`` header.

    Returns True if the computed digest matches the received signature.
    """
    partner_key: str = settings.SUPPLYFORGE.get('shopee', {}).get('partner_key', '')
    if not partner_key:
        logger.error('[Webhook] partner_key not configured — cannot verify signature.')
        return False

    base_string = f'{url}|'.encode('utf-8') + body
    expected = hmac.new(
        partner_key.encode('utf-8'),
        base_string,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_signature)
