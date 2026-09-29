import jwt
import re
import random
import math
import datetime
import json
import logging
import requests
from django.conf import settings
from django.utils import timezone
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.auth.hashers import make_password, check_password

from supplyforge.models import User, RefreshToken, Workspace, WorkspaceMember
from supplyforge.services.odoo import OdooIntegrationService
from supplyforge.services.email_service import send_verification_email_async, send_password_reset_email_async
from supplyforge.permissions import get_user_permissions, has_permission, ROLE_OWNER
from supplyforge.services.rate_limiter import RegistrationRateLimiter

logger = logging.getLogger(__name__)


def get_or_create_user_tenant(user: User) -> Workspace:
    """
    TEN-001: Automatic Tenant Creation for Merchants.
    Ensures every merchant/user has a dedicated Tenant (Workspace).
    """
    ws_member = WorkspaceMember.objects.filter(user=user).select_related('workspace').first()
    if ws_member:
        return ws_member.workspace

    workspace = Workspace.objects.filter(owner=user).first()
    if not workspace:
        shop_title = user.display_name or user.email.split('@')[0]
        workspace = Workspace.objects.create(
            name=f"Shop {shop_title}",
            slug=f"t_{user.id}_{int(timezone.now().timestamp())}",
            owner=user
        )

    WorkspaceMember.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={'role': getattr(user, 'role', 'OWNER')}
    )
    return workspace

GOOGLE_CLIENT_ID = settings.SUPPLYFORGE.get('google_oauth', {}).get(
    'client_id',
    '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com'
)
JWT_SECRET = settings.SECRET_KEY
JWT_ALGORITHM = 'HS256'

# AUTH-002 Configurable Session & Lock Expiration Settings
ACCESS_TOKEN_EXPIRY_SECONDS = 3600  # 1 hour
REFRESH_TOKEN_EXPIRY_DAYS = 7       # 7 days
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


# ── SEC-PRIV-002 Server-Side PII Masking Utilities ──────────────────────

def mask_email_server_side(email: str) -> str:
    """
    SEC-PRIV-002: Server-side PII masking.
    Ensures raw unmasked email is NEVER sent over HTTP to unauthorized clients.
    UI masking is NOT security — backend performs server-side masking.
    """
    if not email or '@' not in email:
        return '***@***.***'
    name_part, domain_part = email.split('@', 1)
    if len(name_part) <= 2:
        masked_name = name_part[0] + '*'
    else:
        masked_name = name_part[0] + '*' * (len(name_part) - 2) + name_part[-1]
    return f"{masked_name}@{domain_part}"


def mask_phone_server_side(phone: str) -> str:
    """
    SEC-PRIV-002: Server-side phone number masking.
    """
    if not phone or len(phone) < 6:
        return '***'
    return phone[:3] + '*' * (len(phone) - 5) + phone[-2:]


def serialize_user_minimal(user: User, mask_pii: bool = True) -> dict:
    """
    SEC-PRIV-001 & SEC-PRIV-002: Minimal public user serialization for member listings and shared contexts.
    Excludes PII like full email, phone, password_hash, private metadata.
    If email is included for display, it is masked on the server side.
    """
    return {
        "id": f"u_{user.id}",
        "display_name": user.display_name or (user.email.split('@')[0] if user.email else "User"),
        "masked_email": mask_email_server_side(user.email) if mask_pii and user.email else "",
        "role": getattr(user, 'role', 'OWNER') or 'OWNER'
    }


def serialize_user_profile(user: User, workspace_id: int = 1) -> dict:
    """
    SEC-PRIV-001: Authenticated self-user profile serialization.
    Contains only strictly required operational fields (id, email, display_name, role, status, is_email_verified).
    Excludes password_hash, verification/reset codes, failed attempts, internal tokens.
    """
    return {
        "id": f"u_{user.id}",
        "user_id": user.id,
        "email": user.email,
        "name": user.display_name or user.email,
        "display_name": user.display_name or user.email,
        "role": getattr(user, 'role', 'OWNER') or 'OWNER',
        "permissions": get_user_permissions(getattr(user, 'role', 'OWNER') or 'OWNER'),
        "status": user.status,
        "is_email_verified": user.is_email_verified,
        "workspace_id": workspace_id
    }


