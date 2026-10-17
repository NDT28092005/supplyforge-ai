import jwt
import hashlib
import logging
import re
import threading
import time
from django.core.cache import cache
from django.conf import settings
from django.db import models
from django.http import JsonResponse
from supplyforge.permissions import get_user_permissions
from supplyforge.request_identity import get_client_ip

logger = logging.getLogger(__name__)
_thread_locals = threading.local()


def get_current_tenant_id():
    return getattr(_thread_locals, 'tenant_id', None)


def set_current_tenant_id(tenant_id):
    _thread_locals.tenant_id = tenant_id


def get_current_user_id():
    return getattr(_thread_locals, 'user_id', None)


def set_current_tenant_context(tenant_id, user_id=None):
    _thread_locals.tenant_id = tenant_id
    _thread_locals.user_id = user_id


class TenantIsolationMiddleware:
    """
    TEN-003 & TEN-002: Application-level Security & Tenant Context Middleware.
    Extracts user, tenant_id, role, and permissions for EVERY incoming HTTP request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auth_header = (request.headers.get('Authorization') or '').strip()
        user_id = None
        email = None
        tenant_id = None
        workspace_id = None
        role = None
        user_obj = None
        request.jwt_payload = None
        request.tenant_context_validated = False

        def auth_error(code, message):
            return JsonResponse({"error": message, "code": code}, status=401)

        if auth_header:
            # Any supplied Authorization value must be a complete Bearer token.
            # In particular, do not silently treat an invalid token as anonymous.
            if not re.fullmatch(r'Bearer\s+\S+', auth_header, flags=re.IGNORECASE):
                return auth_error(
                    "MALFORMED_AUTHORIZATION",
                    "Authorization header không hợp lệ.",
                )

            token_str = auth_header.split(None, 1)[1].strip()
            try:
                payload = jwt.decode(
                    token_str,
                    settings.SECRET_KEY,
                    algorithms=['HS256'],
                    options={'require': ['exp', 'user_id']},
                )
            except jwt.ExpiredSignatureError:
                return auth_error("EXPIRED_TOKEN", "Phiên đăng nhập đã hết hạn.")
            except jwt.InvalidTokenError:
                return auth_error("INVALID_TOKEN", "Bearer token không hợp lệ.")

            user_id = payload.get('user_id')
            from supplyforge.models import User
            try:
                user_obj = User.objects.get(id=user_id)
            except (TypeError, ValueError, User.DoesNotExist):
                return auth_error("INVALID_TOKEN", "Bearer token không hợp lệ.")

            if user_obj.status in [User.STATUS_DISABLED, User.STATUS_LOCKED]:
                return auth_error("ACCOUNT_INACTIVE", "Tài khoản không còn hoạt động.")

            raw_workspace_id = payload.get('workspace_id')
            try:
                workspace_id = int(raw_workspace_id)
                if workspace_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return auth_error("INVALID_TOKEN", "Bearer token không có workspace hợp lệ.")

            user_id = user_obj.id
            email = user_obj.email
            # Role is resolved from the current server-side user record rather
            # than trusting a stale claim. Never default an anonymous request
            # to an elevated role.
            role = user_obj.role or None
            # Canonical tenant identity is derived from the validated
            # workspace claim; an optional client-controlled claim must not
            # override it.
            tenant_id = f"T{workspace_id:03d}"
            request.jwt_payload = payload
            request.tenant_context_validated = True

        path = request.path_info
        public_path = self._is_public_path(path)
        is_options = request.method == 'OPTIONS'

        # In deployed environments, all API endpoints outside the explicit
        # public allowlist require a validated Bearer token. Development keeps
        # anonymous requests reachable for local read-only tooling, but still
        # attaches no tenant context and never grants a role.
        if (
            not user_id
            and not is_options
            and getattr(settings, 'IS_DEPLOYED', False)
            and path.startswith('/api/')
            and not public_path
        ):
            return auth_error(
                "UNAUTHENTICATED",
                "Yêu cầu cần Authorization Bearer token.",
            )

        permissions = get_user_permissions(role)

        # TEN-003: Attach Tenant Context to request object
        request.user_id = user_id
        request.user_email = email
        request.workspace_id = workspace_id
        request.tenant_id = tenant_id
        request.authenticated_tenant_id = tenant_id if request.tenant_context_validated else None
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
        exempt_paths = [
            '/api/auth/register', '/api/v1/auth/register',
            '/api/auth/verify-email', '/api/v1/auth/verify-email',
            '/api/auth/resend-verification', '/api/v1/auth/resend-verification',
            '/api/auth/login', '/api/v1/auth/login',
            '/api/auth/forgot-password', '/api/v1/auth/forgot-password',
            '/api/auth/reset-password', '/api/v1/auth/reset-password',
            '/api/v1/ping'
        ]

        if user_obj and not any(path.startswith(p) for p in exempt_paths):
            from supplyforge.models import User
            if user_obj and (user_obj.status in [User.STATUS_PENDING, 'PENDING_VERIFICATION'] or not user_obj.is_email_verified):
                return JsonResponse({
                    "error": "Tài khoản chưa hoàn tất xác thực email (status = PENDING_VERIFICATION). Hệ thống không cấp quyền sử dụng các chức năng khi chưa verify email.",
                    "code": "EMAIL_VERIFICATION_REQUIRED",
                    "status": user_obj.status,
                    "is_email_verified": False
                }, status=403)

        # TEN-001 & TEN-002: Workspace URL Level Access Control (Tenant Isolation)
        ws_match = re.search(r'/workspaces?/(\d+)', request.path_info)
        if ws_match:
            target_ws_id = int(ws_match.group(1))
            if not user_id:
                return JsonResponse({
                    "error": "Yêu cầu chưa được xác thực (Authorization header missing or invalid).",
                    "code": "UNAUTHENTICATED"
                }, status=401)
            else:
                from supplyforge.models import WorkspaceMember, Workspace
                is_member = WorkspaceMember.objects.filter(workspace_id=target_ws_id, user_id=user_id).exists()
                is_owner = Workspace.objects.filter(id=target_ws_id, owner_id=user_id).exists()
                # A token is scoped to one active workspace. Membership in a
                # second workspace does not authorize switching this request
                # to it through a URL parameter.
                if target_ws_id != workspace_id or not (is_member or is_owner):
                    return JsonResponse({
                        "error": f"Không có quyền truy cập workspace {target_ws_id} (Tenant Isolation).",
                        "code": "WORKSPACE_ACCESS_DENIED"
                    }, status=403)

        # Most analytics/ingestion routes address a session by UUID. Enforce
        # ownership centrally so individual views cannot accidentally omit a
        # workspace filter.
        session_match = re.search(
            r'/sessions/([0-9a-fA-F-]{36})(?:/|$)',
            request.path_info,
        )
        if session_match:
            if not user_id:
                return JsonResponse({
                    "error": "Yêu cầu chưa được xác thực.",
                    "code": "UNAUTHENTICATED",
                }, status=401)
            from supplyforge.models import IngestionSession
            session = IngestionSession.objects.filter(
                id=session_match.group(1)
            ).only('workspace_id').first()
            if session and session.workspace_id != workspace_id:
                return JsonResponse({
                    "error": "Không có quyền truy cập phiên ingestion này.",
                    "code": "SESSION_ACCESS_DENIED",
                }, status=403)


        set_current_tenant_context(
            workspace_id if request.tenant_context_validated else None,
            user_id if request.tenant_context_validated else None,
        )
        try:
            response = self.get_response(request)
        finally:
            set_current_tenant_context(None, None)

        return response

    @staticmethod
    def _is_public_path(path):
        """Return whether ``path`` is intentionally reachable without JWT."""
        public_prefixes = (
            '/health/',
            '/api/v1/health/',
            '/api/v1/ping',
            '/api/version',
            '/api/v1/version',
            '/api/auth/register',
            '/api/v1/auth/register',
            '/api/auth/verify-email',
            '/api/v1/auth/verify-email',
            '/api/auth/resend-verification',
            '/api/v1/auth/resend-verification',
            '/api/auth/login',
            '/api/v1/auth/login',
            '/api/auth/forgot-password',
            '/api/v1/auth/forgot-password',
            '/api/auth/reset-password',
            '/api/v1/auth/reset-password',
            '/api/auth/refresh',
            '/api/v1/auth/refresh',
            '/api/auth/google/',
            '/api/v1/auth/google/',
            '/api/v1/about_us',
            '/api/v1/services',
            '/api/v1/blog',
            '/api/v1/shopee/oauth/',
            '/api/v1/shopee/webhook',
        )
        return path == '/' or path.startswith(public_prefixes)


class TenantManager(models.Manager):
    """
    Custom Django Manager that automatically filters QuerySets by current tenant_id / workspace_id.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant_id()
        user_id = get_current_user_id()
        field_names = {f.name for f in self.model._meta.get_fields()}

        if 'workspace_id' in field_names or 'workspace' in field_names:
            workspace_id = self._workspace_id(tenant_id)
            return qs.filter(workspace_id=workspace_id) if workspace_id else qs.none()
        if 'tenant_id' in field_names:
            canonical_tenant_id = self._tenant_id(tenant_id)
            return (
                qs.filter(tenant_id=canonical_tenant_id)
                if canonical_tenant_id else qs.none()
            )
        if 'user_id' in field_names:
            return qs.filter(user_id=str(user_id)) if user_id is not None else qs.none()

        # A manager declared for a tenant-scoped model must never silently
        # fall back to an unfiltered queryset.
        return qs.none()

    @staticmethod
    def _workspace_id(value):
        """Normalize integer, ``T001`` and ``W001`` workspace identities."""
        if value is None:
            return None
        raw_value = str(value).strip()
        if raw_value[:1].upper() in {'T', 'W'}:
            raw_value = raw_value[1:]
        try:
            workspace_id = int(raw_value)
        except (TypeError, ValueError):
            return None
        return workspace_id if workspace_id > 0 else None

    @classmethod
    def _tenant_id(cls, value):
        workspace_id = cls._workspace_id(value)
        return f'T{workspace_id:03d}' if workspace_id else None


