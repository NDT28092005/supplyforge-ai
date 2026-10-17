import datetime

import jwt
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from supplyforge.models import User, Workspace
from supplyforge.services.tenant_isolation import TenantIsolationService
from supplyforge.views.auth import generate_access_token, get_or_create_user_tenant


class CriticalSecurityRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='critical-security@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER,
        )
        self.workspace = get_or_create_user_tenant(self.user)
        self.token = generate_access_token(self.user, workspace_id=self.workspace.id)

    def test_invalid_bearer_token_returns_401(self):
        response = self.client.get(
            '/api/v1/tenant/context',
            HTTP_AUTHORIZATION='Bearer not-a-jwt',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'INVALID_TOKEN')

    def test_expired_bearer_token_returns_401(self):
        token = jwt.encode(
            {
                'user_id': self.user.id,
                'workspace_id': self.workspace.id,
                'token_type': 'access',
                'exp': timezone.now() - datetime.timedelta(minutes=1),
            },
            settings.SECRET_KEY,
            algorithm='HS256',
        )
        response = self.client.get(
            '/api/v1/tenant/context',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'EXPIRED_TOKEN')

    def test_anonymous_request_has_no_tenant_context(self):
        response = self.client.get('/api/v1/tenant/context?workspaceId=1')
        self.assertEqual(response.status_code, 401)

    def test_client_workspace_selector_cannot_change_validated_context(self):
        response = self.client.get(
            '/api/v1/tenant/context?workspaceId=999999',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['tenant_context']['workspace_id'],
            self.workspace.id,
        )

    def test_tenant_service_does_not_trust_client_headers(self):
        class RequestWithForgedTenantHeader:
            headers = {'X-Tenant-ID': 'T999'}

        self.assertIsNone(
            TenantIsolationService.get_tenant_id_from_request(
                RequestWithForgedTenantHeader()
            )
        )

    def test_workspace_url_cannot_switch_active_token_workspace(self):
        other_workspace = Workspace.objects.create(name='Other Workspace')
        response = self.client.get(
            f'/api/v1/workspaces/{other_workspace.id}/aging',
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'WORKSPACE_ACCESS_DENIED')
