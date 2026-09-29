"""
Unit tests for SEC-AUTHZ-002 (Self-Service Profile Update) & SEC-AUTHZ-003 (Object Ownership & Tenant Isolation)
====================================================================================================================

SEC-AUTHZ-002 Requirement:
"Endpoints like PUT /me/profile MUST bind target user strictly to authenticated identity (request.user).
Does NOT read or trust request.body.user_id to identify target account."

SEC-AUTHZ-003 Requirement:
"Merchant resources (Dataset, SKU, Import, Risk Result, Decision, Action Plan) MUST verify object ownership chain:
request.user -> tenant -> resource.tenant
User A (Tenant A) MUST NOT access Dataset B / Action Plan B belonging to Tenant B simply by knowing dataset_id."
"""

from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient

from supplyforge.models import User, Workspace, WorkspaceMember, ActionPlanRecord
from supplyforge.views.auth import (
    generate_access_token,
    check_object_ownership,
    get_or_create_user_tenant
)


class SelfServiceProfileUpdateSECAuthz002TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

        # Create User A
        self.user_a = User.objects.create(
            email="user_a_self@supplyforge.ai",
            display_name="User A Original",
            role=User.ROLE_OPERATOR,
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        self.token_a = generate_access_token(self.user_a)

        # Create User B
        self.user_b = User.objects.create(
            email="user_b_target@supplyforge.ai",
            display_name="User B Original",
            role=User.ROLE_OPERATOR,
            status=User.STATUS_ACTIVE,
            is_email_verified=True
        )
        self.token_b = generate_access_token(self.user_b)

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_update_me_profile_binds_strictly_to_authenticated_identity(self):
        """SEC-AUTHZ-002: /me/profile endpoint updates authenticated identity's profile."""
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        res = self.client.put('/api/v1/auth/me/profile', {
            "display_name": "User A Self Updated",
            "phone": "0988112233"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 200)

        # User A's profile updated in DB
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.display_name, "User A Self Updated")
        self.assertEqual(self.user_a.phone, "0988112233")

    def test_update_me_profile_blocks_tampering_with_body_user_id(self):
        """
        SEC-AUTHZ-002: Passing user_id of another account in request body to /me/profile
        is rejected (HTTP 400 SELF_SERVICE_TAMPERING_DENIED) and does NOT affect User B.
        """
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        # Attempt to pass User B's ID in body to /me/profile
        res = self.client.put('/api/v1/auth/me/profile', {
            "user_id": self.user_b.id,
            "display_name": "HACKED BY USER A"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "SELF_SERVICE_TAMPERING_DENIED")

        # Verify User B's profile was unchanged
        self.user_b.refresh_from_db()
        self.assertEqual(self.user_b.display_name, "User B Original")

    def test_update_me_profile_prevents_role_elevation(self):
        """SEC-AUTHZ-002: Self-service profile update prevents users from elevating their own role."""
        headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token_a}'}

        res = self.client.put('/api/v1/auth/me/profile', {
            "role": "ADMIN",
            "display_name": "User A Wants Admin"
        }, format='json', **headers)

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "PRIVILEGE_ESCALATION_DENIED")

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.role, User.ROLE_OPERATOR)


class ObjectOwnershipTenantIsolationSECAuthz003TestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.odoo_patcher = patch('supplyforge.services.odoo.OdooIntegrationService.sync_user_to_odoo', return_value=None)
        self.odoo_patcher.start()

        # Tenant A & User A
        self.user_a = User.objects.create(
            email="merchant_a@tenant.com",
            display_name="Merchant A",
            role=User.ROLE_OWNER,
            status=User.STATUS_ACTIVE
        )
        self.tenant_a = get_or_create_user_tenant(self.user_a)

        # Tenant B & User B
        self.user_b = User.objects.create(
            email="merchant_b@tenant.com",
            display_name="Merchant B",
            role=User.ROLE_OWNER,
            status=User.STATUS_ACTIVE
        )
        self.tenant_b = get_or_create_user_tenant(self.user_b)

        # Resource belonging to Tenant B
        self.resource_b = ActionPlanRecord.objects.create(
            plan_id="plan_tenant_b_100",
            campaign_name="Tenant B Clearance",
            sku="SKU-TENANT-B",
            strategy="20% Discount",
            owner="Merchant B",
            start_date="2026-09-28",
            status="DRAFT"
        )
        # Bind resource_b to tenant_b
        setattr(self.resource_b, 'workspace', self.tenant_b)

    def tearDown(self):
        self.odoo_patcher.stop()

    def test_check_object_ownership_same_tenant_allowed(self):
        """SEC-AUTHZ-003: User A accessing Tenant A resource passes object ownership check."""
        resource_a = ActionPlanRecord.objects.create(
            plan_id="plan_tenant_a_100",
            campaign_name="Tenant A Clearance",
            sku="SKU-TENANT-A",
            start_date="2026-09-28"
        )
        setattr(resource_a, 'workspace', self.tenant_a)

        is_allowed, err_msg = check_object_ownership(self.user_a, resource_a)
        self.assertTrue(is_allowed)
        self.assertEqual(err_msg, "")

    def test_check_object_ownership_different_tenant_denied(self):
        """
        SEC-AUTHZ-003: User A (Tenant A) attempting to access Resource B (Tenant B)
        is rejected with tenant isolation error.
        """
        is_allowed, err_msg = check_object_ownership(self.user_a, self.resource_b)

        self.assertFalse(is_allowed)
        self.assertIn("Tài nguyên không thuộc về Workspace", err_msg)