class APIRateLimiterMiddleware:
    """Atomic fixed-window API limiter backed by the configured Django cache."""

    _AUTH_PREFIXES = ('/api/auth/', '/api/v1/auth/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, 'RATE_LIMIT_ENABLED', False):
            return self.get_response(request)
        if request.method == 'OPTIONS' or not request.path_info.startswith('/api/'):
            return self.get_response(request)
        if request.path_info in {
            '/api/v1/ping',
            '/api/version',
            '/api/v1/version',
        }:
            return self.get_response(request)

        limit = self._limit_for(request.path_info)
        window = max(1, int(getattr(settings, 'RATE_LIMIT_WINDOW_SECONDS', 60)))
        identity = self._identity_for(request)
        bucket = int(time.time() // window)
        cache_key = (
            f"sf:api-rate:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}:"
            f"{bucket}:{limit}"
        )

        try:
            count = self._increment(cache_key, window)
        except Exception:
            logger.exception('API rate limiter backend unavailable')
            if getattr(settings, 'RATE_LIMIT_FAIL_CLOSED', False):
                return JsonResponse(
                    {
                        'error': 'Dịch vụ kiểm soát lưu lượng tạm thời không khả dụng.',
                        'code': 'RATE_LIMIT_UNAVAILABLE',
                    },
                    status=503,
                    headers={'Retry-After': '5'},
                )
            return self.get_response(request)

        if count > limit:
            retry_after = max(1, window - (int(time.time()) % window))
            response = JsonResponse(
                {
                    'error': 'Quá nhiều yêu cầu. Vui lòng thử lại sau.',
                    'code': 'RATE_LIMITED',
                },
                status=429,
            )
            response['Retry-After'] = str(retry_after)
            response['X-RateLimit-Limit'] = str(limit)
            response['X-RateLimit-Remaining'] = '0'
            return response

        response = self.get_response(request)
        response['X-RateLimit-Limit'] = str(limit)
        response['X-RateLimit-Remaining'] = str(max(0, limit - count))
        return response

    @staticmethod
    def _increment(cache_key, timeout):
        # cache.add + cache.incr maps to Redis INCR/EXPIRE semantics without a
        # read-modify-write race. Retry once if the key expires between calls.
        if cache.add(cache_key, 1, timeout=timeout):
            return 1
        try:
            return int(cache.incr(cache_key))
        except ValueError:
            if cache.add(cache_key, 1, timeout=timeout):
                return 1
            return int(cache.incr(cache_key))

    @classmethod
    def _limit_for(cls, path):
        if path.startswith(cls._AUTH_PREFIXES):
            return int(getattr(settings, 'RATE_LIMIT_AUTH_REQUESTS', 20))
        if '/ingestion/upload' in path or '/sync/' in path:
            return int(getattr(settings, 'RATE_LIMIT_UPLOAD_REQUESTS', 10))
        return int(getattr(settings, 'RATE_LIMIT_API_REQUESTS', 120))

    @staticmethod
    def _identity_for(request):
        if (
            getattr(request, 'tenant_context_validated', False)
            and getattr(request, 'user_id', None)
            and getattr(request, 'workspace_id', None)
        ):
            return f"user:{request.user_id}:workspace:{request.workspace_id}"

        # This middleware intentionally runs before tenant authentication. A
        # valid token can still receive a stable user bucket without querying
        # the database; invalid/malformed tokens fall back to the peer IP.
        auth_header = (request.headers.get('Authorization') or '').strip()
        if re.fullmatch(r'Bearer\s+\S+', auth_header, flags=re.IGNORECASE):
            try:
                payload = jwt.decode(
                    auth_header.split(None, 1)[1],
                    settings.SECRET_KEY,
                    algorithms=['HS256'],
                    options={'require': ['exp', 'user_id']},
                )
                workspace_id = int(payload.get('workspace_id'))
                if payload.get('user_id') and workspace_id > 0:
                    return f"user:{payload['user_id']}:workspace:{workspace_id}"
            except (jwt.InvalidTokenError, TypeError, ValueError):
                pass
        return f"ip:{get_client_ip(request)}"


class SecurityHeadersMiddleware:
    """Apply headers that are not fully covered by Django SecurityMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': getattr(settings, 'X_FRAME_OPTIONS', 'DENY'),
            'Referrer-Policy': getattr(
                settings,
                'SECURE_REFERRER_POLICY',
                'strict-origin-when-cross-origin',
            ),
            'Content-Security-Policy': getattr(
                settings,
                'CONTENT_SECURITY_POLICY',
                "default-src 'self'; object-src 'none'; frame-ancestors 'none'",
            ),
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        }
        version_match = re.match(r'^/api/(v[0-9]+)/', request.path_info)
        if version_match:
            headers['X-API-Version'] = version_match.group(1)
        elif request.path_info.startswith('/api/'):
            headers['X-API-Version'] = 'v1'
            headers['Deprecation'] = 'true'
        for name, value in headers.items():
            if name not in response:
                response[name] = value
        return response
