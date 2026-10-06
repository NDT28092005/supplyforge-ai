import json
import datetime
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from supplyforge.models import User, RefreshToken
from supplyforge.views.auth import (
    validate_email_format, validate_password_strength,
    generate_access_token, generate_refresh_token, verify_jwt
)


class AuthModuleTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.valid_email = "test.user@supplyforge.ai"
        self.valid_password = "SecurePassword123"
        from supplyforge.services.rate_limiter import RegistrationRateLimiter
        RegistrationRateLimiter.reset_all()

    # ── AUTH-001: REGISTRATION & VALIDATION TESTS ──────────────────────

    def test_email_format_validation(self):
        self.assertTrue(validate_email_format("valid.user@example.com"))
        self.assertTrue(validate_email_format("user+tag@domain.co.vn"))
        self.assertFalse(validate_email_format("invalid_email"))
        self.assertFalse(validate_email_format("@domain.com"))
        self.assertFalse(validate_email_format("user@"))

    def test_password_strength_validation(self):
        valid, msg = validate_password_strength("Pass1234")
        self.assertTrue(valid)

        valid, msg = validate_password_strength("short1")
        self.assertFalse(valid)
        self.assertIn("8 ký tự", msg)

        valid, msg = validate_password_strength("12345678")
        self.assertFalse(valid)
        self.assertIn("chữ cái", msg)

        valid, msg = validate_password_strength("abcdefgh")
        self.assertFalse(valid)
        self.assertIn("chữ số", msg)

    def test_registration_success(self):
        response = self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({
                "email": self.valid_email,
                "password": self.valid_password,
                "shopName": "Test Shop"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("verification_code", data)
        self.assertEqual(data["user"]["email"], self.valid_email)

        # Check DB
        user = User.objects.get(email=self.valid_email)
        self.assertEqual(user.status, User.STATUS_PENDING)
        self.assertFalse(user.is_email_verified)
        self.assertIsNotNone(user.email_verification_code)

    def test_registration_duplicate_email(self):
        User.objects.create(email=self.valid_email, password_hash=make_password(self.valid_password))
        response = self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({
                "email": self.valid_email.upper(),  # Case-insensitive duplicate
                "password": self.valid_password,
                "shopName": "Another Shop"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["code"], "DUPLICATE_EMAIL")

    def test_registration_duplicate_phone(self):
        User.objects.create(email="other@domain.com", phone="0912345678")
        response = self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({
                "email": "new.user@domain.com",
                "password": self.valid_password,
                "phone": "0912345678"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["code"], "DUPLICATE_PHONE")

    def test_email_verification_success(self):
        # Register user first
        reg_resp = self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({
                "email": self.valid_email,
                "password": self.valid_password
            }),
            content_type='application/json'
        )
        code = reg_resp.json()["verification_code"]

        # Verify email
        ver_resp = self.client.post(
            '/api/v1/auth/verify-email',
            data=json.dumps({
                "email": self.valid_email,
                "code": code
            }),
            content_type='application/json'
        )
        self.assertEqual(ver_resp.status_code, 200)
        data = ver_resp.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

        # Check DB updated
        user = User.objects.get(email=self.valid_email)
        self.assertTrue(user.is_email_verified)
        self.assertEqual(user.status, User.STATUS_ACTIVE)

    def test_email_verification_invalid_code(self):
        self.client.post(
            '/api/v1/auth/register',
            data=json.dumps({"email": self.valid_email, "password": self.valid_password}),
            content_type='application/json'
        )
        ver_resp = self.client.post(
            '/api/v1/auth/verify-email',
            data=json.dumps({"email": self.valid_email, "code": "000000"}),
            content_type='application/json'
        )
        self.assertEqual(ver_resp.status_code, 400)
        self.assertEqual(ver_resp.json()["code"], "INVALID_VERIFICATION_CODE")

    # ── AUTH-002: AUTHENTICATION, LOGIN, REFRESH & LOCKOUT TESTS ─────────

    def test_login_success(self):
        user = User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": self.valid_email, "password": self.valid_password}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        self.assertEqual(data["user"]["email"], self.valid_email)

        # Verify DB last_login_at updated
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login_at)
        self.assertEqual(user.failed_login_attempts, 0)

    def test_login_invalid_credentials(self):
        User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": self.valid_email, "password": "WrongPassword123"}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["code"], "INVALID_CREDENTIALS")
        self.assertEqual(data["attempts_left"], 4)

    def test_account_lockout_after_5_failed_attempts(self):
        user = User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        # Attempt 5 wrong logins
        for i in range(5):
            response = self.client.post(
                '/api/v1/auth/login',
                data=json.dumps({"email": self.valid_email, "password": "WrongPassword"}),
                content_type='application/json'
            )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["code"], "ACCOUNT_LOCKED")

        # Check DB status
        user.refresh_from_db()
        self.assertEqual(user.status, User.STATUS_LOCKED)
        self.assertIsNotNone(user.locked_until)

    def test_account_auto_unlock_after_duration(self):
        # Create locked user with locked_until in the past
        past_time = timezone.now() - datetime.timedelta(minutes=20)
        user = User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_LOCKED,
            failed_login_attempts=5,
            locked_until=past_time,
            is_email_verified=True
        )
        # Next login with correct password should unlock automatically
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": self.valid_email, "password": self.valid_password}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.status, User.STATUS_ACTIVE)
        self.assertEqual(user.failed_login_attempts, 0)

    def test_login_disabled_account(self):
        User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_DISABLED,
            is_email_verified=True
        )
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": self.valid_email, "password": self.valid_password}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "ACCOUNT_DISABLED")

    def test_login_pending_verification_account(self):
        User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_PENDING,
            is_email_verified=False
        )
        response = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({"email": self.valid_email, "password": self.valid_password}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "EMAIL_NOT_VERIFIED")

    def test_refresh_token_flow(self):
        import hashlib
        user = User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        refresh_token = generate_refresh_token(user)

        response = self.client.post(
            '/api/v1/auth/refresh',
            data=json.dumps({"refresh_token": refresh_token}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

        # Old refresh token should now be revoked in DB
        old_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
        old_db_token = RefreshToken.objects.get(token=old_hash)
        self.assertTrue(old_db_token.is_revoked)

    def test_logout_flow(self):
        import hashlib
        user = User.objects.create(
            email=self.valid_email,
            password_hash=make_password(self.valid_password),
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        refresh_token = generate_refresh_token(user)

        response = self.client.post(
            '/api/v1/auth/logout',
            data=json.dumps({"refresh_token": refresh_token}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        # Verify refresh token is revoked
        token_hash = hashlib.sha256(refresh_token.encode('utf-8')).hexdigest()
        db_token = RefreshToken.objects.get(token=token_hash)
        self.assertTrue(db_token.is_revoked)

        # Submitting revoked refresh token should fail
        ref_resp = self.client.post(
            '/api/v1/auth/refresh',
            data=json.dumps({"refresh_token": refresh_token}),
            content_type='application/json'
        )
        self.assertEqual(ref_resp.status_code, 401)
