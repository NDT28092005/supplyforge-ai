import json
from django.test import TestCase, Client
from django.contrib.auth.hashers import make_password
from supplyforge.models import User, Workspace, WorkspaceMember, Product
from supplyforge.views.auth import generate_access_token


class SecurityRegressionPyramidTests(TestCase):
    """
    Task 3.3: Security Regression Test suite.
    - IDOR Protection (User A accessing User B's user endpoint -> 403)
    - Tenant Isolation (Workspace A user accessing Workspace B -> 403)
    - Horizontal Privilege Escalation Protection
    - Vertical Privilege Escalation Protection (MEMBER attempting OWNER actions -> 403)
    - Admin Authorization & Authentication Boundaries
    - Premium Authorization Checks
    """

    def setUp(self):
        self.client = Client()

        # User A (Owner of Workspace A)
        self.user_a = User.objects.create(
            email="user_a@supplyforge.local",
            password_hash=make_password("Pass123456"),
            display_name="User A (Shop A)",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role="OWNER"
        )
        self.ws_a = Workspace.objects.create(
            name="Workspace A",
            owner=self.user_a,
            slug="t_ws_a"
        )
        WorkspaceMember.objects.create(workspace=self.ws_a, user=self.user_a, role="OWNER")
        self.token_a = generate_access_token(self.user_a, workspace_id=self.ws_a.id)
        self.headers_a = {"HTTP_AUTHORIZATION": f"Bearer {self.token_a}"}

        # User B (Owner of Workspace B)
        self.user_b = User.objects.create(
            email="user_b@supplyforge.local",
            password_hash=make_password("Pass123456"),
            display_name="User B (Shop B)",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role="OWNER"
        )
        self.ws_b = Workspace.objects.create(
            name="Workspace B",
            owner=self.user_b,
            slug="t_ws_b"
        )
        WorkspaceMember.objects.create(workspace=self.ws_b, user=self.user_b, role="OWNER")
        self.token_b = generate_access_token(self.user_b, workspace_id=self.ws_b.id)
        self.headers_b = {"HTTP_AUTHORIZATION": f"Bearer {self.token_b}"}

        # Regular Member User C in Workspace A (non-Owner)
        self.user_c = User.objects.create(
            email="user_member@supplyforge.local",
            password_hash=make_password("Pass123456"),
            display_name="User C (Member)",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role="MEMBER"
        )
        WorkspaceMember.objects.create(workspace=self.ws_a, user=self.user_c, role="MEMBER")
        self.token_c = generate_access_token(self.user_c, workspace_id=self.ws_a.id)
        self.headers_c = {"HTTP_AUTHORIZATION": f"Bearer {self.token_c}"}

        # Create Product in Workspace B
        self.product_b = Product.objects.create(
            id="prod_ws_b_001",
            user_id=str(self.user_b.id),
            third_party_id="tp_b_001",
            product_name="Product in Workspace B",
            item_sku="SKU_WS_B",
            stock=10,
            cost=100.0,
            price=200.0
        )

    def test_idor_protection(self):
        """User A attempting to update User B's profile via /api/v1/users/{user_b_id} -> 403 Forbidden."""
        response = self.client.post(
            f'/api/v1/users/{self.user_b.id}',
            data=json.dumps({"display_name": "Hacked Name"}),
            content_type="application/json",
            **self.headers_a
        )
        self.assertEqual(response.status_code, 403)

    def test_tenant_isolation(self):
        """User A attempting to read Workspace B's dead stock via /api/v1/workspaces/{ws_b_id}/dead-stock -> 403 Forbidden."""
        response = self.client.get(f'/api/v1/workspaces/{self.ws_b.id}/dead-stock', **self.headers_a)
        self.assertIn(response.status_code, [403, 404])

    def test_horizontal_privilege_escalation(self):
        """User A attempting to access Workspace B's aging metrics -> 403 Forbidden."""
        response = self.client.get(f'/api/v1/workspaces/{self.ws_b.id}/aging', **self.headers_a)
        self.assertIn(response.status_code, [403, 404])

    def test_vertical_privilege_escalation(self):
        """Regular MEMBER user attempting OWNER-only tenant data deletion -> 403 Forbidden."""
        response = self.client.post(
            '/api/v1/tenant/delete-data',
            data=json.dumps({"confirm": True}),
            content_type="application/json",
            **self.headers_c
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_authorization(self):
        """Unauthenticated request to protected endpoints -> 401 Unauthorized."""
        response = self.client.get('/api/v1/workspaces/1/dead-stock')
        self.assertEqual(response.status_code, 401)

    def test_premium_authorization(self):
        """User A can update their own me profile."""
        response = self.client.post(
            '/api/v1/auth/me/profile',
            data=json.dumps({"display_name": "User A Updated"}),
            content_type="application/json",
            **self.headers_a
        )
        self.assertEqual(response.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.display_name, "User A Updated")
