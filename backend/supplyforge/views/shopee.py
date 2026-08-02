from __future__ import annotations

import functools
import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.models import (
    ShopeeConnection,
    SyncLog,
    User,
)
from supplyforge.services.shopee_sync import ShopeeSyncService
from supplyforge.services.shopee_client import verify_webhook_signature
from supplyforge.tasks import (
    sync_shopee_orders_task,
    sync_shopee_products_task,
)

logger = logging.getLogger(__name__)


def shopee_webhook_signature_required(view_func: Callable) -> Callable:
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        received_sig = request.headers.get('Authorization', '')

        if not received_sig:
            logger.warning('[Webhook] Missing Authorization header — rejecting request.')
            return JsonResponse(
                {'error': 'Missing webhook signature.'},
                status=403,
            )

        full_url = request.build_absolute_uri()
        raw_body = request.body  # bytes

        if not verify_webhook_signature(full_url, raw_body, received_sig):
            logger.warning(
                '[Webhook] Signature mismatch — possible forged request. URL=%s',
                full_url,
            )
            return JsonResponse(
                {'error': 'Invalid webhook signature.'},
                status=403,
            )

        return view_func(request, *args, **kwargs)

    return wrapper


@csrf_exempt
@api_view(['GET'])
def shopee_oauth_authorize_url(request):
    cfg = settings.SUPPLYFORGE.get('shopee', {})
    try:
        partner_id = int(cfg.get('partner_id') or 0)
    except (ValueError, TypeError):
        partner_id = 0
    partner_key = cfg.get('partner_key', '')
    api_host = cfg.get('api_host', 'https://partner.shopeemobile.com')
    redirect_url = cfg.get('redirect_url', 'http://localhost:8080/api/v1/shopee/oauth/callback')

    if not partner_id or not partner_key:
        return JsonResponse(
            {'error': 'Shopee Integration is not configured in backend settings.py (missing partner_id or partner_key)'},
            status=400,
        )

    api_path = '/api/v2/shop/auth_partner'
    ts = int(time.time())

    sign_string = f'{partner_id}{api_path}{ts}'
    sign = hmac.new(
        partner_key.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    auth_url = (
        f'{api_host}{api_path}'
        f'?partner_id={partner_id}'
        f'&redirect={redirect_url}'
        f'&timestamp={ts}'
        f'&sign={sign}'
    )

    return JsonResponse({'url': auth_url})


@csrf_exempt
@require_http_methods(['GET'])
def shopee_oauth_callback(request):
    code = request.GET.get('code', '')
    shop_id = request.GET.get('shop_id', '')

    if not code or not shop_id:
        return JsonResponse(
            {'error': 'Missing code or shop_id parameter.'},
            status=400,
        )

    cfg = settings.SUPPLYFORGE.get('shopee', {})
    partner_id = int(cfg.get('partner_id', 0))
    partner_key = cfg.get('partner_key', '')
    api_host = cfg.get('api_host', 'https://partner.shopeemobile.com')

    import requests as http_lib

    api_path = '/api/v2/auth/token/get'
    ts = int(time.time())

    sign_string = f'{partner_id}{api_path}{ts}'
    sign = hmac.new(
        partner_key.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    try:
        resp = http_lib.post(
            f'{api_host}{api_path}',
            params={
                'partner_id': partner_id,
                'timestamp': ts,
                'sign': sign,
            },
            json={
                'code': code,
                'shop_id': int(shop_id),
                'partner_id': partner_id,
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        logger.exception('[OAuth] Token exchange failed.')
        return JsonResponse({'error': f'Token exchange failed: {exc}'}, status=502)

    if data.get('error'):
        return JsonResponse(
            {'error': f"Shopee error: {data['error']} — {data.get('message', '')}"},
            status=400,
        )

    access_token = data.get('access_token', '')
    refresh_token = data.get('refresh_token', '')
    expire_in = data.get('expire_in', 14400)

    user = User.objects.first()

    connection, created = ShopeeConnection.objects.update_or_create(
        shop_id=int(shop_id),
        defaults={
            'user': user,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_expire_at': timezone.now() + timedelta(seconds=expire_in),
            'is_active': True,
        },
    )

    action = 'created' if created else 'updated'
    logger.info('[OAuth] ShopeeConnection %s for shop_id=%s', action, shop_id)

    sync_shopee_products_task.delay(connection.id)
    sync_shopee_orders_task.delay(connection.id)

    return JsonResponse({
        'message': f'Shop {shop_id} connected successfully. Initial sync dispatched.',
        'connection_id': connection.id,
    })


@csrf_exempt
@require_http_methods(['POST'])
@shopee_webhook_signature_required
def shopee_webhook(request):
    import json

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    event_code = payload.get('code', '')
    shop_id = payload.get('shop_id', 0)
    data = payload.get('data', {})

    logger.info('[Webhook] Received event=%s shop_id=%s', event_code, shop_id)

    if event_code == 'shopee.item_stock_changed':
        item_id = data.get('item_id', 0)
        for model_change in data.get('model_list', []):
            model_id = model_change.get('model_id', 0)
            new_stock = model_change.get('current_stock', 0)
            ShopeeSyncService.update_stock_from_webhook(
                shop_id=shop_id,
                item_id=item_id,
                model_id=model_id,
                new_stock=new_stock,
            )

    elif event_code == 'shopee.order_status_update':
        order_sn = data.get('order_sn', '')
        new_status = data.get('status', '')
        if order_sn and new_status:
            ShopeeSyncService.update_order_status_from_webhook(
                shop_id=shop_id,
                order_sn=order_sn,
                new_status=new_status,
            )

    else:
        logger.info('[Webhook] Unhandled event code: %s', event_code)

    return JsonResponse({'message': 'Webhook received.'})


@csrf_exempt
@api_view(['POST'])
def trigger_sync(request):
    connection_id = request.data.get('connection_id')
    sync_type = request.data.get('sync_type', 'ALL').upper()

    if not connection_id:
        return Response(
            {'error': 'connection_id is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        ShopeeConnection.objects.get(id=connection_id, is_active=True)
    except ShopeeConnection.DoesNotExist:
        return Response(
            {'error': 'Active ShopeeConnection not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    dispatched: list[str] = []

    if sync_type in ('PRODUCT', 'ALL'):
        sync_shopee_products_task.delay(connection_id)
        dispatched.append('PRODUCT')

    if sync_type in ('ORDER', 'ALL'):
        sync_shopee_orders_task.delay(connection_id)
        dispatched.append('ORDER')

    return Response({
        'message': f'Sync tasks dispatched: {", ".join(dispatched)}.',
        'connection_id': connection_id,
    })


@api_view(['GET'])
def get_sync_status(request):
    connection_id = request.GET.get('connection_id')
    if not connection_id:
        return Response(
            {'error': 'connection_id query parameter is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    logs = (
        SyncLog.objects
        .filter(connection_id=connection_id)
        .order_by('-created_at')[:10]
        .values(
            'id', 'sync_type', 'log_level', 'event_type',
            'message', 'records_processed', 'records_created',
            'records_updated', 'started_at', 'finished_at', 'created_at',
        )
    )

    return Response(list(logs))
