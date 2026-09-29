"""
Unit tests for SEC-PRIV-002 (UI Masking Is Not Security) & SEC-AUTHZ-001 (Server-Side Object Authorization)
==============================================================================================================

SEC-PRIV-002 Requirement:
"Sensitive information shall not be considered protected merely because it is hidden or masked in the frontend UI.
If user is not permitted to see email: API must NOT return unmasked email."

SEC-AUTHZ-001 Requirement:
"Server MUST NOT trust user_id/target_id supplied by client to determine object access permissions.
Authenticated User -> Authorization Policy -> Can this user modify target resource? -> YES/NO"
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient

from supplyforge.models import User
from supplyforge.views.auth import (
    generate_access_token,
    mask_email_server_side,
    mask_phone_server_side,
    serialize_user_minimal
)


class ServerSideMaskingSECPriv002TestCase(TestCase):
    def test_mask_email_server_side(self):
        """SEC-PRIV-002: Backend masks PII server-side before sending over HTTP wire."""
        self.assertEqual(mask_email_server_side("john.doe@example.com"), "j******e@example.com")
        self.assertEqual(mask_email_server_side("ab@domain.com"), "a*@domain.com")
        self.assertEqual(mask_email_server_side("a@b.com"), "a*@b.com")

    def test_mask_phone_server_side(self):
        """SEC-PRIV-002: Phone numbers masked on server-side."""
        self.assertEqual(mask_phone_server_side("0901234567"), "090*****67")
        self.assertEqual(mask_phone_server_side("12345"), "***")

    def test_serialize_user_minimal_uses_server_side_masking(self):
        """SEC-PRIV-002: Minimal serializer returns server-masked email string."""
        user = User(id=10, email="merchant_secret@shop.com", display_name="Merchant Secret")
        data = serialize_user_minimal(user, mask_pii=True)

        self.assertNotIn("email", data) # Full unmasked email strictly omitted
        self.assertEqual(data["masked_email"], "m*************t@shop.com")


class ServerSideObjectAuthorizationSECAuthz001TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

        # Create User A (Regular Member)
        self.user_a = User.objects.create(
            email="user_a@supplyforge.ai",
            display_name="User A",
            role=User.ROLE_OPERATOR,
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        self.token_a = generate_access_token(self.user_a)

        # Create User B (Target Regular User)
        self.user_b = User.objects.create(
            email="user_b@supplyforge.ai",
            display_name="User B Original Name",
            role=User.ROLE_OPERATOR,
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        self.token_b = generate_access_token(self.user_b)

        # Create Admin User
        self.admin = User.objects.create(
            email="admin@supplyforge.ai",
            display_name="Admin User",
            role=User.ROLE_ADMIN,
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        self.token_admin = generate_access_token(self.admin)

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_idor_blocked_user_a_cannot_modify_user_b_profile(self):
        """
        SEC-AUTHZ-001 IDOR / BOLA Guard:
        User A passes User B's user_id in payload/URL attempting to overwrite User B's profile.
        Server verifies authorization policy and rejects request with HTTP 403 Forbidden.
        """
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        # Attempt IDOR attack: User A sends token A with user_b's ID in body
        res = self.client.put('/api/v1/users/update', {
            "user_id": self.user_b.id,
            "display_name": "HACKED BY USER A"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "FORBIDDEN_OBJECT_ACCESS")

        # Verify User B's display_name in DB was untouched
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_b.display_name, "User B Original Name")

    def test_privilege_escalation_blocked_user_cannot_elevate_own_role(self):
        """
        SEC-AUTHZ-001 Privilege Escalation Guard:
        Regular User A attempts to escalate role to ADMIN via profile update.
        Server rejects request with HTTP 403 Forbidden.
        """
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        res = self.client.put('/api/v1/auth/profile', {
            "role": "ADMIN",
            "display_name": "User A Want Admin"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "PRIVILEGE_ESCALATION_DENIED")

        # Confirm role remains OPERATOR
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.role, User.ROLE_OPERATOR)

    def test_user_can_modify_own_profile(self):
        """SEC-AUTHZ-001: Authenticated user can update their own profile."""
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        res = self.client.put('/api/v1/auth/profile', {
            "display_name": "User A Updated Name",
            "phone": "0911223344"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.display_name, "User A Updated Name")
        self.assertEqual(self.user_a.phone, "0911223344")

    def test_admin_can_modify_other_user_profile(self):
        """SEC-AUTHZ-001: Admin user possesses policy permission to update user profiles."""
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_admin}'}

        res = self.client.put(f'/api/v1/users/{self.user_b.id}', {
            "display_name": "User B Updated By Admin",
            "role": "ANALYST"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 200)
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_b.display_name, "User B Updated By Admin")
        self.assertEqual(self.user_b.role, "ANALYST")
