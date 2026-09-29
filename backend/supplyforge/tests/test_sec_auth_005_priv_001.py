"""
Unit tests for SEC-AUTH-005 (Anti-Account Enumeration) & SEC-PRIV-001 (API Data Minimization)
==================================================================================================

SEC-AUTH-005 Requirements:
1. Forgot password endpoint returns generic response whether email exists or not (preventing email enumeration).
2. Resend verification endpoint returns generic response whether email exists or not.
3. Reset password returns identical 400 INVALID_RESET_CODE for invalid email or invalid code.

SEC-PRIV-001 Requirements:
1. API responses return only minimal necessary fields.
2. Sensitive fields (password_hash, verification codes, reset codes, failed attempts) are NEVER exposed in JSON responses.
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient

from supplyforge.models import User
from supplyforge.views.auth import serialize_user_minimal, serialize_user_profile


class AntiAccountEnumerationSECAuth005TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

        self.existing_email = "existing_user@supplyforge.ai"
        self.user = User.objects.create(
            email=self.existing_email,
            display_name="Existing User",
            status=User.STATUS_PENDING,
            is_email_verified=False
        )

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_forgot_password_generic_response_existing_and_non_existing_email(self):
        """SEC-AUTH-005: forgot-password returns identical HTTP 200 generic message for existing & non-existing emails."""
        non_existing_email = "non_existent_987654@supplyforge.ai"

        # Request 1: Non-existent email
        res1 = self.client.post('/api/v1/auth/forgot-password', {
            "email": non_existing_email
        }, format='json')

        # Request 2: Existing email
        res2 = self.client.post('/api/v1/auth/forgot-password', {
            "email": self.existing_email
        }, format='json')

        # Both must return HTTP 200 OK
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)

        data1 = res1.json()
        data2 = res2.json()

        # Both responses must be identical to prevent enumeration
        self.assertEqual(data1["code"], "RECOVERY_EMAIL_SENT")
        self.assertEqual(data2["code"], "RECOVERY_EMAIL_SENT")
        self.assertEqual(data1["message"], data2["message"])

        # Neither response should leak sensitive dev_reset_code or user existence indicators
        self.assertNotIn("dev_reset_code", data1)
        self.assertNotIn("dev_reset_code", data2)

        # Existing user should have password_reset_code created in DB secretly
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.password_reset_code)
        self.assertEqual(len(self.user.password_reset_code), 6)

    def test_resend_verification_generic_response(self):
        """SEC-AUTH-005: resend-verification returns generic HTTP 200 response to prevent email enumeration."""
        non_existing_email = "non_existent_123456@supplyforge.ai"

        # Request 1: Non-existent email
        res1 = self.client.post('/api/v1/auth/resend-verification', {
            "email": non_existing_email
        }, format='json')

        # Request 2: Existing email
        res2 = self.client.post('/api/v1/auth/resend-verification', {
            "email": self.existing_email
        }, format='json')

        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)

        data1 = res1.json()
        data2 = res2.json()

        self.assertEqual(data1["code"], "VERIFICATION_EMAIL_SENT")
        self.assertEqual(data2["code"], "VERIFICATION_EMAIL_SENT")
        self.assertEqual(data1["message"], data2["message"])
        self.assertNotIn("verification_code", data1)
        self.assertNotIn("verification_code", data2)

    def test_reset_password_anti_enumeration(self):
        """SEC-AUTH-005: reset-password returns generic 400 for non-existent user or invalid code."""
        # Non-existent email
        res1 = self.client.post('/api/v1/auth/reset-password', {
            "email": "ghost_user@supplyforge.ai",
            "code": "123456",
            "new_password": "NewPassword123"
        }, format='json')

        # Existing email with invalid code
        res2 = self.client.post('/api/v1/auth/reset-password', {
            "email": self.existing_email,
            "code": "000000",
            "new_password": "NewPassword123"
        }, format='json')

        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res1.json()["code"], "INVALID_RESET_CODE")
        self.assertEqual(res2.json()["code"], "INVALID_RESET_CODE")
        self.assertEqual(res1.json()["error"], res2.json()["error"])


class DataMinimizationSECPriv001TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

        self.user = User.objects.create(
            email="data_minimization@supplyforge.ai",
            display_name="Minimization Test User",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            email_verification_code="secret_verif_token_xyz",
            password_reset_code="654321",
            failed_login_attempts=2
        )

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_serialize_user_minimal_excludes_pii(self):
        """SEC-PRIV-001: Minimal user serializer includes only id, display_name, role."""
        data = serialize_user_minimal(self.user)

        self.assertEqual(data["id"], f"u_{self.user.id}")
        self.assertEqual(data["display_name"], "Minimization Test User")
        self.assertIn("role", data)

        # Confirm absolute exclusion of PII and private attributes
        self.assertNotIn("email", data)
        self.assertNotIn("phone", data)
        self.assertNotIn("password_hash", data)
        self.assertNotIn("email_verification_code", data)
        self.assertNotIn("password_reset_code", data)

    def test_serialize_user_profile_excludes_sensitive_tokens(self):
        """SEC-PRIV-001: Self-user profile serializer excludes hashes and security tokens."""
        data = serialize_user_profile(self.user)

        self.assertEqual(data["email"], "data_minimization@supplyforge.ai")
        self.assertEqual(data["display_name"], "Minimization Test User")

        # Confirm exclusion of hashes, codes, failed login attempt counters
        self.assertNotIn("password_hash", data)
        self.assertNotIn("email_verification_code", data)
        self.assertNotIn("password_reset_code", data)
        self.assertNotIn("failed_login_attempts", data)
        self.assertNotIn("locked_until", data)

    def test_login_api_response_data_minimization(self):
        """SEC-PRIV-001: Login response user object contains zero sensitive token leaks."""
        self.user.password_hash = "pbkdf2_sha256$..." # set password
        self.user.save()

        with patch('supplyforge.views.auth.check_password', return_value=True):
            res = self.client.post('/api/v1/auth/login', {
                "email": "data_minimization@supplyforge.ai",
                "password": "Password123"
            }, format='json')

            self.assertEqual(res.status_code, 200)
            user_data = res.json()["user"]

            self.assertNotIn("password_hash", user_data)
            self.assertNotIn("email_verification_code", user_data)
            self.assertNotIn("password_reset_code", user_data)
            self.assertNotIn("failed_login_attempts", user_data)