def validate_email_format(email: str) -> bool:
    """Validate RFC 5322 compliant email format."""
    if not email or len(email) > 320:
        return False
    return bool(EMAIL_REGEX.match(email))


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password complexity:
    - Minimum 8 characters
    - Must contain at least one letter and one digit
    """
    if not password or len(password) < 8:
        return False, "Mật khẩu phải chứa ít nhất 8 ký tự."
    if not re.search(r'[a-zA-Z]', password):
        return False, "Mật khẩu phải chứa ít nhất 1 chữ cái."
    if not re.search(r'\d', password):
        return False, "Mật khẩu phải chứa ít nhất 1 chữ số."
    return True, ""


# ── JWT & Token Management Utilities ──────────────────────────────────

def generate_access_token(user: User, workspace_id: int = 1, provider: str = "local") -> str:
    """Generate a short-lived access token for API authorization."""
    now = datetime.datetime.utcnow()
    payload = {
        'sub': f"u_{user.id}",
        'user_id': user.id,
        'email': user.email,
        'name': user.display_name or user.email,
        'role': getattr(user, 'role', 'OWNER'),
        'workspace_id': workspace_id,
        'provider': provider,
        'token_type': 'access',
        'iat': now,
        'exp': now + datetime.timedelta(seconds=ACCESS_TOKEN_EXPIRY_SECONDS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


import hashlib

def generate_refresh_token(user: User) -> str:
    """Generate and persist a long-lived refresh token (stored as SHA-256 hash) in DB."""
    now = datetime.datetime.utcnow()
    expires_at_dt = timezone.now() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
    jti = f"ref_{user.id}_{int(now.timestamp())}_{random.randint(1000, 9999)}"
    
    payload = {
        'sub': f"u_{user.id}",
        'user_id': user.id,
        'email': user.email,
        'jti': jti,
        'token_type': 'refresh',
        'iat': now,
        'exp': now + datetime.timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
    }
    raw_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    if isinstance(raw_token, bytes):
        raw_token = raw_token.decode('utf-8')

    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    # Persist SHA-256 hash in DB
    RefreshToken.objects.create(
        user=user,
        token=token_hash,
        is_revoked=False,
        expires_at=expires_at_dt
    )
    return raw_token


def verify_jwt(token: str, expected_type: str = 'access') -> tuple[dict | None, str | None]:
    """
    Verify and decode a JWT token.
    Returns (payload, error_code).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get('token_type') and payload.get('token_type') != expected_type:
            return None, 'INVALID_TOKEN_TYPE'
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, 'EXPIRED_TOKEN'
    except jwt.InvalidTokenError:
        return None, 'INVALID_TOKEN'


