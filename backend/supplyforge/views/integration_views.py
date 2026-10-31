"""Workspace-scoped management and signed ingress APIs for ERP integrations."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.db.models import Count, FloatField, IntegerField, Max, Q, Sum
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models import (
    BackgroundJob, IntegrationConnection, IntegrationEvent,
    IntegrationSkuDailyMetric, IntegrationSkuMapping, IntegrationSkuMappingAudit,
    IntegrationSyncRun, IntegrationOperationalRiskSnapshot, CapitalExposureItemRecord,
    Product,
)
from supplyforge.permissions import PERM_MANAGE_INTEGRATIONS, has_permission
from supplyforge.services.integration_security import (
    decrypt_credentials, encrypt_credentials, entitlement_active,
    verify_webhook_signature, webhook_secret_hash,
)
from supplyforge.services.odoo_connector import OdooConnector, OdooConnectorError
from supplyforge.services.operational_analytics import OdooOperationalAnalyticsService


def _workspace(request):
    if not (getattr(request, 'tenant_context_validated', False) and getattr(request, 'workspace_id', None)):
        return None
    return int(request.workspace_id)


def _access_error(request, write=False):
    workspace_id = _workspace(request)
    if not workspace_id:
        return Response({'error': {'code': 'UNAUTHENTICATED', 'message': 'Yêu cầu cần workspace đã xác thực.'}}, status=status.HTTP_401_UNAUTHORIZED)
    if not entitlement_active(workspace_id):
        return Response({'error': {'code': 'FEATURE_NOT_ENTITLED', 'message': 'Odoo Integration là tính năng thuộc gói ERP Integrations.'}}, status=status.HTTP_403_FORBIDDEN)
    if write and not has_permission(getattr(request, 'user_role', None), PERM_MANAGE_INTEGRATIONS):
        return Response({'error': {'code': 'PERMISSION_DENIED', 'message': 'Chỉ OWNER hoặc ADMIN có thể quản lý kết nối ERP.'}}, status=status.HTTP_403_FORBIDDEN)
    return None


def _mapping_actor(request) -> str:
    return str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))[:128]


def _serialize_mapping(mapping: IntegrationSkuMapping) -> dict:
    product = mapping.canonical_product
    return {
        'id': mapping.id,
        'external_sku': mapping.external_sku,
        'external_name': mapping.external_name,
        'canonical_sku': mapping.canonical_sku,
        'canonical_product': ({
            'id': product.id,
            'item_sku': product.item_sku,
            'product_name': product.product_name,
        } if product else None),
        'status': mapping.status,
        'mapping_method': mapping.mapping_method,
        'mapped_by': mapping.mapped_by,
        'confirmed_at': mapping.confirmed_at.isoformat() if mapping.confirmed_at else None,
        'ignored_at': mapping.ignored_at.isoformat() if mapping.ignored_at else None,
        'resolution_note': mapping.resolution_note,
        # The client must return this value when writing. It prevents a stale
        # browser tab from silently overwriting another operator's decision.
        'updated_at': mapping.updated_at.isoformat(),
    }


def _mapping_summary(queryset) -> dict:
    summary = {
        IntegrationSkuMapping.STATUS_REVIEW: 0,
        IntegrationSkuMapping.STATUS_AUTO: 0,
        IntegrationSkuMapping.STATUS_CONFIRMED: 0,
        IntegrationSkuMapping.STATUS_IGNORED: 0,
    }
    for row in queryset.values('status').annotate(total=Count('id')):
        summary[row['status']] = row['total']
    summary['LINKED'] = summary[IntegrationSkuMapping.STATUS_AUTO] + summary[IntegrationSkuMapping.STATUS_CONFIRMED]
    return summary


def _record_mapping_audit(mapping, action: str, *, actor: str, previous_product_id: str = '', previous_sku: str = '', note: str = ''):
    IntegrationSkuMappingAudit.objects.create(
        mapping=mapping,
        action=action,
        previous_canonical_product_id=previous_product_id,
        previous_canonical_sku=previous_sku,
        canonical_product_id_snapshot=str(mapping.canonical_product_id or ''),
        canonical_sku=mapping.canonical_sku,
        actor=actor,
        note=note,
    )


def _serialize(connection: IntegrationConnection) -> dict:
    last_run = connection.sync_runs.order_by('-created_at').first()
    return {
        'id': str(connection.id), 'provider': connection.provider, 'display_name': connection.display_name,
        'status': connection.status, 'base_url': connection.base_url,
        'company': {'id': connection.external_company_id, 'name': connection.external_company_name},
        'warehouses': [{'id': item[0], 'name': item[1]} for item in zip(connection.warehouse_ids or [], connection.warehouse_names or [])],
        'discovery': (connection.cursor_json or {}).get('discovery') or None,
        'last_successful_sync_at': connection.last_successful_sync_at.isoformat() if connection.last_successful_sync_at else None,
        'last_error': {'code': connection.last_error_code, 'message': connection.last_error_message} if connection.last_error_code else None,
        'unmapped_sku_count': connection.sku_mappings.filter(status='NEEDS_REVIEW').count(),
        'latest_run': ({
            'id': str(last_run.id), 'type': last_run.run_type, 'status': last_run.status,
            'summary': last_run.summary, 'error_code': last_run.error_code,
            'error_message': last_run.error_message, 'started_at': last_run.started_at.isoformat() if last_run.started_at else None,
            'finished_at': last_run.finished_at.isoformat() if last_run.finished_at else None,
        } if last_run else None),
        'created_at': connection.created_at.isoformat(),
    }


def _validate_connection_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('URL Odoo không hợp lệ.')
    if parsed.scheme not in {'http', 'https'}:
        raise ValueError('URL Odoo phải dùng HTTP hoặc HTTPS.')
    # A deployed integration must use HTTPS and an operator allowlist. This
    # prevents a tenant configuration from becoming an arbitrary SSRF target.
    from django.conf import settings
    if settings.IS_DEPLOYED:
        allowed_hosts = {item.strip().lower() for item in __import__('os').environ.get('INTEGRATION_ALLOWED_HOSTS', '').split(',') if item.strip()}
        if parsed.scheme != 'https':
            raise ValueError('Kết nối ERP trên môi trường triển khai phải dùng HTTPS.')
        hostname = (parsed.hostname or '').lower()
        if not allowed_hosts or hostname not in allowed_hosts:
            raise ValueError('Máy chủ Odoo chưa nằm trong danh sách đích kết nối được phê duyệt.')
    return f'{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip("/")}'


def _safe_webhook_payload(value) -> dict:
    """Keep webhooks as a pull signal, never an ingress for customer PII."""
    if not isinstance(value, dict):
        return {}
    allowed = {'sku', 'default_code', 'name', 'product_id', 'warehouse_id', 'warehouse_name', 'event_version'}
    return {
        key: str(value[key])[:512]
        for key in allowed
        if value.get(key) not in (None, '')
    }


def _queue_run(connection: IntegrationConnection, run_type: str) -> IntegrationSyncRun:
    active = connection.sync_runs.filter(status__in={'PENDING', 'RUNNING'}).first()
    if active:
        raise ValueError('Kết nối đang có một lượt đồng bộ chạy hoặc chờ xử lý.')
    run = IntegrationSyncRun.objects.create(connection=connection, run_type=run_type, cursor_before=connection.cursor_json)
    job = BackgroundJob.objects.create(
        workspace=connection.workspace, job_type='INTEGRATION_SYNC', status='PENDING', current_stage='INTEGRATION_SYNC',
        stages_json={'INTEGRATION_SYNC': {'status': 'PENDING', 'progress': 0, 'provider': connection.provider, 'runType': run_type}},
        idempotency_key=f'integration:{connection.id}:{run_type}:{run.id}',
    )
    run.background_job = job
    run.save(update_fields=['background_job'])
    from supplyforge.tasks import run_integration_sync
    task = run_integration_sync.delay(str(run.id))
    job.celery_task_id = str(task.id)
    job.save(update_fields=['celery_task_id', 'updated_at'])
    return run


class IntegrationConnectionListCreateView(APIView):
    def get(self, request):
        error = _access_error(request)
        if error:
            return error
        connections = IntegrationConnection.objects.filter(workspace_id=_workspace(request)).prefetch_related('sync_runs', 'sku_mappings').order_by('-created_at')
        return Response({'entitled': True, 'connections': [_serialize(item) for item in connections]})

    def post(self, request):
        error = _access_error(request, write=True)
        if error:
            return error
        data = request.data or {}
        provider = str(data.get('provider') or 'ODOO').upper()
        if provider != 'ODOO':
            return Response({'error': {'code': 'UNSUPPORTED_PROVIDER', 'message': 'Provider này chưa được hỗ trợ.'}}, status=status.HTTP_400_BAD_REQUEST)
        required = ['display_name', 'base_url', 'database', 'username', 'api_key']
        missing = [name for name in required if not str(data.get(name) or '').strip()]
        if missing:
            return Response({'error': {'code': 'INVALID_CONNECTION', 'message': f"Thiếu trường: {', '.join(missing)}."}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            base_url = _validate_connection_url(str(data['base_url']))
        except ValueError as exc:
            return Response({'error': {'code': 'INVALID_CONNECTION_URL', 'message': str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
        webhook_secret = secrets.token_urlsafe(32)
        credentials = {'database': str(data['database']).strip(), 'username': str(data['username']).strip(), 'api_key': str(data['api_key']).strip(), 'webhook_secret': webhook_secret}
        connection = IntegrationConnection.objects.create(
            workspace_id=_workspace(request), provider=provider, display_name=str(data['display_name']).strip()[:128],
            base_url=base_url, external_database=credentials['database'],
            external_company_id=str(data.get('company_id') or ''), external_company_name=str(data.get('company_name') or ''),
            warehouse_ids=[str(item) for item in data.get('warehouse_ids', [])], warehouse_names=[str(item) for item in data.get('warehouse_names', [])],
            credential_encrypted=encrypt_credentials(credentials), webhook_secret_hash=webhook_secret_hash(webhook_secret),
            created_by=str(getattr(request, 'user_email', '') or getattr(request, 'user_id', ''))[:128],
        )
        payload = _serialize(connection)
        payload['webhook'] = {'url_path': f'/api/v1/integrations/webhooks/{connection.webhook_token}', 'secret': webhook_secret}
        return Response(payload, status=status.HTTP_201_CREATED)


class IntegrationConnectionDetailView(APIView):
    def get(self, request, connection_id):
        error = _access_error(request)
        if error:
            return error
        connection = IntegrationConnection.objects.filter(id=connection_id, workspace_id=_workspace(request)).first()
        if not connection:
            return Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(connection))

    def patch(self, request, connection_id):
        error = _access_error(request, write=True)
        if error:
            return error
        connection = IntegrationConnection.objects.filter(id=connection_id, workspace_id=_workspace(request)).first()
        if not connection:
            return Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        if 'status' in request.data and str(request.data['status']).upper() in {'PAUSED', 'ACTIVE'}:
            connection.status = str(request.data['status']).upper()
        if 'warehouse_ids' in request.data:
            connection.warehouse_ids = [str(item) for item in request.data['warehouse_ids']]
            connection.warehouse_names = [str(item) for item in request.data.get('warehouse_names', [])]
        if 'company_id' in request.data:
            connection.external_company_id = str(request.data.get('company_id') or '').strip()
            connection.external_company_name = str(request.data.get('company_name') or '').strip()[:255]
        connection.save()
        return Response(_serialize(connection))


class IntegrationRunView(APIView):
    def post(self, request, connection_id, run_type):
        error = _access_error(request, write=True)
        if error:
            return error
        connection = IntegrationConnection.objects.filter(id=connection_id, workspace_id=_workspace(request)).first()
        if not connection:
            return Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        mapped_type = {
            'validate': 'VALIDATE', 'initial-sync': 'INITIAL', 'sync': 'INCREMENTAL', 'reconcile': 'RECONCILIATION',
        }.get(run_type)
        if not mapped_type:
            return Response({'error': {'code': 'INVALID_RUN_TYPE'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            run = _queue_run(connection, mapped_type)
        except ValueError as exc:
            return Response({'error': {'code': 'SYNC_ALREADY_RUNNING', 'message': str(exc)}}, status=status.HTTP_409_CONFLICT)
        return Response({'run_id': str(run.id), 'job_id': str(run.background_job_id), 'status': run.status}, status=status.HTTP_202_ACCEPTED)


class IntegrationSkuMappingView(APIView):
    def get(self, request, connection_id):
        error = _access_error(request)
        if error:
            return error
        qs = IntegrationSkuMapping.objects.filter(
            connection_id=connection_id,
            connection__workspace_id=_workspace(request),
        )
        filter_name = str(request.query_params.get('status') or IntegrationSkuMapping.STATUS_REVIEW).upper()
        filters = {
            'ALL': Q(),
            'LINKED': Q(status__in=[IntegrationSkuMapping.STATUS_AUTO, IntegrationSkuMapping.STATUS_CONFIRMED]),
            IntegrationSkuMapping.STATUS_REVIEW: Q(status=IntegrationSkuMapping.STATUS_REVIEW),
            IntegrationSkuMapping.STATUS_IGNORED: Q(status=IntegrationSkuMapping.STATUS_IGNORED),
        }
        if filter_name not in filters:
            return Response({'error': {'code': 'INVALID_MAPPING_STATUS', 'message': 'Bộ lọc trạng thái mapping không hợp lệ.'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            page = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(10, int(request.query_params.get('pageSize', 25))))
        except (TypeError, ValueError):
            return Response({'error': {'code': 'INVALID_PAGINATION'}}, status=status.HTTP_400_BAD_REQUEST)
        total = qs.filter(filters[filter_name]).count()
        items = qs.filter(filters[filter_name]).select_related('canonical_product').order_by('external_sku')[(page - 1) * page_size:page * page_size]
        return Response({
            'items': [_serialize_mapping(item) for item in items],
            'pagination': {
                'page': page, 'pageSize': page_size, 'totalItems': total,
                'totalPages': max(1, (total + page_size - 1) // page_size),
            },
            'summary': _mapping_summary(qs),
            'filter': filter_name,
        })

    def patch(self, request, connection_id, mapping_id):
        error = _access_error(request, write=True)
        if error:
            return error
        payload = request.data or {}
        action = str(payload.get('action') or '').upper()
        if action not in {'CONFIRM', 'IGNORE', 'REOPEN', 'UNLINK'}:
            return Response({'error': {'code': 'INVALID_MAPPING_ACTION', 'message': 'Hành động mapping không hợp lệ.'}}, status=status.HTTP_400_BAD_REQUEST)

        expected_updated_at = str(payload.get('expected_updated_at') or '').strip()
        parsed_expected = parse_datetime(expected_updated_at) if expected_updated_at else None
        if expected_updated_at and not parsed_expected:
            return Response({'error': {'code': 'INVALID_MAPPING_VERSION', 'message': 'Phiên bản mapping không hợp lệ. Hãy tải lại danh sách.'}}, status=status.HTTP_400_BAD_REQUEST)
        if parsed_expected and timezone.is_naive(parsed_expected):
            parsed_expected = timezone.make_aware(parsed_expected)
        note = str(payload.get('note') or '').strip()
        if len(note) > 500:
            return Response({'error': {'code': 'MAPPING_NOTE_TOO_LONG', 'message': 'Ghi chú mapping không được vượt quá 500 ký tự.'}}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            mapping = IntegrationSkuMapping.objects.select_for_update().select_related(
                'connection__workspace', 'canonical_product',
            ).filter(
                id=mapping_id,
                connection_id=connection_id,
                connection__workspace_id=_workspace(request),
            ).first()
            if not mapping:
                return Response({'error': {'code': 'MAPPING_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
            if parsed_expected and mapping.updated_at != parsed_expected:
                return Response({
                    'error': {
                        'code': 'MAPPING_STALE',
                        'message': 'Mapping đã được một người dùng khác cập nhật. Hãy tải lại trước khi thao tác tiếp.',
                    },
                    'mapping': _serialize_mapping(mapping),
                }, status=status.HTTP_409_CONFLICT)

            actor = _mapping_actor(request)
            previous_product_id = str(mapping.canonical_product_id or '')
            previous_sku = mapping.canonical_sku

            if action == 'CONFIRM':
                canonical_product_id = str(payload.get('canonical_product_id') or '').strip()
                if not canonical_product_id:
                    return Response({'error': {'code': 'CANONICAL_PRODUCT_REQUIRED', 'message': 'Hãy chọn SKU chuẩn nội bộ trước khi xác nhận.'}}, status=status.HTTP_400_BAD_REQUEST)
                target = Product.objects.filter(
                    id=canonical_product_id,
                    user_id=str(mapping.connection.workspace.owner_id or ''),
                ).exclude(item_sku__isnull=True).exclude(item_sku='').first()
                if not target:
                    return Response({'error': {'code': 'CANONICAL_PRODUCT_NOT_FOUND', 'message': 'SKU chuẩn đã chọn không tồn tại trong workspace hiện tại.'}}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

                conflicting_mapping = IntegrationSkuMapping.objects.select_for_update().filter(
                    connection=mapping.connection,
                    status__in=[IntegrationSkuMapping.STATUS_AUTO, IntegrationSkuMapping.STATUS_CONFIRMED],
                ).exclude(id=mapping.id).filter(
                    Q(canonical_product_id=target.id) |
                    Q(canonical_product__isnull=True, canonical_sku=target.item_sku),
                ).first()
                if conflicting_mapping:
                    return Response({'error': {
                        'code': 'CANONICAL_PRODUCT_ALREADY_LINKED',
                        'message': f'SKU chuẩn {target.item_sku} đã liên kết với SKU Odoo {conflicting_mapping.external_sku}.',
                    }}, status=status.HTTP_409_CONFLICT)

                if mapping.status == IntegrationSkuMapping.STATUS_CONFIRMED and mapping.canonical_product_id == target.id:
                    return Response(_serialize_mapping(mapping))

                mapping.canonical_product = target
                mapping.canonical_sku = str(target.item_sku)
                mapping.status = IntegrationSkuMapping.STATUS_CONFIRMED
                mapping.mapping_method = IntegrationSkuMapping.METHOD_MANUAL
                mapping.mapped_by = actor
                mapping.confirmed_at = timezone.now()
                mapping.ignored_at = None
                mapping.resolution_note = note
                mapping.save()
                _record_mapping_audit(
                    mapping,
                    IntegrationSkuMappingAudit.ACTION_CORRECTED if previous_product_id else IntegrationSkuMappingAudit.ACTION_CONFIRMED,
                    actor=actor,
                    previous_product_id=previous_product_id,
                    previous_sku=previous_sku,
                    note=note,
                )
            elif action == 'IGNORE':
                mapping.canonical_product = None
                mapping.canonical_sku = ''
                mapping.status = IntegrationSkuMapping.STATUS_IGNORED
                mapping.mapping_method = ''
                mapping.mapped_by = actor
                mapping.confirmed_at = None
                mapping.ignored_at = timezone.now()
                mapping.resolution_note = note
                mapping.save()
                _record_mapping_audit(
                    mapping, IntegrationSkuMappingAudit.ACTION_IGNORED, actor=actor,
                    previous_product_id=previous_product_id, previous_sku=previous_sku, note=note,
                )
            else:
                mapping.canonical_product = None
                mapping.canonical_sku = ''
                mapping.status = IntegrationSkuMapping.STATUS_REVIEW
                mapping.mapping_method = ''
                mapping.mapped_by = actor
                mapping.confirmed_at = None
                mapping.ignored_at = None
                mapping.resolution_note = note
                mapping.save()
                _record_mapping_audit(
                    mapping,
                    IntegrationSkuMappingAudit.ACTION_REOPENED if action == 'REOPEN' else IntegrationSkuMappingAudit.ACTION_UNLINKED,
                    actor=actor,
                    previous_product_id=previous_product_id,
                    previous_sku=previous_sku,
                    note=note,
                )
        # Mapping changes alter what can enter the operational source. Queue
        # the bounded rebuild outside the request; CSV research results are
        # never touched by this workflow.
        from supplyforge.tasks import refresh_integration_operational_analytics
        connection_id = str(mapping.connection_id)
        transaction.on_commit(
            lambda: refresh_integration_operational_analytics.delay(connection_id),
            robust=True,
        )
        response = _serialize_mapping(mapping)
        response['operational_refresh'] = {'status': 'QUEUED'}
        return Response(response)


class IntegrationSkuCandidateView(APIView):
    """Bounded canonical product search for an ERP SKU mapping decision."""

    def get(self, request, connection_id):
        error = _access_error(request)
        if error:
            return error
        connection = IntegrationConnection.objects.select_related('workspace').filter(
            id=connection_id, workspace_id=_workspace(request),
        ).first()
        if not connection:
            return Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        search = str(request.query_params.get('q') or '').strip()
        if len(search) < 2:
            return Response({'items': []})
        try:
            limit = min(50, max(5, int(request.query_params.get('limit', 20))))
        except (TypeError, ValueError):
            return Response({'error': {'code': 'INVALID_LIMIT'}}, status=status.HTTP_400_BAD_REQUEST)
        products = Product.objects.filter(
            user_id=str(connection.workspace.owner_id or ''),
        ).exclude(item_sku__isnull=True).exclude(item_sku='').filter(
            Q(item_sku__icontains=search) | Q(product_name__icontains=search),
        ).order_by('item_sku')[:limit]
        return Response({'items': [{
            'id': product.id,
            'item_sku': product.item_sku,
            'product_name': product.product_name or '',
            'stock': product.stock,
            'price': float(product.price) if product.price is not None else None,
        } for product in products]})


class IntegrationOverviewView(APIView):
    """Operational ERP facts for the settings screen, without exposing source credentials."""

    def get(self, request, connection_id):
        error = _access_error(request)
        if error:
            return error
        connection = IntegrationConnection.objects.filter(id=connection_id, workspace_id=_workspace(request)).first()
        if not connection:
            return Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
        today = timezone.localdate()
        metrics = IntegrationSkuDailyMetric.objects.filter(connection=connection)
        latest_date = metrics.aggregate(value=Max('metric_date'))['value']
        recent = metrics.filter(metric_date__gte=today - timedelta(days=27))
        totals = recent.aggregate(sales=Sum('sales_quantity'), returns=Sum('returned_quantity'), revenue=Sum('revenue'))
        inventory = metrics.filter(metric_date=latest_date, on_hand_quantity__isnull=False) if latest_date else metrics.none()
        inventory_total = inventory.aggregate(value=Sum('on_hand_quantity'))['value'] or 0
        snapshot = IntegrationOperationalRiskSnapshot.objects.filter(connection=connection).first()
        warehouses = []
        for item in inventory.values('warehouse_id', 'warehouse_name').annotate(on_hand=Sum('on_hand_quantity')).order_by('warehouse_name'):
            warehouses.append({
                'warehouse_id': item['warehouse_id'], 'warehouse_name': item['warehouse_name'],
                'on_hand_quantity': float(item['on_hand'] or 0),
            })
        return Response({
            'connection_id': str(connection.id),
            'latest_metric_date': latest_date.isoformat() if latest_date else None,
            'freshness': connection.last_successful_sync_at.isoformat() if connection.last_successful_sync_at else None,
            'sales_28d': float(totals['sales'] or 0),
            'returns_28d': float(totals['returns'] or 0),
            'revenue_28d': float(totals['revenue'] or 0),
            'on_hand_quantity': float(inventory_total),
            'warehouse_inventory': warehouses,
            'unmapped_sku_count': connection.sku_mappings.filter(status='NEEDS_REVIEW').count(),
            'operational_source': {
                'status': snapshot.status if snapshot else 'PENDING',
                'data_as_of': snapshot.source_data_as_of.isoformat() if snapshot and snapshot.source_data_as_of else None,
                'calculated_at': snapshot.calculated_at.isoformat() if snapshot else None,
                'coverage': snapshot.coverage if snapshot else {},
            },
        })


def _operational_connection(request, connection_id):
    """Return a tenant-scoped connection after entitlement enforcement."""
    error = _access_error(request)
    if error:
        return None, error
    connection = IntegrationConnection.objects.filter(
        id=connection_id,
        workspace_id=_workspace(request),
    ).first()
    if not connection:
        return None, Response({'error': {'code': 'CONNECTION_NOT_FOUND'}}, status=status.HTTP_404_NOT_FOUND)
    return connection, None


def _operational_source_payload(connection, snapshot):
    freshness_age_minutes = None
    if connection.last_successful_sync_at:
        freshness_age_minutes = max(0, int((timezone.now() - connection.last_successful_sync_at).total_seconds() // 60))
    return {
        'type': 'ODOO_OPERATIONS',
        'connection_id': str(connection.id),
        'connection_name': connection.display_name,
        'provider': connection.provider,
        'company': connection.external_company_name,
        'warehouses': connection.warehouse_names or [],
        'last_successful_sync_at': connection.last_successful_sync_at.isoformat() if connection.last_successful_sync_at else None,
        'freshness_age_minutes': freshness_age_minutes,
        'is_stale': freshness_age_minutes is None or freshness_age_minutes > 30,
        'data_as_of': snapshot.source_data_as_of.isoformat() if snapshot and snapshot.source_data_as_of else None,
        'calculated_at': snapshot.calculated_at.isoformat() if snapshot else None,
        'status': snapshot.status if snapshot else 'PENDING',
        'risk_engine': snapshot.risk_engine_version if snapshot else 'odoo_operational_rules_v1',
        'coverage': snapshot.coverage if snapshot else {},
    }


class IntegrationOperationalRiskView(APIView):
    """Read the materialised Odoo risk source; no calculation in HTTP."""

    def get(self, request, connection_id):
        connection, error = _operational_connection(request, connection_id)
        if error:
            return error
        snapshot = IntegrationOperationalRiskSnapshot.objects.filter(connection=connection).first()
        source = _operational_source_payload(connection, snapshot)
        if not snapshot or snapshot.status != 'READY':
            return Response({'total_count': 0, 'limit': 50, 'offset': 0, 'assessments': [], 'source': source})

        query = snapshot.assessments.all()
        risk_class = str(request.query_params.get('risk_class') or '').upper()
        search = str(request.query_params.get('sku') or '').strip()
        category = str(request.query_params.get('category') or '').strip()
        if risk_class:
            query = query.filter(risk_class=risk_class)
        if search:
            query = query.filter(Q(external_sku__icontains=search) | Q(canonical_sku__icontains=search) | Q(product_name__icontains=search))
        if category:
            query = query.filter(category__icontains=category)

        capital_band = str(request.query_params.get('capital_band') or '').upper()
        aging_band = str(request.query_params.get('aging_band') or '').upper()
        sort_by = str(request.query_params.get('sort_by') or '-risk_score')
        needs_metrics = capital_band or aging_band or sort_by.lstrip('-') in {'capital_exposure', 'dsls'}
        if needs_metrics:
            query = query.annotate(
                list_capital_exposure=Cast('evidence__capital_exposure_vnd', FloatField()),
                list_dsls=Cast('evidence__dsls', IntegerField()),
            )
        if capital_band == 'LOW':
            query = query.filter(list_capital_exposure__lt=10_000_000)
        elif capital_band == 'MID':
            query = query.filter(list_capital_exposure__gte=10_000_000, list_capital_exposure__lte=50_000_000)
        elif capital_band == 'HIGH':
            query = query.filter(list_capital_exposure__gt=50_000_000)
        if aging_band == 'FRESH':
            query = query.filter(list_dsls__lte=30)
        elif aging_band == 'AGING':
            query = query.filter(list_dsls__gt=30, list_dsls__lte=60)
        elif aging_band == 'AT_RISK':
            query = query.filter(list_dsls__gt=60, list_dsls__lte=90)
        elif aging_band == 'CRITICAL':
            query = query.filter(list_dsls__gt=90)

        sort_map = {
            'risk_score': 'risk_score', '-risk_score': '-risk_score',
            'risk_probability': 'risk_probability', '-risk_probability': '-risk_probability',
            'capital_exposure': 'list_capital_exposure', '-capital_exposure': '-list_capital_exposure',
            'dsls': 'list_dsls', '-dsls': '-list_dsls',
        }
        query = query.order_by(sort_map.get(sort_by, '-risk_score'), 'external_sku')
        try:
            limit = min(100, max(1, int(request.query_params.get('limit', 50))))
            offset = max(0, int(request.query_params.get('offset', 0)))
        except (TypeError, ValueError):
            return Response({'error': {'code': 'INVALID_PAGINATION', 'message': 'limit và offset phải là số nguyên hợp lệ.'}}, status=status.HTTP_400_BAD_REQUEST)

        total_count = query.count()
        rows = query[offset:offset + limit]
        assessments = []
        for record in rows:
            evidence = record.evidence if isinstance(record.evidence, dict) else {}
            assessments.append({
                'assessment_id': str(record.id),
                'sku': record.canonical_sku,
                'external_sku': record.external_sku,
                'canonical_sku_id': record.canonical_sku,
                'product_name': record.product_name,
                'category': record.category,
                'risk': {'class': record.risk_class, 'score': record.risk_score, 'probability': record.risk_probability},
                'primary_signals': record.primary_signals,
                'supporting_signals': record.supporting_signals,
                'evidence': evidence,
                'capital_exposure_vnd': evidence.get('capital_exposure_vnd', 0),
                'stock_quantity': evidence.get('stock_quantity', 0),
                'unit_cost': evidence.get('unit_cost', 0),
                'model': {'name': 'Odoo operational rules', 'version': snapshot.risk_engine_version},
                'assessment_timestamp': snapshot.calculated_at.isoformat(),
            })
        return Response({'total_count': total_count, 'limit': limit, 'offset': offset, 'assessments': assessments, 'source': source})


class IntegrationOperationalRiskSummaryView(APIView):
    """Small source and class aggregate for the Odoo risk dashboard header."""

    def get(self, request, connection_id):
        connection, error = _operational_connection(request, connection_id)
        if error:
            return error
        snapshot = IntegrationOperationalRiskSnapshot.objects.filter(connection=connection).first()
        source = _operational_source_payload(connection, snapshot)
        counts = {'CRITICAL': 0, 'HIGH_RISK': 0, 'MEDIUM_RISK': 0, 'LOW_RISK': 0}
        if snapshot and snapshot.status == 'READY':
            for row in snapshot.assessments.values('risk_class').annotate(total=Count('id')):
                counts[row['risk_class']] = row['total']
        return Response({
            'total_skus': sum(counts.values()),
            'critical': counts['CRITICAL'],
            'high_risk': counts['HIGH_RISK'],
            'medium_risk': counts['MEDIUM_RISK'],
            'low_risk': counts['LOW_RISK'],
            'source': source,
        })


class IntegrationOperationalCapitalView(APIView):
    """Return the latest Odoo capital analysis built with the operational risk view."""

    def get(self, request, connection_id):
        connection, error = _operational_connection(request, connection_id)
        if error:
            return error
        snapshot = IntegrationOperationalRiskSnapshot.objects.filter(connection=connection).first()
        analysis = OdooOperationalAnalyticsService.get_capital_analysis(connection.id, connection.workspace_id)
        source = _operational_source_payload(connection, snapshot)
        if not analysis:
            return Response({
                'code': 'ODOO_OPERATIONAL_ANALYSIS_PENDING',
                'detail': 'Bản phân tích vận hành sẽ sẵn sàng sau khi đồng bộ Odoo và hoàn tất liên kết SKU.',
                'source': source,
            }, status=status.HTTP_409_CONFLICT)
        from supplyforge.serializers.capital_exposure_serializer import CapitalExposureAnalysisSerializer
        payload = CapitalExposureAnalysisSerializer(analysis).data
        payload['source'] = source
        return Response(payload)


class IntegrationOperationalExecutiveSummaryView(APIView):
    """Operational-only counterpart to the CSV executive dashboard summary."""

    def get(self, request, connection_id):
        connection, error = _operational_connection(request, connection_id)
        if error:
            return error
        snapshot = IntegrationOperationalRiskSnapshot.objects.filter(connection=connection).first()
        source = _operational_source_payload(connection, snapshot)
        if not snapshot or snapshot.status != 'READY':
            return Response({'hasData': False, 'source': source})

        counts = {'CRITICAL': 0, 'HIGH_RISK': 0, 'MEDIUM_RISK': 0, 'LOW_RISK': 0}
        for row in snapshot.assessments.values('risk_class').annotate(total=Count('id')):
            counts[row['risk_class']] = row['total']
        analysis = OdooOperationalAnalyticsService.get_capital_analysis(connection.id, connection.workspace_id)
        distributions = {
            row.get('group'): row
            for row in (analysis.risk_distribution if analysis else [])
            if isinstance(row, dict)
        }
        aging = {
            row.get('group'): row
            for row in (analysis.aging_distribution if analysis else [])
            if isinstance(row, dict)
        }
        top_items = []
        if analysis:
            items = CapitalExposureItemRecord.objects.filter(
                analysis=analysis,
                slow_moving_risk_class__in=['CRITICAL', 'HIGH_RISK'],
            ).order_by('-risk_weighted_exposure', 'sku')[:5]
            top_items = [{
                'sku': item.sku,
                'name': item.product_name or item.sku,
                'capitalExposureVnd': item.capital_exposure,
                'daysInInventory': item.aging_days or 0,
                'riskClass': item.slow_moving_risk_class,
            } for item in items]
        # Keep the Odoo dashboard contract identical to the CSV dashboard.
        # The capital analysis persists a list for reporting, but consumers of
        # this summary address values by risk class.
        risk_capital = {
            risk_class: float(distributions.get(risk_class, {}).get('inventory_value') or 0)
            for risk_class in ['CRITICAL', 'HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK']
        }
        at_risk_capital = risk_capital['CRITICAL'] + risk_capital['HIGH_RISK']
        return Response({
            'hasData': bool(sum(counts.values())),
            'source': source,
            'capitalStatus': 'READY' if analysis else 'RISK_READ_MODEL_ONLY',
            'totalSkus': sum(counts.values()),
            'criticalCount': counts['CRITICAL'],
            'highRiskCount': counts['HIGH_RISK'],
            'mediumRiskCount': counts['MEDIUM_RISK'],
            'lowRiskCount': counts['LOW_RISK'],
            'totalCapitalExposureVnd': float(analysis.total_inventory_value) if analysis else 0,
            'atRiskCapitalVnd': at_risk_capital,
            'agedCapitalVnd': float(aging.get('CRITICAL_AGING', {}).get('inventory_value') or 0),
            'agedSkuCount': int(aging.get('CRITICAL_AGING', {}).get('sku_count') or 0),
            'topRiskSkus': top_items,
            'riskCapitalByClassVnd': risk_capital,
        })


@csrf_exempt
@require_http_methods(['POST'])
def integration_webhook(request, webhook_token):
    connection = IntegrationConnection.objects.filter(webhook_token=webhook_token, status='ACTIVE').first()
    if not connection or not entitlement_active(connection.workspace_id):
        from supplyforge.metrics import record_erp_webhook
        record_erp_webhook('unavailable')
        return JsonResponse({'error': 'Connection unavailable.'}, status=404)
    timestamp = request.headers.get('X-SupplyForge-Timestamp', '')
    signature = request.headers.get('X-SupplyForge-Signature', '')
    try:
        secret = decrypt_credentials(connection.credential_encrypted).get('webhook_secret', '')
        body = request.body
        if not verify_webhook_signature(secret, timestamp, body, signature):
            from supplyforge.metrics import record_erp_webhook
            record_erp_webhook('invalid_signature')
            return JsonResponse({'error': 'Invalid webhook signature.'}, status=403)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError('Event payload must be an object.')
    except (ValueError, json.JSONDecodeError):
        from supplyforge.metrics import record_erp_webhook
        record_erp_webhook('invalid_payload')
        return JsonResponse({'error': 'Invalid event payload.'}, status=400)
    external_event_id = str(payload.get('event_id') or '').strip()
    event_type = str(payload.get('event_type') or '').strip()
    if not external_event_id or not event_type:
        from supplyforge.metrics import record_erp_webhook
        record_erp_webhook('invalid_payload')
        return JsonResponse({'error': 'event_id and event_type are required.'}, status=400)
    checksum = hashlib.sha256(body).hexdigest()
    occurred_at = parse_datetime(str(payload.get('occurred_at') or ''))
    if occurred_at and timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at)
    try:
        event, created = IntegrationEvent.objects.get_or_create(
            connection=connection, external_event_id=external_event_id,
            defaults={
                'event_type': event_type[:64],
                'payload': _safe_webhook_payload(payload.get('payload')),
                'payload_checksum': checksum,
                'occurred_at': occurred_at or timezone.now(),
            },
        )
    except IntegrityError:
        event, created = IntegrationEvent.objects.get(connection=connection, external_event_id=external_event_id), False
    if created:
        from supplyforge.tasks import process_integration_event
        process_integration_event.delay(str(event.id))
    from supplyforge.metrics import record_erp_webhook
    record_erp_webhook('accepted' if created else 'duplicate')
    return JsonResponse({'accepted': True, 'duplicate': not created, 'event_id': str(event.id)}, status=202)
