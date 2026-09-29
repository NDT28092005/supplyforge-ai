import json
from django.test import TestCase, Client
from supplyforge.models import User, RefreshToken
from supplyforge.permissions import (
    has_permission, get_user_permissions,
    ROLE_OWNER, ROLE_ADMIN, ROLE_ANALYST, ROLE_OPERATOR, ROLE_VIEWER,
    PERM_UPLOAD_DATA, PERM_DELETE_DATASET, PERM_RUN_SIMULATION, PERM_EXECUTE_ACTION, PERM_VIEW_FINANCIAL
)


class Auth003And004TestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.test_email = "owner_test@supplyforge.ai"
        self.test_password = "Password123"
        self.user = User.objects.create(
            email=self.test_email,
            display_name="Test Owner",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )

    # ── AUTH-003 Tests ──
    def test_forgot_password_generates_code_and_sends_email(self):
        response = self.client.post(
            '/api/v1/auth/forgot-password',
            data=json.dumps({"email": self.test_email}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("message", data)
        self.assertEqual(data.get("code"), "RECOVERY_EMAIL_SENT")

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.password_reset_code)
        self.assertEqual(len(self.user.password_reset_code), 6)

    def test_reset_password_success(self):
        # Initiate forgot password
        self.client.post(
            '/api/v1/auth/forgot-password',
            data=json.dumps({"email": self.test_email}),
            content_type='application/json'
        )
        self.user.refresh_from_db()
        reset_code = self.user.password_reset_code

        # Perform password reset
        new_password = "NewPassword123"
        reset_resp = self.client.post(
            '/api/v1/auth/reset-password',
            data=json.dumps({
                "email": self.test_email,
                "code": reset_code,
                "new_password": new_password
            }),
            content_type='application/json'
        )
        self.assertEqual(reset_resp.status_code, 200)

        # Login with new password
        login_resp = self.client.post(
            '/api/v1/auth/login',
            data=json.dumps({
                "email": self.test_email,
                "password": new_password
            }),
            content_type='application/json'
        )
        self.assertEqual(login_resp.status_code, 200)

    def test_reset_password_with_invalid_code_fails(self):
        reset_resp = self.client.post(
            '/api/v1/auth/reset-password',
            data=json.dumps({
                "email": self.test_email,
                "code": "000000",
                "new_password": "NewPassword123"
            }),
            content_type='application/json'
        )
        self.assertEqual(reset_resp.status_code, 400)

    # ── AUTH-004 RBAC Permission Tests ──
    def test_rbac_permission_matrix(self):
        # OWNER & ADMIN
        self.assertTrue(has_permission(ROLE_OWNER, PERM_UPLOAD_DATA))
        self.assertTrue(has_permission(ROLE_OWNER, PERM_DELETE_DATASET))
        self.assertTrue(has_permission(ROLE_ADMIN, PERM_DELETE_DATASET))

        # ANALYST
        self.assertFalse(has_permission(ROLE_ANALYST, PERM_UPLOAD_DATA))
        self.assertFalse(has_permission(ROLE_ANALYST, PERM_DELETE_DATASET))
        self.assertTrue(has_permission(ROLE_ANALYST, PERM_RUN_SIMULATION))
        self.assertTrue(has_permission(ROLE_ANALYST, PERM_VIEW_FINANCIAL))

        # OPERATOR
        self.assertTrue(has_permission(ROLE_OPERATOR, PERM_UPLOAD_DATA))
        self.assertFalse(has_permission(ROLE_OPERATOR, PERM_DELETE_DATASET))
        self.assertFalse(has_permission(ROLE_OPERATOR, PERM_VIEW_FINANCIAL))
        self.assertTrue(has_permission(ROLE_OPERATOR, PERM_EXECUTE_ACTION))

        # VIEWER
        self.assertFalse(has_permission(ROLE_VIEWER, PERM_UPLOAD_DATA))
        self.assertFalse(has_permission(ROLE_VIEWER, PERM_DELETE_DATASET))
        self.assertFalse(has_permission(ROLE_VIEWER, PERM_RUN_SIMULATION))
        self.assertFalse(has_permission(ROLE_VIEWER, PERM_EXECUTE_ACTION))
        self.assertFalse(has_permission(ROLE_VIEWER, PERM_VIEW_FINANCIAL))
