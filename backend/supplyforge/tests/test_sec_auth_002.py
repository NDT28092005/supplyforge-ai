"""
Unit tests for SEC-AUTH-002: Email Verification Enforcement
============================================================
Verifies:
1. Registration creates user with status = 'PENDING_VERIFICATION' and is_email_verified = False.
2. Unverified accounts cannot log in or access protected functionality (HTTP 403 Forbidden).
3. Email verification API validates PIN/token and transitions status from 'PENDING_VERIFICATION' -> 'ACTIVE'.
4. Verified accounts are granted full access to protected functionality.
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models import User
from supplyforge.views.auth import generate_access_token


class EmailVerificationSECAuth002TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_registration_creates_pending_verification_account(self):
        """SEC-AUTH-002: Registration creates account with status = PENDING_VERIFICATION."""
        payload = {
            "shopName": "Shop Unverified",
            "email": "unverified_shop@example.com",
            "password": "Password123"
        }
        res = self.client.post('/api/v1/auth/register', payload, format='json')
        self.assertEqual(res.status_code, 201)

        user = User.objects.get(email="unverified_shop@example.com")
        self.assertEqual(user.status, "PENDING_VERIFICATION")
        self.assertFalse(user.is_email_verified)
        self.assertIsNotNone(user.email_verification_code)

    def test_unverified_account_login_denied(self):
        """SEC-AUTH-002: Unverified user cannot log in (HTTP 403)."""
        user = User.objects.create(
            email="pending_login@example.com",
            password_hash="pbkdf2_sha256$...", # dummy hash
            status=User.STATUS_PENDING,
            is_email_verified=False
        )

        res = self.client.post('/api/v1/auth/login', {
            "email": "pending_login@example.com",
            "password": "Password123"
        }, format='json')

        self.assertEqual(res.status_code, 403)
        data = res.json()
        self.assertIn("EMAIL_NOT_VERIFIED", data.get("code", ""))

    def test_unverified_account_protected_functionality_denied(self):
        """SEC-AUTH-002: System shall not grant protected functionality to unverified accounts (HTTP 403)."""
        unverified_user = User.objects.create(
            email="unverified_api_access@example.com",
            status=User.STATUS_PENDING,
            is_email_verified=False
        )
        token = generate_access_token(unverified_user)

        # Attempt to access protected APIs using unverified user token
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}

        res_notifications = self.client.get('/api/v1/notifications/', **headers)
        self.assertEqual(res_notifications.status_code, 403)
        self.assertEqual(res_notifications.json()["code"], "EMAIL_VERIFICATION_REQUIRED")

        res_decisions = self.client.get('/api/v1/decisions/', **headers)
        self.assertEqual(res_decisions.status_code, 403)

        res_export = self.client.get('/api/v1/export/risk/', **headers)
        self.assertEqual(res_export.status_code, 403)

    def test_email_verification_flow_transitions_to_active_and_grants_access(self):
        """
        SEC-AUTH-002 Full Workflow:
        1. Register -> status = PENDING_VERIFICATION
        2. Verify Email Token -> status = ACTIVE & is_email_verified = True
        3. Protected functionality granted!
        """
        # 1. Register
        reg_res = self.client.post('/api/v1/auth/register', {
            "shopName": "Workflow Shop",
            "email": "workflow_user@example.com",
            "password": "Password123"
        }, format='json')
        self.assertEqual(reg_res.status_code, 201)

        user = User.objects.get(email="workflow_user@example.com")
        self.assertEqual(user.status, User.STATUS_PENDING)
        self.assertFalse(user.is_email_verified)
        code = user.email_verification_code

        # 2. Verify email token
        ver_res = self.client.post('/api/v1/auth/verify-email', {
            "email": "workflow_user@example.com",
            "code": code
        }, format='json')
        self.assertEqual(ver_res.status_code, 200)

        user.refresh_from_db()
        self.assertEqual(user.status, User.STATUS_ACTIVE)
        self.assertTrue(user.is_email_verified)

        # 3. Access protected functionality with verified account token
        token = ver_res.json()["access_token"]
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'}

        res = self.client.get('/api/v1/notifications/', **headers)
        self.assertEqual(res.status_code, 200)