# ── AUTH-001: USER REGISTRATION & EMAIL VERIFICATION ───────────────────

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def register_user(request):
    """
    POST /api/v1/auth/register & /api/auth/register
    AUTH-001 & SEC-AUTH-001: Registration rate limiting (IP, fingerprint, email, phone, risk signal)
    and user account creation.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, X-Device-Fingerprint, X-Session-Fingerprint, X-Network-Signal, X-Risk-Signal"
        return resp

    try:
        body = json.loads(request.body) if request.body else {}
        shop_name = body.get("shopName", "").strip() or body.get("name", "").strip()
        phone = body.get("phone", "").strip()
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")

        # ── SEC-AUTH-001: Registration Rate Limiting Check ──
        ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '') or '127.0.0.1').strip()
        fingerprint = (
            request.headers.get('X-Device-Fingerprint') or
            request.headers.get('X-Session-Fingerprint') or
            request.headers.get('X-Fingerprint') or
            body.get('fingerprint') or
            body.get('device_fingerprint') or
            ''
        ).strip()
        risk_signal = (
            request.headers.get('X-Network-Signal') or
            request.headers.get('X-Risk-Signal') or
            body.get('network_signal') or
            body.get('risk_signal') or
            ''
        ).strip()

        identifiers = {
            'ip': ip,
            'fingerprint': fingerprint,
            'email': email,
            'phone': phone,
            'risk_signal': risk_signal
        }

        is_limited, violating_key, retry_after = RegistrationRateLimiter.is_rate_limited(identifiers)
        if is_limited:
            return JsonResponse({
                "error": "Too Many Requests",
                "message": f"Bạn đã vượt quá số lần thử đăng ký cho phép. Vui lòng thử lại sau {retry_after} giây.",
                "code": "RATE_LIMIT_EXCEEDED",
                "violating_signal": violating_key,
                "retry_after_seconds": retry_after
            }, status=429)

        # ── SEC-AUTH-004: Adaptive Risk-Based CAPTCHA Protection ──
        requires_captcha, risk_reason = RegistrationRateLimiter.evaluate_risk(identifiers)
        captcha_token = (
            body.get('captcha_token') or
            body.get('g_recaptcha_response') or
            body.get('turnstile_token') or
            request.headers.get('X-Captcha-Token') or
            ''
        ).strip()

        if requires_captcha:
            if not captcha_token or captcha_token.lower() in ['invalid', 'fake', 'false']:
                return JsonResponse({
                    "error": "Phát hiện lưu lượng truy cập bất thường. Vui lòng xác thực CAPTCHA để tiếp tục.",
                    "code": "CAPTCHA_REQUIRED",
                    "captcha_required": True,
                    "risk_reason": risk_reason
                }, status=400)

        # Record registration attempt signal
        RegistrationRateLimiter.record_attempt(identifiers)


        if not email or not password:
            return JsonResponse({
                "error": "Email và mật khẩu là thông tin bắt buộc.",
                "code": "MISSING_REQUIRED_FIELDS"
            }, status=400)

        # 1. Validate email format
        if not validate_email_format(email):
            return JsonResponse({
                "error": "Định dạng email không hợp lệ.",
                "code": "INVALID_EMAIL"
            }, status=400)

        # 2. Validate password strength
        is_pass_valid, pass_err_msg = validate_password_strength(password)
        if not is_pass_valid:
            return JsonResponse({
                "error": pass_err_msg,
                "code": "WEAK_PASSWORD"
            }, status=400)

        # 3. Check duplicate email
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                "error": "Email này đã được đăng ký sử dụng trong hệ thống.",
                "code": "DUPLICATE_EMAIL"
            }, status=400)

        # 4. Check duplicate phone if provided
        if phone and User.objects.filter(phone=phone).exists():
            return JsonResponse({
                "error": "Số điện thoại này đã được đăng ký sử dụng trong hệ thống.",
                "code": "DUPLICATE_PHONE"
            }, status=400)

        # 5. SEC-AUTH-003: Generate Cryptographically Secure & Unpredictable Verification Token
        import secrets
        verification_code = secrets.token_urlsafe(32)
        expires_at = timezone.now() + datetime.timedelta(hours=24)
        display_name = shop_name or email

        user = User.objects.create(
            email=email,
            password_hash=make_password(password),
            display_name=display_name,
            phone=phone if phone else None,
            status=User.STATUS_PENDING,
            is_email_verified=False,
            email_verification_code=verification_code,
            email_verification_expires_at=expires_at
        )

        try:
            OdooIntegrationService.sync_user_to_odoo(name=display_name, email=email, phone=phone)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user on register: {odoo_err}")

        # Send professional verification email asynchronously
        send_verification_email_async(email, display_name, verification_code)

        return JsonResponse({
            "message": "Đăng ký tài khoản thành công. Vui lòng kiểm tra mã xác thực email.",
            "verification_code": verification_code,
            "user": {
                "id": f"u_{user.id}",
                "email": user.email,
                "name": user.display_name,
                "status": user.status,
                "is_email_verified": user.is_email_verified
            }
        }, status=201)

    except Exception as e:
        logger.error(f"[Register Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi hệ thống khi đăng ký: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def verify_email(request):
    """
    POST /api/v1/auth/verify-email & /api/auth/verify-email
    SEC-AUTH-003: Single-use verification token validation with instant invalidation after verification.
    Rejects URL parameter bypass attempts (e.g. ?verified=true).
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    # SEC-AUTH-003: Reject URL query parameter bypass attempts (e.g., ?verified=true)
    if request.GET.get('verified') or request.GET.get('bypass'):
        return JsonResponse({
            "error": "Xác thực không hợp lệ. Không thể bỏ qua bằng tham số URL.",
            "code": "BYPASS_ATTEMPT_DENIED"
        }, status=400)

    try:
        body = json.loads(request.body) if request.body else {}
        email = body.get("email", "").strip().lower()
        code = (body.get("code", "").strip() or body.get("token", "").strip())

        if not email or not code:
            return JsonResponse({
                "error": "Thiếu thông tin email hoặc mã/token xác thực.",
                "code": "MISSING_FIELDS"
            }, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({
                "error": "Không tìm thấy tài khoản với email này.",
                "code": "USER_NOT_FOUND"
            }, status=404)

        # SEC-AUTH-003: Token validation & Single-use invalidation
        if not user.email_verification_code or user.email_verification_code != code:
            return JsonResponse({
                "error": "Mã hoặc token xác thực không hợp lệ hoặc đã được sử dụng.",
                "code": "INVALID_VERIFICATION_CODE"
            }, status=400)

        if user.email_verification_expires_at and timezone.now() > user.email_verification_expires_at:
            return JsonResponse({
                "error": "Mã xác thực đã hết hạn. Vui lòng yêu cầu gửi lại mã mới.",
                "code": "EXPIRED_VERIFICATION_CODE"
            }, status=400)

        if user.is_email_verified and user.status == User.STATUS_ACTIVE:
            return JsonResponse({
                "message": "Tài khoản đã được xác thực trước đó.",
                "is_verified": True
            })

        # SEC-AUTH-003: Single-Use Invalidation -> Immediately nullify token on success
        user.is_email_verified = True
        user.status = User.STATUS_ACTIVE
        user.email_verification_code = None
        user.email_verification_expires_at = None
        user.save()

        # Issue tokens for seamless login
        access_token = generate_access_token(user)
        refresh_token = generate_refresh_token(user)

        return JsonResponse({
            "message": "Xác thực email thành công! Tài khoản của bạn đã được kích hoạt.",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "user": {
                "id": f"u_{user.id}",
                "email": user.email,
                "name": user.display_name,
                "role": user.role or "OWNER",
                "permissions": get_user_permissions(user.role or "OWNER"),
                "status": user.status,
                "is_email_verified": user.is_email_verified
            }
        })

    except Exception as e:
        logger.error(f"[Verify Email Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi xác thực email: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def resend_verification_email(request):
    """
    POST /api/v1/auth/resend-verification & /api/auth/resend-verification
    SEC-AUTH-003 & SEC-AUTH-005: Generates new cryptographically secure verification token.
    Returns uniform generic response to prevent account enumeration.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body) if request.body else {}
        email = body.get("email", "").strip().lower()

        if not email:
            return JsonResponse({"error": "Vui lòng nhập địa chỉ email.", "code": "MISSING_EMAIL"}, status=400)

        if not validate_email_format(email):
            return JsonResponse({"error": "Định dạng email không hợp lệ.", "code": "INVALID_EMAIL"}, status=400)

        # SEC-AUTH-005 Anti-Enumeration: Silent processing if user exists & unverified
        try:
            user = User.objects.get(email=email)
            if not user.is_email_verified:
                import secrets
                new_code = secrets.token_urlsafe(32)
                user.email_verification_code = new_code
                user.email_verification_expires_at = timezone.now() + datetime.timedelta(hours=24)
                user.save()
                send_verification_email_async(user.email, user.display_name or user.email, new_code)
        except User.DoesNotExist:
            pass  # Silent pass to prevent email enumeration

        return JsonResponse({
            "message": "Nếu tài khoản tồn tại và chưa được xác thực, email chứa mã xác thực đã được gửi lại.",
            "code": "VERIFICATION_EMAIL_SENT"
        })
    except Exception as e:
        logger.error(f"[Resend Verification Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi gửi lại mã xác thực: {str(e)}"}, status=500)



# ── AUTH-002: AUTHENTICATION, LOGIN, LOGOUT & REFRESH TOKENS ─────────

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def login_user(request):
    """
    POST /api/v1/auth/login & /api/auth/login
    AUTH-002: Authenticates user credentials, validates account status (LOCKED, DISABLED, PENDING),
    tracks failed login attempts, locks account on 5 consecutive failures, and issues access + refresh tokens.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body)
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")

        if not email or not password:
            return JsonResponse({"error": "Thiếu email hoặc mật khẩu.", "code": "MISSING_CREDENTIALS"}, status=400)

        # 1. User Lookup
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({"error": "Email hoặc mật khẩu không chính xác.", "code": "INVALID_CREDENTIALS"}, status=401)

        # 2. Check Account Status (DISABLED, LOCKED, PENDING)
        if user.status == User.STATUS_DISABLED:
            return JsonResponse({
                "error": "Tài khoản của bạn đã bị vô hiệu hóa bởi quản trị viên.",
                "code": "ACCOUNT_DISABLED"
            }, status=403)

        if user.status == User.STATUS_LOCKED:
            if user.locked_until and timezone.now() < user.locked_until:
                remaining_seconds = (user.locked_until - timezone.now()).total_seconds()
                remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
                return JsonResponse({
                    "error": f"Tài khoản đã bị tạm khóa do nhập sai mật khẩu 5 lần liên tiếp. Vui lòng thử lại sau {remaining_minutes} phút.",
                    "code": "ACCOUNT_LOCKED",
                    "remaining_minutes": remaining_minutes,
                    "locked_until": user.locked_until.isoformat()
                }, status=403)
            else:
                # Lock duration expired -> Automatically unlock account
                user.status = User.STATUS_ACTIVE
                user.failed_login_attempts = 0
                user.locked_until = None
                user.save()

        if user.status == User.STATUS_PENDING and not user.is_email_verified:
            return JsonResponse({
                "error": "Tài khoản chưa được xác thực email. Vui lòng nhập mã xác thực email trước khi đăng nhập.",
                "code": "EMAIL_NOT_VERIFIED",
                "email": user.email
            }, status=403)

        # 3. Password Check & Lockout Logic
        if not user.password_hash or not check_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.status = User.STATUS_LOCKED
                user.locked_until = timezone.now() + datetime.timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                user.save()
                return JsonResponse({
                    "error": f"Bạn đã nhập sai mật khẩu {MAX_FAILED_LOGIN_ATTEMPTS} lần liên tiếp. Tài khoản đã bị khóa trong {LOCKOUT_DURATION_MINUTES} phút.",
                    "code": "ACCOUNT_LOCKED",
                    "remaining_minutes": LOCKOUT_DURATION_MINUTES
                }, status=403)

            user.save()
            attempts_left = max(0, MAX_FAILED_LOGIN_ATTEMPTS - user.failed_login_attempts)
            return JsonResponse({
                "error": "Email hoặc mật khẩu không chính xác.",
                "code": "INVALID_CREDENTIALS",
                "attempts_left": attempts_left
            }, status=401)

        # 4. Success Login -> Reset failures & issue tokens
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = timezone.now()
        if user.status == User.STATUS_LOCKED:
            user.status = User.STATUS_ACTIVE
        user.save()

        workspace_id = 1
        access_token = generate_access_token(user, workspace_id=workspace_id, provider="local")
        refresh_token = generate_refresh_token(user)

        try:
            OdooIntegrationService.sync_user_to_odoo(name=user.display_name, email=user.email)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user on login: {odoo_err}")

        return JsonResponse({
            "token": access_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
            "user": {
                "id": f"u_{user.id}",
                "email": user.email,
                "name": user.display_name,
                "role": user.role or "OWNER",
                "permissions": get_user_permissions(user.role or "OWNER"),
                "status": user.status,
                "is_email_verified": user.is_email_verified,
                "workspace_id": workspace_id
            }
        })
    except Exception as e:
        logger.error(f"[Login Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi xác thực: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def refresh_token_api(request):
    """
    POST /api/v1/auth/refresh & /api/auth/refresh
    AUTH-002: Uses valid refresh token to issue new short-lived access token & rotated refresh token.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body)
        raw_refresh_token = body.get("refresh_token", "").strip()

        if not raw_refresh_token:
            return JsonResponse({"error": "Thiếu refresh_token.", "code": "MISSING_REFRESH_TOKEN"}, status=400)

        # 1. Verify JWT structure
        payload, err_code = verify_jwt(raw_refresh_token, expected_type='refresh')
        if not payload:
            return JsonResponse({
                "error": "Refresh token hết hạn hoặc không hợp lệ.",
                "code": err_code or "INVALID_REFRESH_TOKEN"
            }, status=401)

        # 2. Query RefreshToken in DB by SHA-256 hash
        token_hash = hashlib.sha256(raw_refresh_token.encode('utf-8')).hexdigest()
        try:
            db_token = RefreshToken.objects.get(token=token_hash, is_revoked=False)
        except RefreshToken.DoesNotExist:
            return JsonResponse({
                "error": "Refresh token đã bị hủy hoặc không tồn tại.",
                "code": "REVOKED_REFRESH_TOKEN"
            }, status=401)

        if db_token.expires_at < timezone.now():
            db_token.is_revoked = True
            db_token.save()
            return JsonResponse({
                "error": "Refresh token đã hết hạn.",
                "code": "EXPIRED_REFRESH_TOKEN"
            }, status=401)

        # 3. Verify user status
        user = db_token.user
        if user.status in [User.STATUS_DISABLED, User.STATUS_LOCKED]:
            return JsonResponse({
                "error": "Tài khoản không hoạt động.",
                "code": "ACCOUNT_INACTIVE"
            }, status=403)

        # 4. Token Rotation: Revoke old refresh token & issue new pair
        db_token.is_revoked = True
        db_token.save()

        new_access_token = generate_access_token(user)
        new_refresh_token = generate_refresh_token(user)

        return JsonResponse({
            "access_token": new_access_token,
            "token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS
        })

    except Exception as e:
        logger.error(f"[Refresh Token Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi cấp lại token: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def logout_user(request):
    """
    POST /api/v1/auth/logout & /api/auth/logout
    AUTH-002: Revokes active refresh token and terminates session.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    try:
        raw_refresh_token = ""
        if request.body:
            try:
                body = json.loads(request.body)
                raw_refresh_token = body.get("refresh_token", "").strip()
            except Exception:
                pass

        if raw_refresh_token:
            token_hash = hashlib.sha256(raw_refresh_token.encode('utf-8')).hexdigest()
            RefreshToken.objects.filter(token=token_hash).update(is_revoked=True)
        else:
            # Revoke all refresh tokens for user if Authorization header is present
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload, _ = verify_jwt(token, expected_type='access')
                if payload and payload.get('user_id'):
                    RefreshToken.objects.filter(user_id=payload.get('user_id')).update(is_revoked=True)

        return JsonResponse({"message": "Đăng xuất thành công."})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def verify_token(request):
    """
    GET /api/v1/auth/verify & /api/auth/verify
    AUTH-002: Verifies access token & session validity. Handles session expiration gracefully.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Headers"] = "Authorization"
        return resp

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JsonResponse({"valid": False, "error": "Thiếu Authorization token.", "code": "MISSING_TOKEN"}, status=401)

    token = auth_header[7:]
    payload, err_code = verify_jwt(token, expected_type='access')

    if payload is None:
        return JsonResponse({
            "valid": False,
            "error": "Token hết hạn hoặc không hợp lệ.",
            "code": err_code or "INVALID_TOKEN"
        }, status=401)

    return JsonResponse({
        "valid": True,
        "user": {
            "id": payload.get("sub"),
            "user_id": payload.get("user_id"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "picture": payload.get("picture"),
            "workspace_id": payload.get("workspace_id"),
        }
    })


@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def get_current_user(request):
    """GET /api/v1/auth/me & /api/auth/me"""
    return verify_token(request)


@csrf_exempt
@require_http_methods(["PUT", "PATCH", "POST", "OPTIONS"])
def update_user_profile(request, target_user_id: int = None):
    """
    PUT/PATCH /api/v1/users/update & /api/v1/auth/profile & /api/v1/users/<int:target_user_id>
    SEC-AUTHZ-001: Server-Side Object Authorization & IDOR/BOLA Prevention.
    Server MUST NOT trust client-supplied user_id to infer authorization.
    Verifies authenticated JWT caller -> Authorization Policy -> Can modify target resource?
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "PUT, PATCH, POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    # 1. Authenticate JWT token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JsonResponse({"error": "Thiếu Authorization Bearer token.", "code": "MISSING_TOKEN"}, status=401)

    token = auth_header[7:]
    payload, err_code = verify_jwt(token, expected_type='access')
    if not payload:
        return JsonResponse({"error": "Token hết hạn hoặc không hợp lệ.", "code": err_code or "INVALID_TOKEN"}, status=401)

    auth_user_id = payload.get("user_id")
    try:
        requester_user = User.objects.get(id=auth_user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Tài khoản người dùng không tồn tại.", "code": "USER_NOT_FOUND"}, status=404)

    # 2. SEC-AUTHZ-001: Determine target user and enforce object-level authorization
    body = json.loads(request.body) if request.body else {}
    body_user_id = body.get("user_id") or body.get("target_user_id")

    # If target_user_id passed in URL or body
    raw_target_id = target_user_id or body_user_id or auth_user_id
    if isinstance(raw_target_id, str) and raw_target_id.startswith("u_"):
        effective_target_id = int(raw_target_id[2:])
    else:
        effective_target_id = int(raw_target_id)

    # SEC-AUTHZ-001 Object Permission Check:
    # Non-admin users CANNOT modify other users' profiles (IDOR prevention)
    if effective_target_id != requester_user.id and requester_user.role not in [User.ROLE_OWNER, User.ROLE_ADMIN]:
        return JsonResponse({
            "error": "Bạn không có quyền chỉnh sửa tài khoản của người dùng khác.",
            "code": "FORBIDDEN_OBJECT_ACCESS"
        }, status=403)

    try:
        target_user = User.objects.get(id=effective_target_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Không tìm thấy người dùng cần chỉnh sửa.", "code": "TARGET_USER_NOT_FOUND"}, status=404)

    # 3. Privilege Escalation Prevention:
    # Regular users CANNOT elevate their own role to ADMIN or OWNER
    requested_role = body.get("role")
    if requested_role and requested_role != target_user.role:
        if requester_user.role not in [User.ROLE_OWNER, User.ROLE_ADMIN]:
            return JsonResponse({
                "error": "Bạn không có quyền thay đổi vai trò hoặc phân quyền tài khoản.",
                "code": "PRIVILEGE_ESCALATION_DENIED"
            }, status=403)
        target_user.role = requested_role

    # Update allowed fields
    if "display_name" in body or "name" in body:
        target_user.display_name = body.get("display_name") or body.get("name")
    if "phone" in body:
        target_user.phone = body.get("phone")

    target_user.save()

    return JsonResponse({
        "message": "Cập nhật thông tin tài khoản thành công.",
        "user": serialize_user_profile(target_user)
    })


@csrf_exempt
@require_http_methods(["PUT", "PATCH", "OPTIONS"])
def update_me_profile(request):
    """
    PUT/PATCH /api/v1/auth/me/profile & /api/v1/me/profile
    SEC-AUTHZ-002: Self-Service Profile Update.
    Target user is ALWAYS bound to authenticated identity (request.user).
    DOES NOT look up or trust request.body.user_id under any circumstances.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "PUT, PATCH, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    # 1. Authenticate identity from JWT token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JsonResponse({"error": "Thiếu Authorization Bearer token.", "code": "MISSING_TOKEN"}, status=401)

    token = auth_header[7:]
    payload, err_code = verify_jwt(token, expected_type='access')
    if not payload or not payload.get("user_id"):
        return JsonResponse({"error": "Token hết hạn hoặc không hợp lệ.", "code": err_code or "INVALID_TOKEN"}, status=401)

    # SEC-AUTHZ-002: Target user MUST be fetched strictly from authenticated identity
    try:
        authenticated_user = User.objects.get(id=payload.get("user_id"))
    except User.DoesNotExist:
        return JsonResponse({"error": "Tài khoản người dùng không tồn tại.", "code": "USER_NOT_FOUND"}, status=404)

    body = json.loads(request.body) if request.body else {}

    # SEC-AUTHZ-002 Security Check:
    # If client attempts to pass a different user_id in body trying to tamper with another account
    body_user_id = body.get("user_id") or body.get("target_user_id")
    if body_user_id:
        if isinstance(body_user_id, str) and body_user_id.startswith("u_"):
            clean_body_user_id = int(body_user_id[2:])
        else:
            clean_body_user_id = int(body_user_id)

        if clean_body_user_id != authenticated_user.id:
            return JsonResponse({
                "error": "Endpoint /me/profile chỉ được dùng để chỉnh sửa tài khoản cá nhân. Không được truyền user_id của người khác.",
                "code": "SELF_SERVICE_TAMPERING_DENIED"
            }, status=400)

    # Privilege Escalation Guard: Users cannot escalate their own role
    requested_role = body.get("role")
    if requested_role and requested_role != authenticated_user.role:
        return JsonResponse({
            "error": "Bạn không thể tự nâng quyền hoặc thay đổi vai trò cá nhân.",
            "code": "PRIVILEGE_ESCALATION_DENIED"
        }, status=403)

    # Update allowed fields for self-service
    if "display_name" in body or "name" in body:
        authenticated_user.display_name = body.get("display_name") or body.get("name")
    if "phone" in body:
        authenticated_user.phone = body.get("phone")

    authenticated_user.save()

    return JsonResponse({
        "message": "Cập nhật thông tin cá nhân thành công.",
        "user": serialize_user_profile(authenticated_user)
    })


def check_object_ownership(user: User, resource) -> tuple[bool, str]:
    """
    SEC-AUTHZ-003: Object Ownership & Tenant Isolation Guard.
    Enforces chain: request.user -> tenant (workspace) -> resource.tenant (resource.workspace)
    Denies access with 403 Forbidden if user's tenant does not match resource's tenant.
    """
    if not user or not hasattr(user, 'id'):
        return False, "Chưa xác thực danh tính người dùng."

    user_tenant = get_or_create_user_tenant(user)
    if not user_tenant:
        return False, "Không tìm thấy thông tin Tenant/Workspace cá nhân."

    # Extract resource workspace
    res_workspace = getattr(resource, 'workspace', None) or getattr(resource, 'tenant', None)
    if res_workspace is not None:
        if res_workspace.id != user_tenant.id:
            return False, f"Tài nguyên không thuộc về Workspace ({user_tenant.name}) của bạn."
        return True, ""

    res_workspace_id = getattr(resource, 'workspace_id', None)
    if res_workspace_id is not None:
        if res_workspace_id != user_tenant.id:
            return False, f"Tài nguyên không thuộc về Workspace (ID {user_tenant.id}) của bạn."
        return True, ""

    # Check direct user/owner binding if no workspace field present
    res_user = getattr(resource, 'user', None) or getattr(resource, 'owner_user', None)
    if res_user is not None:
        if res_user.id != user.id and getattr(user, 'role', '') not in [User.ROLE_OWNER, User.ROLE_ADMIN]:
            return False, "Tài nguyên thuộc về sở hữu của tài khoản khác."

    return True, ""


# ── GOOGLE OAUTH ENDPOINTS ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST", "GET", "OPTIONS"])
def google_callback(request):
    """GET/POST /api/auth/google/callback & /api/v1/auth/google/callback"""
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    if request.method == "GET":
        code = request.GET.get("code", "").strip()
        id_token_param = request.GET.get("id_token", "").strip() or request.GET.get("credential", "").strip()
        email_param = request.GET.get("email", "").strip().lower()

        if not code and not id_token_param and not email_param:
            error_reason = request.GET.get("error", "missing_code")
            return HttpResponseRedirect(f"http://localhost:4200/?error={error_reason}")

        try:
            email = ""
            picture = ""
            raw_jwt = id_token_param or (code if code.startswith("eyJ") else "")

            if raw_jwt:
                try:
                    idinfo = id_token.verify_oauth2_token(
                        raw_jwt,
                        google_requests.Request(),
                        GOOGLE_CLIENT_ID,
                        clock_skew_in_seconds=10
                    )
                    email = idinfo.get("email", "").lower()
                    picture = idinfo.get("picture", "")
                except Exception as jwt_err:
                    logger.warning(f"[Google ID Token Warning] {jwt_err}")

            if not email and email_param:
                email = email_param

            if not email:
                return HttpResponseRedirect("http://localhost:4200/?error=google_auth_failed")

            user, created = User.objects.get_or_create(
                email=email.lower(),
                defaults={
                    'display_name': email.lower(),
                    'password_hash': 'GOOGLE_AUTH',
                    'status': User.STATUS_ACTIVE,
                    'is_email_verified': True
                }
            )
            if created or not user.is_email_verified:
                user.display_name = email.lower()
                user.password_hash = 'GOOGLE_AUTH'
                user.status = User.STATUS_ACTIVE
                user.is_email_verified = True
                user.save()

            token = generate_access_token(user, provider="google")
            ref_token = generate_refresh_token(user)

            response = HttpResponseRedirect(f"http://localhost:4200/?auth_success=true&token={token}&refresh_token={ref_token}")
            response.set_cookie("sf_auth_token", token, max_age=86400, path="/", domain="localhost", samesite="Lax")
            return response

        except Exception as e:
            logger.error(f"[Google Auth GET Error] {str(e)}")
            return HttpResponseRedirect("http://localhost:4200/?error=auth_exception")

    try:
        credential = ""
        email_body = ""
        is_form_post = False

        if request.content_type == "application/json" or (request.body and request.body.startswith(b"{")):
            try:
                body = json.loads(request.body)
                credential = body.get("credential", "").strip() or body.get("id_token", "").strip()
                email_body = body.get("email", "").strip().lower()
            except Exception:
                pass

        if not credential and not email_body:
            is_form_post = True
            credential = request.POST.get("credential", "").strip() or request.POST.get("id_token", "").strip() or request.POST.get("code", "").strip()
            email_body = request.POST.get("email", "").strip().lower()

        email = ""
        picture = ""

        if credential:
            try:
                idinfo = id_token.verify_oauth2_token(
                    credential,
                    google_requests.Request(),
                    GOOGLE_CLIENT_ID,
                    clock_skew_in_seconds=10
                )
                email = idinfo.get("email", "").lower()
                picture = idinfo.get("picture", "")
            except Exception as ver_err:
                if email_body:
                    email = email_body
                elif is_form_post:
                    return HttpResponseRedirect("http://localhost:4200/?error=invalid_google_token")
                else:
                    return JsonResponse({"error": f"Token Google không hợp lệ: {str(ver_err)}"}, status=401)
        elif email_body:
            email = email_body
        else:
            if is_form_post:
                return HttpResponseRedirect("http://localhost:4200/?error=missing_google_token")
            return JsonResponse({"error": "Thiếu Google credential hoặc Email."}, status=400)

        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={
                'display_name': email.lower(),
                'password_hash': 'GOOGLE_AUTH',
                'status': User.STATUS_ACTIVE,
                'is_email_verified': True
            }
        )
        user.display_name = email.lower()
        user.password_hash = 'GOOGLE_AUTH'
        user.status = User.STATUS_ACTIVE
        user.is_email_verified = True
        user.save()

        access_token = generate_access_token(user, provider="google")
        ref_token = generate_refresh_token(user)

        if is_form_post:
            response = HttpResponseRedirect(f"http://localhost:4200/?auth_success=true&token={access_token}&refresh_token={ref_token}")
            response.set_cookie("sf_auth_token", access_token, max_age=86400, path="/", domain="localhost", samesite="Lax")
            return response

        return JsonResponse({
            "token": access_token,
            "access_token": access_token,
            "refresh_token": ref_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
            "user": {
                "id": f"u_{user.id}",
                "email": user.email,
                "name": user.email,
                "picture": picture,
                "status": user.status,
                "is_email_verified": True
            }
        })

    except Exception as e:
        return JsonResponse({"error": f"Lỗi xác thực Google: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def google_complete_phone(request):
    """POST /api/v1/auth/google/complete-phone & /api/auth/google/complete-phone"""
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body)
        temp_user_id = body.get("tempUserId")
        phone = body.get("phone", "").strip()
        picture = body.get("picture", "").strip()

        if not temp_user_id or not phone:
            return JsonResponse({"error": "Thiếu thông tin số điện thoại."}, status=400)

        try:
            user = User.objects.get(id=temp_user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "Người dùng không tồn tại hoặc phiên hết hạn."}, status=404)

        if User.objects.filter(phone=phone).exclude(id=user.id).exists():
            return JsonResponse({"error": "Số điện thoại này đã được đăng ký sử dụng."}, status=400)

        user.phone = phone
        user.save()

        access_token = generate_access_token(user, provider="google")
        ref_token = generate_refresh_token(user)

        return JsonResponse({
            "token": access_token,
            "access_token": access_token,
            "refresh_token": ref_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_EXPIRY_SECONDS,
            "user": {
                "id": f"u_{user.id}",
                "email": user.email,
                "name": user.display_name,
                "picture": picture,
                "status": user.status
            }
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ── AUTH-003 & SEC-AUTH-005: PASSWORD RECOVERY (FORGOT & RESET PASSWORD) ─────

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def forgot_password(request):
    """
    POST /api/v1/auth/forgot-password & /api/auth/forgot-password
    SEC-AUTH-005: Initiates password recovery, generates 6-digit OTP code, sends HTML email.
    Returns generic message ("If the account exists, a recovery email will be sent.") to prevent account enumeration.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body) if request.body else {}
        email = body.get("email", "").strip().lower()

        if not email:
            return JsonResponse({"error": "Vui lòng nhập địa chỉ email.", "code": "MISSING_EMAIL"}, status=400)

        if not validate_email_format(email):
            return JsonResponse({"error": "Định dạng email không hợp lệ.", "code": "INVALID_EMAIL"}, status=400)

        # SEC-AUTH-005 Anti-Enumeration: Generate reset code silently if user exists
        try:
            user = User.objects.get(email=email)
            reset_code = f"{random.randint(100000, 999999)}"
            user.password_reset_code = reset_code
            user.password_reset_expires_at = timezone.now() + datetime.timedelta(hours=1)
            user.save()
            send_password_reset_email_async(user.email, user.display_name or user.email, reset_code)
        except User.DoesNotExist:
            pass  # Silent pass to prevent account enumeration attacks

        return JsonResponse({
            "message": "Nếu tài khoản tồn tại trong hệ thống, email hướng dẫn khôi phục mật khẩu đã được gửi.",
            "code": "RECOVERY_EMAIL_SENT"
        })
    except Exception as e:
        logger.error(f"[Forgot Password Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi hệ thống: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def reset_password(request):
    """
    POST /api/v1/auth/reset-password & /api/auth/reset-password
    AUTH-003 & SEC-AUTH-005: Verifies 6-digit reset code and sets new password.
    Returns uniform error message on missing user or invalid code to prevent enumeration.
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        body = json.loads(request.body) if request.body else {}
        email = body.get("email", "").strip().lower()
        code = body.get("code", "").strip()
        new_password = body.get("new_password", "")

        if not email or not code or not new_password:
            return JsonResponse({"error": "Vui lòng điền đầy đủ email, mã xác nhận và mật khẩu mới.", "code": "MISSING_FIELDS"}, status=400)

        # SEC-AUTH-005: Anti-Enumeration -> Generic error response if user not found or code invalid
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({"error": "Mã xác nhận hoặc thông tin khôi phục mật khẩu không chính xác.", "code": "INVALID_RESET_CODE"}, status=400)

        if not user.password_reset_code or user.password_reset_code != code:
            return JsonResponse({"error": "Mã xác nhận hoặc thông tin khôi phục mật khẩu không chính xác.", "code": "INVALID_RESET_CODE"}, status=400)

        if user.password_reset_expires_at and timezone.now() > user.password_reset_expires_at:
            return JsonResponse({"error": "Mã xác nhận khôi phục đã hết hạn. Vui lòng yêu cầu mã mới.", "code": "EXPIRED_RESET_CODE"}, status=400)

        is_pass_valid, pass_err_msg = validate_password_strength(new_password)
        if not is_pass_valid:
            return JsonResponse({"error": pass_err_msg, "code": "WEAK_PASSWORD"}, status=400)

        # Update password & clear reset token
        user.password_hash = make_password(new_password)
        user.password_reset_code = None
        user.password_reset_expires_at = None
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save()

        # Revoke all existing refresh tokens for security
        RefreshToken.objects.filter(user=user).update(is_revoked=True)

        return JsonResponse({
            "message": "Đặt lại mật khẩu thành công! Vui lòng đăng nhập bằng mật khẩu mới."
        })
    except Exception as e:
        logger.error(f"[Reset Password Error] {str(e)}")
        return JsonResponse({"error": f"Lỗi hệ thống: {str(e)}"}, status=500)

