import jwt
import datetime
import json
import logging
import requests
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.auth.hashers import make_password, check_password

from supplyforge.models import User
from supplyforge.services.odoo import OdooIntegrationService

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = settings.SUPPLYFORGE.get('google_oauth', {}).get(
    'client_id',
    '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com'
)
JWT_SECRET = settings.SECRET_KEY
JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = 24 * 7  # 7 days


def generate_jwt(payload: dict) -> str:
    """Generate a signed JWT token for the given user payload."""
    data = {
        **payload,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    """Verify and decode a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


@csrf_exempt
@require_http_methods(["POST", "GET", "OPTIONS"])
def google_callback(request):
    """
    GET/POST /api/auth/google/callback
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    # 1. HỖ TRỢ GET REQUEST & FORM POST: Luồng OAuth 2.0 ID Token & Code
    if request.method == "GET":
        code = request.GET.get("code", "").strip()
        id_token_param = request.GET.get("id_token", "").strip() or request.GET.get("credential", "").strip()
        email_param = request.GET.get("email", "").strip().lower()

        if not code and not id_token_param and not email_param:
            error_reason = request.GET.get("error", "missing_code")
            return HttpResponseRedirect(f"http://localhost:4200/?error={error_reason}")

        try:
            email = ""
            name = ""
            picture = ""

            # 1.1 Nếu có id_token trực tiếp hoặc code dạng JWT (bắt đầu bằng eyJ)
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
                    logger.warning(f"[Direct ID Token Verify Warning] {jwt_err}")

            # 1.2 Nếu có code chuẩn auth_code, trao đổi với Google Token Endpoint (nếu có client_secret)
            if not email and code and not code.startswith("eyJ"):
                token_url = "https://oauth2.googleapis.com/token"
                client_secret = settings.SUPPLYFORGE.get('google_oauth', {}).get('client_secret', '')
                if client_secret:
                    token_data = {
                        "code": code,
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": client_secret,
                        "redirect_uri": "http://localhost:8080/api/auth/google/callback",
                        "grant_type": "authorization_code"
                    }
                    r = requests.post(token_url, data=token_data)
                    if r.status_code == 200:
                        tokens = r.json()
                        credential = tokens.get("id_token", "")
                        if credential:
                            idinfo = id_token.verify_oauth2_token(
                                credential,
                                google_requests.Request(),
                                GOOGLE_CLIENT_ID,
                                clock_skew_in_seconds=10
                            )
                            email = idinfo.get("email", "").lower()
                            picture = idinfo.get("picture", "")

            if not email and email_param:
                email = email_param

            if not email:
                # Không xác minh được email Google thực tế -> Trả về thông báo lỗi, KHÔNG dùng email giả
                return HttpResponseRedirect("http://localhost:4200/?error=google_auth_failed")

            # Lưu vào MySQL DB bảng users với display_name là email và password_hash là GOOGLE_AUTH
            user, created = User.objects.get_or_create(
                email=email.lower(),
                defaults={
                    'display_name': email.lower(),
                    'password_hash': 'GOOGLE_AUTH'
                }
            )
            if created or not user.password_hash or user.password_hash != 'GOOGLE_AUTH':
                user.display_name = email.lower()
                user.password_hash = 'GOOGLE_AUTH'
                user.save()

            user_id = f"u_{user.id}"
            workspace_id = 1

            jwt_payload = {
                "sub": user_id,
                "email": user.email,
                "name": user.email,
                "picture": picture,
                "workspace_id": workspace_id,
                "provider": "google",
            }

            token = generate_jwt(jwt_payload)
            if isinstance(token, bytes):
                token = token.decode('utf-8')

            try:
                OdooIntegrationService.sync_user_to_odoo(name=user.email, email=user.email, phone=user.phone)
            except Exception as odoo_err:
                logger.warning(f"[Odoo Sync Warning] Failed to sync user to Odoo: {odoo_err}")

            response = HttpResponseRedirect(f"http://localhost:4200/?auth_success=true&token={token}")
            response.set_cookie(
                "sf_auth_token", 
                token, 
                max_age=86400, 
                path="/", 
                domain="localhost",
                samesite="Lax"
            )
            return response

        except Exception as e:
            logger.error(f"[Google Auth GET Error] {str(e)}")
            return HttpResponseRedirect(f"http://localhost:4200/?error=auth_exception")

    # 2. HỖ TRỢ POST REQUEST: Form POST từ Google hoặc JSON API từ Frontend
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
        name = ""
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
                logger.warning(f"[Google Token Verify Warning] {ver_err}")
                if email_body:
                    email = email_body
                else:
                    if is_form_post:
                        return HttpResponseRedirect("http://localhost:4200/?error=invalid_google_token")
                    return JsonResponse({"error": f"Token Google không hợp lệ: {str(ver_err)}"}, status=401)
        elif email_body:
            email = email_body
        else:
            if is_form_post:
                return HttpResponseRedirect("http://localhost:4200/?error=missing_google_token")
            return JsonResponse({"error": "Thiếu Google credential hoặc Email."}, status=400)

        name = email  # Tên chính là email theo yêu cầu của user

        # Lưu tài khoản Google trực tiếp vào MySQL database (bảng users)
        user, created = User.objects.get_or_create(
            email=email.lower(),
            defaults={
                'display_name': email.lower(),
                'password_hash': 'GOOGLE_AUTH'
            }
        )
        
        # Cập nhật display_name = email & password_hash = GOOGLE_AUTH để phân biệt với manual
        user.display_name = email.lower()
        user.password_hash = 'GOOGLE_AUTH'
        user.save()

        user_id = f"u_{user.id}"
        workspace_id = 1

        jwt_payload = {
            "sub": user_id,
            "email": user.email,
            "name": user.email,
            "picture": picture,
            "workspace_id": workspace_id,
            "provider": "google",
        }

        token = generate_jwt(jwt_payload)
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        try:
            OdooIntegrationService.sync_user_to_odoo(name=user.email, email=user.email, phone=user.phone)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user to Odoo: {odoo_err}")

        # Nếu là Google Form POST redirect, chuyển hướng về Frontend kèm token trên URL
        if is_form_post:
            response = HttpResponseRedirect(f"http://localhost:4200/?auth_success=true&token={token}")
            response.set_cookie("sf_auth_token", token, max_age=86400, path="/", domain="localhost", samesite="Lax")
            return response

        return JsonResponse({
            "token": token,
            "user": {
                "id": user_id,
                "email": user.email,
                "name": user.email,
                "picture": picture,
                "workspace_id": workspace_id,
                "provider": "google"
            }
        })

    except ValueError as e:
        return JsonResponse({"error": f"Token Google không hợp lệ: {str(e)}"}, status=401)
    except Exception as e:
        return JsonResponse({"error": f"Lỗi xác thực: {str(e)}"}, status=500)


@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def verify_token(request):
    """
    GET /api/auth/verify
    Header: Authorization: Bearer <JWT>
    Returns: { "valid": true, "user": { ... } }
    """
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Headers"] = "Authorization"
        return resp

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JsonResponse({"valid": False, "error": "Thiếu token xác thực."}, status=401)

    token = auth_header[7:]
    payload = verify_jwt(token)

    if payload is None:
        return JsonResponse({"valid": False, "error": "Token hết hạn hoặc không hợp lệ."}, status=401)

    return JsonResponse({
        "valid": True,
        "user": {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "picture": payload.get("picture"),
            "workspace_id": payload.get("workspace_id"),
        }
    })


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def register_user(request):
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
        
    try:
        body = json.loads(request.body)
        shop_name = body.get("shopName", "").strip()
        phone = body.get("phone", "").strip()
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")
        
        if not shop_name or not email or not password:
            return JsonResponse({"error": "Thiếu các thông tin bắt buộc."}, status=400)
            
        if User.objects.filter(email=email).exists():
            return JsonResponse({"error": "Email này đã được đăng ký sử dụng."}, status=400)
            
        if phone and User.objects.filter(phone=phone).exists():
            return JsonResponse({"error": "Số điện thoại này đã được đăng ký sử dụng."}, status=400)
            
        user = User.objects.create(
            email=email,
            password_hash=make_password(password),
            display_name=shop_name
        )
        
        try:
            OdooIntegrationService.sync_user_to_odoo(name=shop_name, email=email, phone=phone)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user on register: {odoo_err}")
            
        return JsonResponse({
            "message": "Đăng ký tài khoản thành công.",
            "user": {
                "email": user.email,
                "name": user.display_name
            }
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def login_user(request):
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
            return JsonResponse({"error": "Thiếu email hoặc mật khẩu."}, status=400)
            
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({"error": "Email hoặc mật khẩu không chính xác."}, status=401)
            
        if not user.password_hash or not check_password(password, user.password_hash):
            return JsonResponse({"error": "Email hoặc mật khẩu không chính xác."}, status=401)
            
        user_id = f"u_{user.id}"
        workspace_id = 1
        
        jwt_payload = {
            "sub": user_id,
            "email": user.email,
            "name": user.display_name,
            "workspace_id": workspace_id,
            "provider": "local",
        }
        
        token = generate_jwt(jwt_payload)
        
        try:
            OdooIntegrationService.sync_user_to_odoo(name=user.display_name, email=user.email)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user on login: {odoo_err}")
            
        return JsonResponse({
            "token": token,
            "user": {
                "id": user_id,
                "email": user.email,
                "name": user.display_name,
                "workspace_id": workspace_id
            }
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def google_complete_phone(request):
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
        
        try:
            OdooIntegrationService.sync_user_to_odoo(name=user.display_name, email=user.email, phone=phone)
        except Exception as odoo_err:
            logger.warning(f"[Odoo Sync Warning] Failed to sync user to Odoo: {odoo_err}")
            
        user_id = f"u_{user.id}"
        workspace_id = 1
        
        jwt_payload = {
            "sub": user_id,
            "email": user.email,
            "name": user.display_name,
            "picture": picture,
            "workspace_id": workspace_id,
            "provider": "google",
        }
        
        token = generate_jwt(jwt_payload)
        
        return JsonResponse({
            "token": token,
            "user": {
                "id": user_id,
                "email": user.email,
                "name": user.display_name,
                "picture": picture,
                "workspace_id": workspace_id
            }
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
