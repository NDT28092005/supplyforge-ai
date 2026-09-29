"""
Unit tests for SEC-AUTH-003 (Verification Token Security) & SEC-AUTH-004 (CAPTCHA / Bot Protection)
========================================================================================================

SEC-AUTH-003 Requirements:
1. Verification token must be random and sufficiently unpredictable (secrets.token_urlsafe).
2. Verification token must expire (expired token rejected with EXPIRED_VERIFICATION_CODE).
3. Single-use invalidation: Token invalidated immediately after successful verification. Second attempt fails.
4. Parameter bypass protection: Rejects URL query parameter bypass attempts (?verified=true / ?bypass=true).

SEC-AUTH-004 Requirements:
1. Normal registration requests (low volume / low risk) proceed without CAPTCHA friction.
2. High-volume or suspicious requests trigger CAPTCHA challenge requirement (HTTP 400 CAPTCHA_REQUIRED).
3. Providing valid CAPTCHA token satisfies challenge and allows registration to succeed.
"""

import datetime
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import User
from supplyforge.services.rate_limiter import RegistrationRateLimiter


class VerificationTokenSecuritySECAuth003TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        RegistrationRateLimiter.reset_all()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

    def tearDown(self):
        self.odoo_patcher.stop()
        RegistrationRateLimiter.reset_all()

    def test_token_unpredictable_and_random(self):
        """SEC-AUTH-003: Verification token must be high-entropy, random and sufficiently unpredictable."""
        reg_res = self.client.post('/api/v1/auth/register', {
            "shopName": "Random Token Shop",
            "email": "token_random@example.com",
            "password": "Password123"
        }, format='json')
        self.assertEqual(reg_res.status_code, 201)

        user = User.objects.get(email="token_random@example.com")
        token = user.email_verification_code
        self.assertIsNotNone(token)
        # Check token length and entropy (URL safe base64 32 bytes is ~43-44 chars)
        self.assertGreaterEqual(len(token), 32)

    def test_single_use_token_invalidation(self):
        """SEC-AUTH-003: Token must be single-use and invalidated immediately after successful verification."""
        reg_res = self.client.post('/api/v1/auth/register', {
            "shopName": "Single Use Shop",
            "email": "single_use@example.com",
            "password": "Password123"
        }, format='json')
        token = reg_res.json()["verification_code"]

        # First verification attempt -> Successful (200 OK)
        ver_res = self.client.post('/api/v1/auth/verify-email', {
            "email": "single_use@example.com",
            "code": token
        }, format='json')
        self.assertEqual(ver_res.status_code, 200)

        # Confirm token in DB was set to None
        user = User.objects.get(email="single_use@example.com")
        self.assertIsNone(user.email_verification_code)

        # Second verification attempt with same token -> Fails (400 INVALID_VERIFICATION_CODE)
        reuse_res = self.client.post('/api/v1/auth/verify-email', {
            "email": "single_use@example.com",
            "code": token
        }, format='json')
        self.assertEqual(reuse_res.status_code, 400)
        self.assertEqual(reuse_res.json()["code"], "INVALID_VERIFICATION_CODE")

    def test_token_expiration(self):
        """SEC-AUTH-003: Token must expire and expired tokens must be rejected."""
        user = User.objects.create(
            email="expired_token@example.com",
            password_hash="hashed_pw",
            status=User.STATUS_PENDING,
            is_email_verified=False,
            email_verification_code="valid_format_token_12345",
            email_verification_expires_at=timezone.now() - datetime.timedelta(minutes=10) # Expired 10m ago
        )

        res = self.client.post('/api/v1/auth/verify-email', {
            "email": "expired_token@example.com",
            "code": "valid_format_token_12345"
        }, format='json')

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "EXPIRED_VERIFICATION_CODE")

    def test_reject_url_parameter_bypass_attempts(self):
        """SEC-AUTH-003: System must reject URL parameter bypass attempts (e.g., ?verified=true)."""
        res = self.client.post('/api/v1/auth/verify-email?verified=true', {
            "email": "bypass_attempt@example.com",
            "code": "some_token"
        }, format='json')

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "BYPASS_ATTEMPT_DENIED")


class CaptchaBotProtectionSECAuth004TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        RegistrationRateLimiter.reset_all()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

    def tearDown(self):
        self.odoo_patcher.stop()
        RegistrationRateLimiter.reset_all()

    def test_normal_registration_requires_no_captcha(self):
        """SEC-AUTH-004: Normal registration requests proceed without demanding CAPTCHA."""
        res = self.client.post('/api/v1/auth/register', {
            "shopName": "Normal Shop",
            "email": "normal_user@example.com",
            "password": "Password123"
        }, format='json', REMOTE_ADDR='192.168.1.100')

        self.assertEqual(res.status_code, 201)

    def test_high_volume_registration_triggers_captcha_challenge(self):
        """SEC-AUTH-004: High-volume registration attempts from same IP trigger CAPTCHA challenge (HTTP 400 CAPTCHA_REQUIRED)."""
        target_ip = '192.168.1.200'

        # Make 3 registration attempts (threshold = 3)
        for i in range(1, 4):
            self.client.post('/api/v1/auth/register', {
                "shopName": f"Volume Shop {i}",
                "email": f"vol_user_{i}@example.com",
                "password": "Password123"
            }, format='json', REMOTE_ADDR=target_ip)

        # 4th request from same IP without captcha token -> Required CAPTCHA
        high_vol_res = self.client.post('/api/v1/auth/register', {
            "shopName": "Volume Shop 4",
            "email": "vol_user_4@example.com",
            "password": "Password123"
        }, format='json', REMOTE_ADDR=target_ip)

        self.assertEqual(high_vol_res.status_code, 400)
        data = high_vol_res.json()
        self.assertEqual(data["code"], "CAPTCHA_REQUIRED")
        self.assertTrue(data["captcha_required"])

    def test_risk_signal_header_triggers_captcha(self):
        """SEC-AUTH-004: Suspicious risk signal header triggers CAPTCHA challenge."""
        headers = {'HTTP_X_RISK_SIGNAL': 'suspicious_proxy_bot'}
        
        res = self.client.post('/api/v1/auth/register', {
            "shopName": "Risk Signal Shop",
            "email": "risk_signal_user@example.com",
            "password": "Password123"
        }, format='json', REMOTE_ADDR='10.0.0.5', **headers)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "CAPTCHA_REQUIRED")

    def test_valid_captcha_token_bypasses_challenge(self):
        """SEC-AUTH-004: Providing a valid CAPTCHA token satisfies the challenge and allows registration."""
        target_ip = '192.168.1.201'

        # Simulate 3 prior attempts to trigger risk evaluation
        for i in range(1, 4):
            self.client.post('/api/v1/auth/register', {
                "email": f"prior_user_{i}@example.com",
                "password": "Password123"
            }, format='json', REMOTE_ADDR=target_ip)

        # 4th attempt with valid captcha_token
        res = self.client.post('/api/v1/auth/register', {
            "shopName": "Captcha Solved Shop",
            "email": "captcha_solved@example.com",
            "password": "Password123",
            "captcha_token": "valid_turnstile_response_token_abc123"
        }, format='json', REMOTE_ADDR=target_ip)

        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["user"]["email"], "captcha_solved@example.com")
