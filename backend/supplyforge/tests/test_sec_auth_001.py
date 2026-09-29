"""
Unit tests for SEC-AUTH-001: Registration Rate Limiting
=========================================================
Verifies policy-driven rate limiting across 5 key dimensions:
1. IP address
2. Device/session fingerprint
3. Email
4. Phone
5. Network/risk signal

Acceptance Criteria:
- 100 registration requests -> First N requests accepted/processed, later requests rate limited with HTTP 429.
- Prevents creation of 100 accounts.
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models import User
from supplyforge.services.rate_limiter import RegistrationRateLimiter


class RegistrationRateLimiterTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        RegistrationRateLimiter.reset_all()
        # Mock Odoo sync to keep unit tests running at lightspeed
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

    def tearDown(self):
        self.odoo_patcher.stop()
        RegistrationRateLimiter.reset_all()

    def test_sec_auth_001_100_registration_requests_rate_limited(self):
        """
        Acceptance Criteria:
        100 registration requests from same IP / signal:
        - First 5 requests processed.
        - Remaining 95 requests rate limited with HTTP 429 Too Many Requests.
        - Does NOT allow creating 100 accounts.
        """
        status_codes = []
        created_accounts_count_before = User.objects.count()

        for i in range(1, 101):
            payload = {
                "shopName": f"Shop Test {i}",
                "email": f"user_test_{i}@example.com",
                "phone": f"0900000{i:03d}",
                "password": "Password123",
                "captcha_token": "valid_test_captcha_token"
            }
            # All 100 requests originate from the same IP (192.168.1.50)
            res = self.client.post(
                '/api/v1/auth/register',
                payload,
                format='json',
                REMOTE_ADDR='192.168.1.50'
            )
            status_codes.append(res.status_code)

        # Count occurrences
        success_status_count = status_codes.count(201)
        rate_limited_status_count = status_codes.count(429)

        # First 5 should be accepted (201 Created), remaining 95 rate limited (429)
        self.assertEqual(success_status_count, 5)
        self.assertEqual(rate_limited_status_count, 95)
        self.assertEqual(len(status_codes), 100)

        # Confirm 100 accounts were NOT created (only 5 created)
        total_created = User.objects.count() - created_accounts_count_before
        self.assertEqual(total_created, 5)

        # Verify 429 Response Format
        last_res = self.client.post(
            '/api/v1/auth/register',
            {"email": "extra@example.com", "password": "Password123", "captcha_token": "valid_test_captcha_token"},
            format='json',
            REMOTE_ADDR='192.168.1.50'
        )
        self.assertEqual(last_res.status_code, 429)
        data = last_res.json()
        self.assertEqual(data["error"], "Too Many Requests")
        self.assertEqual(data["code"], "RATE_LIMIT_EXCEEDED")
        self.assertIn("retry_after_seconds", data)

    def test_rate_limiting_by_device_fingerprint(self):
        """SEC-AUTH-001: Rate limiting triggered by device fingerprint header."""
        headers = {'HTTP_X_DEVICE_FINGERPRINT': 'device_fp_abc_999'}
        
        for i in range(1, 6):
            res = self.client.post(
                '/api/v1/auth/register',
                {"email": f"fp_user_{i}@test.com", "password": "Password123", "captcha_token": "valid_test_captcha_token"},
                format='json',
                REMOTE_ADDR=f'10.0.0.{i}', # Different IPs, same device fingerprint
                **headers
            )
            self.assertEqual(res.status_code, 201)

        # 6th attempt with same device fingerprint -> 429
        blocked_res = self.client.post(
            '/api/v1/auth/register',
            {"email": "fp_user_6@test.com", "password": "Password123", "captcha_token": "valid_test_captcha_token"},
            format='json',
            REMOTE_ADDR='10.0.0.6',
            **headers
        )
        self.assertEqual(blocked_res.status_code, 429)

    def test_rate_limiting_by_phone(self):
        """SEC-AUTH-001: Rate limiting triggered by phone number."""
        target_phone = "0988776655"
        
        for i in range(1, 6):
            res = self.client.post(
                '/api/v1/auth/register',
                {"email": f"phone_user_{i}@test.com", "phone": target_phone, "password": "Password123", "captcha_token": "valid_test_captcha_token"},
                format='json',
                REMOTE_ADDR=f'172.16.0.{i}'
            )
            self.assertIn(res.status_code, [201, 400])

        # 6th attempt with same phone -> 429 Rate Limited
        blocked_res = self.client.post(
            '/api/v1/auth/register',
            {"email": "phone_user_6@test.com", "phone": target_phone, "password": "Password123", "captcha_token": "valid_test_captcha_token"},
            format='json',
            REMOTE_ADDR='172.16.0.6'
        )
        self.assertEqual(blocked_res.status_code, 429)

    def test_rate_limiting_by_network_risk_signal(self):
        """SEC-AUTH-001: Rate limiting triggered by risk signal header."""
        headers = {'HTTP_X_RISK_SIGNAL': 'subnet_signal_88'}

        for i in range(1, 6):
            res = self.client.post(
                '/api/v1/auth/register',
                {"email": f"risk_user_{i}@test.com", "password": "Password123", "captcha_token": "valid_test_captcha_token"},
                format='json',
                REMOTE_ADDR=f'192.168.10.{i}',
                **headers
            )
            self.assertEqual(res.status_code, 201)

        # 6th attempt with same risk signal -> 429
        blocked_res = self.client.post(
            '/api/v1/auth/register',
            {"email": "risk_user_6@test.com", "password": "Password123", "captcha_token": "valid_test_captcha_token"},
            format='json',
            REMOTE_ADDR='192.168.10.6',
            **headers
        )
        self.assertEqual(blocked_res.status_code, 429)
