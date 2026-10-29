from unittest.mock import patch
from pathlib import Path

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.http import JsonResponse
from django.core.files.uploadedfile import SimpleUploadedFile

from supplyforge.middleware import (
    APIRateLimiterMiddleware,
    TenantIsolationMiddleware,
    TenantManager,
    set_current_tenant_context,
)
from supplyforge.models import CopilotConversation, IngestionSession, Product, User, Workspace
from supplyforge.request_identity import get_client_ip
from supplyforge.db_router import ReadReplicaRouter
from supplyforge.services.storage_backend import S3StorageBackend, StorageBackend


class HighSecurityTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    @override_settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_FAIL_CLOSED=True,
        RATE_LIMIT_WINDOW_SECONDS=60,
        RATE_LIMIT_API_REQUESTS=2,
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'high-security-tests',
            }
        },
    )
    def test_api_rate_limiter_uses_atomic_counter_and_returns_429(self):
        factory = RequestFactory()
        middleware = APIRateLimiterMiddleware(
            lambda request: JsonResponse({'ok': True})
        )

        for _ in range(2):
            response = middleware(
                factory.get('/api/v1/services', REMOTE_ADDR='198.51.100.10')
            )
            self.assertEqual(response.status_code, 200)

        response = middleware(
            factory.get('/api/v1/services', REMOTE_ADDR='198.51.100.10')
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response['X-RateLimit-Remaining'], '0')
        self.assertTrue(response['Retry-After'])

    @override_settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_FAIL_CLOSED=True,
        RATE_LIMIT_WINDOW_SECONDS=60,
        RATE_LIMIT_API_REQUESTS=1,
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'invalid-auth-rate-limit-tests',
            }
        },
    )
    def test_invalid_bearer_flood_is_limited_before_tenant_authentication(self):
        factory = RequestFactory()
        middleware = APIRateLimiterMiddleware(
            TenantIsolationMiddleware(lambda request: JsonResponse({'ok': True}))
        )

        first = middleware(
            factory.get(
                '/api/v1/services',
                REMOTE_ADDR='198.51.100.11',
                HTTP_AUTHORIZATION='Bearer invalid-token',
            )
        )
        second = middleware(
            factory.get(
                '/api/v1/services',
                REMOTE_ADDR='198.51.100.11',
                HTTP_AUTHORIZATION='Bearer invalid-token',
            )
        )

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 429)

    @override_settings(TRUSTED_PROXY_IPS=('10.0.0.5',))
    def test_forwarded_ip_is_used_only_from_trusted_proxy(self):
        factory = RequestFactory()
        trusted = factory.get(
            '/api/v1/ping',
            REMOTE_ADDR='10.0.0.5',
            HTTP_X_FORWARDED_FOR='198.51.100.20, 10.0.0.5',
        )
        untrusted = factory.get(
            '/api/v1/ping',
            REMOTE_ADDR='198.51.100.30',
            HTTP_X_FORWARDED_FOR='198.51.100.20',
        )
        self.assertEqual(get_client_ip(trusted), '198.51.100.20')
        self.assertEqual(get_client_ip(untrusted), '198.51.100.30')

    @override_settings(TRUSTED_PROXY_IPS=('10.0.0.0/16',))
    def test_forwarded_ip_is_accepted_from_configured_proxy_cidr(self):
        factory = RequestFactory()
        request = factory.get(
            '/api/v1/ping',
            REMOTE_ADDR='10.0.22.17',
            HTTP_X_FORWARDED_FOR='198.51.100.99, 10.0.22.17',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.99')

    @override_settings(
        STORAGE_BACKEND='local',
        INGESTION_UPLOAD_DIR='/tmp',
    )
    def test_local_storage_round_trip_isolated_from_upload_name(self):
        content = b'order_id,sku\norder-1,sku-1\n'
        uploaded = SimpleUploadedFile(
            '../../tenant-a.csv',
            content,
            content_type='text/csv',
        )
        path, size = StorageBackend.save_uploaded_file(uploaded)
        try:
            self.assertEqual(size, len(content))
            self.assertTrue(Path(path).is_file())
            with StorageBackend.localize(path) as local_path:
                self.assertEqual(Path(local_path).read_bytes(), content)
        finally:
            StorageBackend.delete(path)

    @override_settings(
        STORAGE_BACKEND='s3',
        S3_BUCKET='supplyforge-test',
        S3_ACCESS_KEY='access',
        S3_SECRET_KEY='secret',
        S3_REGION='us-east-1',
    )
    @patch('boto3.client')
    def test_s3_storage_round_trip_and_existence(self, client_factory):
        from botocore.exceptions import ClientError

        objects = {}

        class FakeS3Client:
            def upload_fileobj(self, file_obj, bucket, key):
                objects[(bucket, key)] = file_obj.read()

            def head_object(self, Bucket, Key):
                try:
                    content = objects[(Bucket, Key)]
                except KeyError:
                    raise ClientError(
                        {'Error': {'Code': '404'}},
                        'HeadObject',
                    )
                return {'ContentLength': len(content)}

            def download_file(self, bucket, key, destination):
                with open(destination, 'wb') as output:
                    output.write(objects[(bucket, key)])

            def delete_object(self, Bucket, Key):
                objects.pop((Bucket, Key), None)

        client_factory.return_value = FakeS3Client()
        uploaded = SimpleUploadedFile('orders.csv', b'order_id,sku\n1,A\n')
        path, size = StorageBackend.save_uploaded_file(uploaded)

        self.assertEqual(size, len(b'order_id,sku\n1,A\n'))
        self.assertTrue(path.startswith('s3://'))
        self.assertTrue(StorageBackend.exists(path))
        with StorageBackend.localize(path) as local_path:
            self.assertEqual(Path(local_path).read_bytes(), b'order_id,sku\n1,A\n')

        StorageBackend.delete(path)
        self.assertFalse(StorageBackend.exists(path))

    @override_settings(
        STORAGE_BACKEND='s3',
        S3_AUTH_MODE='auto',
        S3_BUCKET='supplyforge-test',
        S3_ENDPOINT_URL='',
        S3_ACCESS_KEY='',
        S3_SECRET_KEY='',
        S3_REGION='ap-southeast-1',
    )
    @patch('boto3.client')
    def test_s3_auto_auth_uses_aws_sdk_credential_chain(self, client_factory):
        S3StorageBackend()

        client_factory.assert_called_once_with(
            's3',
            endpoint_url=None,
            region_name='ap-southeast-1',
        )

    @override_settings(
        STORAGE_BACKEND='s3',
        S3_AUTH_MODE='static',
        S3_BUCKET='supplyforge-test',
        S3_ENDPOINT_URL='http://minio:9000',
        S3_ACCESS_KEY='access',
        S3_SECRET_KEY='secret',
        S3_REGION='us-east-1',
    )
    @patch('boto3.client')
    def test_s3_static_auth_passes_explicit_credentials(self, client_factory):
        S3StorageBackend()

        client_factory.assert_called_once_with(
            's3',
            endpoint_url='http://minio:9000',
            region_name='us-east-1',
            aws_access_key_id='access',
            aws_secret_access_key='secret',
        )


class HighSecurityDatabaseTests(TestCase):
    def tearDown(self):
        set_current_tenant_context(None, None)
        super().tearDown()

    def test_tenant_manager_normalizes_workspace_and_legacy_tenant_ids(self):
        owner = User.objects.create(
            email='manager-owner@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        workspace_a = Workspace.objects.create(name='Workspace A', owner=owner)
        workspace_b = Workspace.objects.create(name='Workspace B')
        session_a = IngestionSession.objects.create(
            workspace=workspace_a,
            original_filename='a.csv',
        )
        IngestionSession.objects.create(
            workspace=workspace_b,
            original_filename='b.csv',
        )
        Product.objects.create(
            id='product-manager-a',
            user_id=str(owner.id),
            third_party_id='third-party-a',
        )
        Product.objects.create(
            id='product-manager-b',
            user_id='other-user',
            third_party_id='third-party-b',
        )
        CopilotConversation.objects.create(
            tenant_id=f'T{workspace_a.id:03d}',
            merchant_id=str(owner.id),
        )
        CopilotConversation.objects.create(
            tenant_id=f'T{workspace_b.id:03d}',
            merchant_id='other-user',
        )

        set_current_tenant_context(workspace_a.id, owner.id)

        workspace_manager = TenantManager()
        workspace_manager.model = IngestionSession
        self.assertEqual(
            list(workspace_manager.get_queryset()),
            [session_a],
        )

        user_manager = TenantManager()
        user_manager.model = Product
        self.assertEqual(
            list(user_manager.get_queryset()).pop().user_id,
            str(owner.id),
        )

        tenant_manager = TenantManager()
        tenant_manager.model = CopilotConversation
        self.assertEqual(
            tenant_manager.get_queryset().count(),
            1,
        )

    def test_tenant_manager_fails_closed_without_context(self):
        manager = TenantManager()
        manager.model = IngestionSession
        set_current_tenant_context(None, None)
        self.assertEqual(manager.get_queryset().count(), 0)


class ReadReplicaRouterTests(SimpleTestCase):
    @override_settings(DATABASES={'default': {}, 'replica': {}})
    def test_reads_route_to_replica_but_writes_stay_on_default(self):
        router = ReadReplicaRouter()
        self.assertEqual(router.db_for_read(User), 'replica')
        self.assertIsNone(router.db_for_read(User, instance=User()))
        self.assertEqual(router.db_for_write(User), 'default')
        self.assertFalse(router.allow_migrate('replica', 'supplyforge'))

    @override_settings(DATABASES={'default': {}, 'replica': {}})
    def test_ingestion_workflow_reads_stay_on_primary(self):
        """A newly uploaded session must be readable by the next request."""
        router = ReadReplicaRouter()
        self.assertEqual(router.db_for_read(IngestionSession), 'default')
