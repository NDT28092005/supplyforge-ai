"""
SupplyForge AI — Notification & Alert Views (NOTI-001 & NOTI-002)
===============================================================
REST API Endpoints for In-App Notifications:
- GET /api/v1/notifications/ : List notifications (auto-seed sample NOTI-001 alerts if empty)
- POST /api/v1/notifications/mark-read/ : Mark notification(s) as read
- POST /api/v1/notifications/create/ : Create new notification alert trigger
"""

import json
from django.http import JsonResponse
from rest_framework.decorators import api_view
from supplyforge.models import NotificationRecord


def _trusted_workspace_id(request):
    if not (
        getattr(request, 'tenant_context_validated', False)
        and getattr(request, 'workspace_id', None)
    ):
        return None, JsonResponse(
            {
                'error': 'Yêu cầu cần Authorization Bearer token.',
                'code': 'UNAUTHENTICATED',
            },
            status=401,
        )
    return int(request.workspace_id), None


def _validate_requested_workspace(request, workspace_id):
    if workspace_id in (None, ''):
        return None
    try:
        requested_id = int(workspace_id)
    except (TypeError, ValueError):
        return JsonResponse(
            {'error': 'workspace_id không hợp lệ.', 'code': 'INVALID_WORKSPACE'},
            status=400,
        )
    if requested_id != request.workspace_id:
        return JsonResponse(
            {
                'error': 'Workspace trong request không khớp tenant của phiên đăng nhập.',
                'code': 'WORKSPACE_MISMATCH',
            },
            status=403,
        )
    return None


def _seed_default_notifications(workspace_id):
    """Seed default realistic notifications covering all 6 NOTI-001 triggers."""
    default_items = [
        {
            'notification_type': NotificationRecord.TRIGGER_NEW_CRITICAL_SKU,
            'title': 'Phát hiện sản phẩm rủi ro cao mới',
            'message': 'Mặt hàng CRIT-024 đã chuyển sang nhóm rủi ro cao do 90 ngày chưa phát sinh đơn hàng mới.',
            'severity': NotificationRecord.SEVERITY_CRITICAL,
            'related_sku': 'CRIT-024',
            'action_url': '/app/risk?sku=CRIT-024'
        },
        {
            'notification_type': NotificationRecord.TRIGGER_CAPITAL_EXPOSURE_INCREASE,
            'title': 'Tổng vốn đọng tăng đột biến',
            'message': 'Tổng vốn bị chôn kẹt trong kho tăng thêm +45.000.000 VNĐ so với kỳ phân tích 30 ngày trước.',
            'severity': NotificationRecord.SEVERITY_HIGH,
            'action_url': '/app/capital'
        },
        {
            'notification_type': NotificationRecord.TRIGGER_DATASET_STALE,
            'title': 'Dữ liệu kho quá 30 ngày chưa cập nhật',
            'message': 'Lần nạp tệp CSV đơn hàng gần nhất là 32 ngày trước. Vui lòng nạp tệp mới để đảm bảo độ chính xác.',
            'severity': NotificationRecord.SEVERITY_WARNING,
            'action_url': '/app/import'
        },
        {
            'notification_type': NotificationRecord.TRIGGER_ACTION_DEADLINE_APPROACHING,
            'title': 'Sắp hết hạn kế hoạch xả kho',
            'message': 'Chiến dịch xả hàng CRIT-024 (Giảm giá 15% trong 14 ngày) chỉ còn 2 ngày trước khi kết thúc.',
            'severity': NotificationRecord.SEVERITY_WARNING,
            'related_sku': 'CRIT-024',
            'action_url': '/app/decisions'
        },
        {
            'notification_type': NotificationRecord.TRIGGER_IMPORT_FAILED,
            'title': 'Cảnh báo nạp dữ liệu',
            'message': 'Tệp CSV nạp trước đó có 2 dòng thiếu mã sản phẩm. Hệ thống đã tự động bỏ qua các dòng lỗi.',
            'severity': NotificationRecord.SEVERITY_INFO,
            'action_url': '/app/import'
        },
        {
            'notification_type': NotificationRecord.TRIGGER_PREDICTION_FAILED,
            'title': 'Cảnh báo mô hình dự báo',
            'message': 'Sản phẩm mới nhập chưa có đủ 14 ngày lịch sử đơn hàng để chạy mô phỏng chính xác.',
            'severity': NotificationRecord.SEVERITY_INFO,
            'action_url': '/app/risk'
        },
    ]

    for item in default_items:
        NotificationRecord.objects.create(
            workspace_id=workspace_id,
            notification_type=item['notification_type'],
            title=item['title'],
            message=item['message'],
            severity=item['severity'],
            related_sku=item.get('related_sku'),
            action_url=item.get('action_url'),
            is_read=False
        )


