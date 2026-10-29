import io
from rest_framework.test import APIClient
from django.test import TestCase
from django.utils import timezone

from supplyforge.models import (
    DatasetVersion,
    IngestionSession,
    User,
    Workspace,
    WorkspaceMember,
)
from supplyforge.services.error_matrix import ErrorMatrixRegistry
from supplyforge.views.auth import generate_access_token
from django.core.files.uploadedfile import SimpleUploadedFile


class ImportIdempotencyAndErrorMatrixTestCase(TestCase):
    """
    Test suite verifying:
    - IR-020 Import Idempotency: Duplicate network upload retries return existing session with idempotent_retry = True.
    - Requirement #22 Error Matrix: Standardized Error Matrix registry and API endpoint.
    """

    def setUp(self):
        self.client = APIClient()
        self.user_id = 'test_merchant_ir020'
        self.user = User.objects.create(
            email='ir020@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace, _ = Workspace.objects.get_or_create(
            id=1,
            defaults={'name': 'Test Workspace', 'owner': self.user},
        )
        WorkspaceMember.objects.get_or_create(
            workspace=self.workspace,
            user=self.user,
        )
        self.auth = {
            'HTTP_AUTHORIZATION': (
                f'Bearer {generate_access_token(self.user, self.workspace.id)}'
            )
        }

    def test_ir020_import_idempotency_retries(self):
        """Verify uploading exact same file twice returns existing session without duplicating datasets."""
        csv_bytes = b"order_id,sku,product_name,selling_price,quantity,order_date\nORD-IDEMP-01,SKU-IDEMP-1,Idempotent Product,199000,1,2026-08-01\n"
        file_1 = SimpleUploadedFile("orders_retried.csv", csv_bytes, content_type="text/csv")

        # Request #1
        res1 = self.client.post(
            '/api/v2/ingestion/upload',
            {'file': file_1, 'workspaceId': 1},
            format='multipart'
            ,
            **self.auth
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        session_id_1 = data1["sessionId"]

        # Request #2 (Network Retry with identical file bytes)
        file_2 = SimpleUploadedFile("orders_retried.csv", csv_bytes, content_type="text/csv")

        res2 = self.client.post(
            '/api/v2/ingestion/upload',
            {'file': file_2, 'workspaceId': 1},
            format='multipart'
            ,
            **self.auth
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()

        # Must return the SAME session and mark idempotent_retry = True
        self.assertEqual(data2["sessionId"], session_id_1)
        self.assertTrue(data2.get("idempotent_retry"))

        # Verify only 1 IngestionSession was created for workspace
        self.assertEqual(IngestionSession.objects.filter(workspace=self.workspace).count(), 1)

    def test_clear_allows_reimporting_an_archived_identical_file(self):
        """A deliberate reset retires the old fingerprint, not the history."""
        csv_bytes = (
            b'order_id,sku,product_name,selling_price,quantity,order_date\n'
            b'ORD-CLEAR-01,SKU-CLEAR-1,Reloadable Product,199000,1,2026-08-01\n'
        )
        initial_upload = self.client.post(
            '/api/v2/ingestion/upload',
            {
                'file': SimpleUploadedFile(
                    'reloadable.csv', csv_bytes, content_type='text/csv',
                ),
                'workspaceId': self.workspace.id,
            },
            format='multipart',
            **self.auth,
        )
        self.assertEqual(initial_upload.status_code, 200)
        session = IngestionSession.objects.get(id=initial_upload.json()['sessionId'])
        version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now(),
        )

        clear_response = self.client.delete('/api/v1/import/clear', **self.auth)

        self.assertEqual(clear_response.status_code, 200)
        session.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(session.status, 'ARCHIVED')
        self.assertEqual(session.error_code, 'DATASET_RETIRED')
        self.assertEqual(version.status, DatasetVersion.STATUS_SUPERSEDED)

        reupload = self.client.post(
            '/api/v2/ingestion/upload',
            {
                'file': SimpleUploadedFile(
                    'reloadable.csv', csv_bytes, content_type='text/csv',
                ),
                'workspaceId': self.workspace.id,
            },
            format='multipart',
            **self.auth,
        )

        self.assertEqual(reupload.status_code, 200)
        self.assertFalse(reupload.json().get('idempotent_retry', False))
        self.assertNotEqual(reupload.json()['sessionId'], str(session.id))
        self.assertEqual(IngestionSession.objects.filter(workspace=self.workspace).count(), 2)

    def test_reimport_recovers_a_legacy_cleared_completed_session(self):
        """Pre-fix cleared workspaces must not require a second clear action."""
        csv_bytes = (
            b'order_id,sku,product_name,selling_price,quantity,order_date\n'
            b'ORD-LEGACY-01,SKU-LEGACY-1,Legacy Product,199000,1,2026-08-01\n'
        )
        first_upload = self.client.post(
            '/api/v2/ingestion/upload',
            {
                'file': SimpleUploadedFile(
                    'legacy-cleared.csv', csv_bytes, content_type='text/csv',
                ),
                'workspaceId': self.workspace.id,
            },
            format='multipart',
            **self.auth,
        )
        self.assertEqual(first_upload.status_code, 200)
        session = IngestionSession.objects.get(id=first_upload.json()['sessionId'])
        session.status = 'COMPLETED'
        session.save(update_fields=['status', 'updated_at'])
        version = DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now(),
        )

        reupload = self.client.post(
            '/api/v2/ingestion/upload',
            {
                'file': SimpleUploadedFile(
                    'legacy-cleared.csv', csv_bytes, content_type='text/csv',
                ),
                'workspaceId': self.workspace.id,
            },
            format='multipart',
            **self.auth,
        )

        self.assertEqual(reupload.status_code, 200)
        self.assertFalse(reupload.json().get('idempotent_retry', False))
        session.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(session.status, 'ARCHIVED')
        self.assertEqual(version.status, DatasetVersion.STATUS_SUPERSEDED)

    def test_error_matrix_registry_api(self):
        """Verify Requirement #22: Error Matrix registry returns all 12 standardized error codes and behaviors."""
        matrix = ErrorMatrixRegistry.list_matrix()
        codes = [item["code"] for item in matrix]

        expected_codes = [
            'ERR_FILE_FORMAT', 'ERR_SCHEMA_MISSING', 'ERR_DATA_TYPE',
            'ERR_DUPLICATE', 'ERR_EMPTY_FILE', 'ERR_FILE_SIZE',
            'ERR_ENCODING', 'ERR_PROCESSING_TIMEOUT', 'ERR_DATABASE',
            'ERR_WORKER', 'ERR_AUTH', 'ERR_IMPORT_CONFLICT'
        ]

        for code in expected_codes:
            self.assertIn(code, codes)

        # Call GET /api/v2/ingestion/error-matrix API
        response = self.client.get('/api/v2/ingestion/error-matrix', **self.auth)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertIn('error_matrix', res_data)
        self.assertEqual(len(res_data['error_matrix']), len(expected_codes))
