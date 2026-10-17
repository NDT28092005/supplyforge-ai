import json
from django.test import TestCase, Client
from django.core.exceptions import PermissionDenied
from supplyforge.models import User, Workspace, WorkspaceMember, Product, IngestionSession
from supplyforge.services.tenant_isolation import TenantIsolationService
from supplyforge.views.auth import get_or_create_user_tenant


class Ten001And002TestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create User A & Tenant 1
        self.user_a = User.objects.create(
            email="merchant_a@shop.com",
            display_name="Shop A",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant_a = get_or_create_user_tenant(self.user_a)

        # Create User B & Tenant 2
        self.user_b = User.objects.create(
            email="merchant_b@shop.com",
            display_name="Shop B",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant_b = get_or_create_user_tenant(self.user_b)

    def test_ten_001_tenant_creation_hierarchy(self):
        """TEN-001: User -> Tenant -> Workspace Member hierarchy created cleanly."""
        self.assertIsNotNone(self.tenant_a)
        self.assertEqual(self.tenant_a.owner, self.user_a)
        member = WorkspaceMember.objects.filter(workspace=self.tenant_a, user=self.user_a).first()
        self.assertIsNotNone(member)

        # Confirm distinct tenants for Merchant A and Merchant B
        self.assertNotEqual(self.tenant_a.id, self.tenant_b.id)

    def test_ten_002_tenant_isolation_verification(self):
        """TEN-002: User A (T001) cannot access resources of User B (T002)."""
        # Create resource belonging to Tenant B (workspace_id = tenant_b.id)
        session_b = IngestionSession.objects.create(
            workspace=self.tenant_b,
            status='COMPLETED'
        )

        # Verify Tenant A ('T001' or tenant_a.id) access on Tenant B's resource returns False
        tenant_a_id = f"T{self.tenant_a.id:03d}"
        is_allowed = TenantIsolationService.verify_resource_tenant_access(
            session_b,
            tenant_id=tenant_a_id,
            action="read"
        )
        self.assertFalse(is_allowed)

        # Verify Tenant B accessing its own resource returns True
        tenant_b_id = f"T{self.tenant_b.id:03d}"
        is_owner_allowed = TenantIsolationService.verify_resource_tenant_access(
            session_b,
            tenant_id=tenant_b_id,
            action="read"
        )
        self.assertTrue(is_owner_allowed)

    def test_ten_002_enforce_isolation_raises_permission_denied(self):
        """TEN-002: enforce_tenant_isolation raises PermissionDenied on cross-tenant access."""
        session_b = IngestionSession.objects.create(
            workspace=self.tenant_b,
            status='COMPLETED'
        )

        # Tenant context must come from validated middleware state, not a
        # client-controlled tenant header.
        class DummyRequest:
            tenant_context_validated = True
            authenticated_tenant_id = f"T{self.tenant_a.id:03d}"

        req = DummyRequest()
        with self.assertRaises(PermissionDenied):
            TenantIsolationService.enforce_tenant_isolation(session_b, req, action="read")