@api_view(['GET'])
def list_notifications(request):
    """GET /api/v1/notifications/"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    workspace_id, context_error = _trusted_workspace_id(request)
    if context_error:
        return context_error
    workspace_error = _validate_requested_workspace(
        request,
        request.GET.get('workspace_id'),
    )
    if workspace_error:
        return workspace_error

    unread_only = request.GET.get('unread_only', 'false').lower() == 'true'

    qs = NotificationRecord.objects.filter(workspace_id=workspace_id)
    if not qs.exists():
        _seed_default_notifications(workspace_id=workspace_id)
        qs = NotificationRecord.objects.filter(workspace_id=workspace_id)

    total_unread = qs.filter(is_read=False).count()

    if unread_only:
        qs = qs.filter(is_read=False)

    notifications = []
    for item in qs[:50]:
        notifications.append({
            'id': item.id,
            'workspace_id': item.workspace_id,
            'notification_type': item.notification_type,
            'notification_type_display': item.get_notification_type_display(),
            'title': item.title,
            'message': item.message,
            'severity': item.severity,
            'severity_display': item.get_severity_display(),
            'is_read': item.is_read,
            'related_sku': item.related_sku,
            'action_url': item.action_url,
            'created_at': item.created_at.strftime('%H:%M %d/%m/%Y'),
        })

    return JsonResponse({
        'success': True,
        'count': len(notifications),
        'unread_count': total_unread,
        'notifications': notifications
    })


@api_view(['POST'])
def mark_notifications_read(request):
    """POST /api/v1/notifications/mark-read/"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        body = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        body = {}

    workspace_id, context_error = _trusted_workspace_id(request)
    if context_error:
        return context_error
    workspace_error = _validate_requested_workspace(
        request,
        body.get('workspace_id'),
    )
    if workspace_error:
        return workspace_error
    notification_id = body.get('id')
    mark_all = body.get('mark_all', False)

    qs = NotificationRecord.objects.filter(workspace_id=workspace_id)

    if mark_all:
        updated_count = qs.filter(is_read=False).update(is_read=True)
    elif notification_id:
        updated_count = qs.filter(id=notification_id).update(is_read=True)
    else:
        updated_count = 0

    unread_count = qs.filter(is_read=False).count()

    return JsonResponse({
        'success': True,
        'updated_count': updated_count,
        'unread_count': unread_count,
        'message': 'Đã cập nhật trạng thái thông báo'
    })


@api_view(['POST'])
def create_notification(request):
    """POST /api/v1/notifications/create/"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    workspace_id, context_error = _trusted_workspace_id(request)
    if context_error:
        return context_error
    workspace_error = _validate_requested_workspace(
        request,
        body.get('workspace_id'),
    )
    if workspace_error:
        return workspace_error
    notification_type = body.get('notification_type', NotificationRecord.TRIGGER_NEW_CRITICAL_SKU)
    title = body.get('title', 'Cảnh báo hệ thống mới')
    message = body.get('message', 'Đã ghi nhận sự kiện rủi ro mới.')
    severity = body.get('severity', NotificationRecord.SEVERITY_WARNING)
    related_sku = body.get('related_sku')
    action_url = body.get('action_url')

    record = NotificationRecord.objects.create(
        workspace_id=workspace_id,
        notification_type=notification_type,
        title=title,
        message=message,
        severity=severity,
        related_sku=related_sku,
        action_url=action_url,
        is_read=False
    )

    return JsonResponse({
        'success': True,
        'notification': {
            'id': record.id,
            'title': record.title,
            'message': record.message,
            'notification_type': record.notification_type,
            'severity': record.severity,
            'is_read': record.is_read,
            'created_at': record.created_at.strftime('%H:%M %d/%m/%Y'),
        }
    }, status=201)
