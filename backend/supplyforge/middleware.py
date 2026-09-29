import jwt
import logging
import threading
from django.conf import settings
from django.db import models
from supplyforge.permissions import get_user_permissions, ROLE_OWNER

logger = logging.getLogger(__name__)
_thread_locals = threading.local()


def get_current_tenant_id():
    return getattr(_thread_locals, 'tenant_id', None)


def set_current_tenant_id(tenant_id):
    _thread_locals.tenant_id = tenant_id


class TenantIsolationMiddleware:
    """
    TEN-003 & TEN-002: Application-level Security & Tenant Context Middleware.
    Extracts user, tenant_id, role, and permissions for EVERY incoming HTTP request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auth_header = request.headers.get('Authorization', '')
        user_id = None
        email = None
        tenant_id = None
        workspace_id = None
        role = ROLE_OWNER

        if auth_header.startswith('Bearer '):
            token_str = auth_header[7:].strip()
            try:
                payload = jwt.decode(token_str, settings.SECRET_KEY, algorithms=['HS256'])
                user_id = payload.get('user_id')
                email = payload.get('email')
                workspace_id = payload.get('workspace_id')
                tenant_id = payload.get('tenant_id') or (f"T{workspace_id:03d}" if workspace_id else None)
                role = payload.get('role')
                if not role and user_id:
                    from supplyforge.models import User
                    user_obj = User.objects.filter(id=user_id).first()
                    if user_obj:
                        role = user_obj.role
                role = role or ROLE_OWNER
                request.jwt_payload = payload
            except Exception as e:
                pass

        if not workspace_id:
            raw_ws = request.headers.get('X-Workspace-ID') or request.headers.get('X-Tenant-ID') or request.GET.get('workspaceId')
            if raw_ws and str(raw_ws).replace('T', '').replace('W', '').isdigit():
                workspace_id = int(str(raw_ws).replace('T', '').replace('W', ''))
            else:
                workspace_id = 1

        if not tenant_id:
            tenant_id = f"T{workspace_id:03d}"

        permissions = get_user_permissions(role)

        # TEN-003: Attach Tenant Context to request object
        request.user_id = user_id
        request.user_email = email
        request.workspace_id = workspace_id
        request.tenant_id = tenant_id
        request.authenticated_tenant_id = tenant_id
        request.user_role = role
        request.user_permissions = permissions
        request.tenant_context = {
            "user_id": user_id,
            "email": email,
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "role": role,
            "permissions": permissions
        }

        # SEC-AUTH-002: Email Verification Enforcement Gate
        path = request.path_info
        exempt_paths = [
            '/api/auth/register', '/api/v1/auth/register',
            '/api/auth/verify-email', '/api/v1/auth/verify-email',
            '/api/auth/resend-verification', '/api/v1/auth/resend-verification',
            '/api/auth/login', '/api/v1/auth/login',
            '/api/auth/forgot-password', '/api/v1/auth/forgot-password',
            '/api/auth/reset-password', '/api/v1/auth/reset-password',
            '/api/v1/ping', '/api/v1/data/check'
        ]

        if user_id and not any(path.startswith(p) for p in exempt_paths):
            from supplyforge.models import User
            user_obj = User.objects.filter(id=user_id).first()
            if user_obj and (user_obj.status in [User.STATUS_PENDING, 'PENDING_VERIFICATION'] or not user_obj.is_email_verified):
                from django.http import JsonResponse
                return JsonResponse({
                    "error": "Tài khoản chưa hoàn tất xác thực email (status = PENDING_VERIFICATION). Hệ thống không cấp quyền sử dụng các chức năng khi chưa verify email.",
                    "code": "EMAIL_VERIFICATION_REQUIRED",
                    "status": user_obj.status,
                    "is_email_verified": False
                }, status=403)

        set_current_tenant_id(workspace_id)


        try:
            response = self.get_response(request)
        finally:
            set_current_tenant_id(None)

        return response


class TenantManager(models.Manager):
    """
    Custom Django Manager that automatically filters QuerySets by current tenant_id / workspace_id.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant_id()
        if tenant_id:
            field_names = [f.name for f in self.model._meta.get_fields()]
            if 'user_id' in field_names:
                return qs.filter(user_id=tenant_id)
            elif 'workspace' in field_names or 'workspace_id' in field_names:
                return qs.filter(workspace_id=tenant_id)
        return qs

