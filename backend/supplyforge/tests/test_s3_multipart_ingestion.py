"""Unit tests for cloud multipart ingestion without contacting AWS."""

from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from supplyforge.models import BackgroundJob, IngestionSession, Workspace
from supplyforge.services.s3_multipart_ingestion import (
    MultipartUploadError,
    S3MultipartIngestionService,
)
from supplyforge.services.storage_backend import StorageBackend


class FakeS3StorageBackend:
    """In-memory S3 contract used to keep multipart tests offline."""

    create_calls = []
    complete_calls = []
    head_responses = {}

    def __init__(self, bucket=None):
        self.bucket = bucket or settings.S3_BUCKET

    @classmethod
    def reset(cls):
        cls.create_calls = []
        cls.complete_calls = []
        cls.head_responses = {}

    @staticmethod
    def uri(bucket, key):
        return f's3://{bucket}/{key}'

    def create_multipart_upload(self, key, content_type):
        self.create_calls.append((self.bucket, key, content_type))
        return {'UploadId': f'upload-{len(self.create_calls)}'}

    def generate_upload_part_url(self, key, upload_id, part_number, expires_in):
        return f'https://uploads.invalid/{key}?uploadId={upload_id}&part={part_number}'

    def complete_multipart_upload(self, key, upload_id, parts):
        self.complete_calls.append((self.bucket, key, upload_id, parts))
        return {'ETag': 'completed-etag'}

    def head_uri(self, uri):
        return self.head_responses[uri]


@override_settings(
    STORAGE_BACKEND='s3',
    S3_BUCKET='supplyforce-dev-raw',
    S3_LAKE_BUCKET='supplyforce-dev-lake',
    S3_MULTIPART_PART_SIZE_BYTES=8 * 1024 * 1024,
    S3_PRESIGNED_UPLOAD_TTL_SECONDS=900,
)
class S3MultipartIngestionServiceTests(TestCase):
    part_size = 8 * 1024 * 1024

    def setUp(self):
        FakeS3StorageBackend.reset()
        self.workspace_a = Workspace.objects.create(name='Workspace A')
        self.workspace_b = Workspace.objects.create(name='Workspace B')
        self.storage_backend = patch(
            'supplyforge.services.s3_multipart_ingestion.S3StorageBackend',
            FakeS3StorageBackend,
        )
        self.storage_backend.start()
        self.addCleanup(self.storage_backend.stop)

    def _initiate(self, workspace=None, size_bytes=None, key='request-001'):
        return S3MultipartIngestionService.initiate(
            workspace or self.workspace_a,
            filename='orders.csv',
            size_bytes=size_bytes or self.part_size,
            content_type='text/csv',
            session_type='INITIAL',
            client_idempotency_key=key,
        )

    def _event_for(self, session, workspace_id=None):
        return {
            'detail': {
                'bucket': {'name': settings.S3_BUCKET},
                'object': {
                    'key': session.s3_object_key,
                    'etag': 'event-etag',
                },
            },
        }

    def test_initiate_scopes_the_immutable_key_and_reuses_idempotency_key(self):
        payload = self._initiate(size_bytes=self.part_size + 1)
        session = IngestionSession.objects.get(id=payload['sessionId'])

        self.assertEqual(
            session.s3_object_key,
            f'raw/workspace-{self.workspace_a.id}/session-{session.id}/source.csv',
        )
        self.assertEqual(session.raw_storage_path, f's3://{settings.S3_BUCKET}/{session.s3_object_key}')
        self.assertEqual(len(payload['parts']), 2)
        self.assertFalse(payload['idempotentRetry'])
        self.assertEqual(len(FakeS3StorageBackend.create_calls), 1)

        retry = self._initiate(size_bytes=self.part_size + 1)

        self.assertEqual(retry['sessionId'], payload['sessionId'])
        self.assertTrue(retry['idempotentRetry'])
        self.assertEqual(len(FakeS3StorageBackend.create_calls), 1)

    def test_complete_is_tenant_scoped_and_requires_every_part(self):
        payload = self._initiate(size_bytes=self.part_size + 1)

        with self.assertRaises(MultipartUploadError):
            S3MultipartIngestionService.complete(
                self.workspace_b,
                payload['sessionId'],
                upload_id=payload['uploadId'],
                parts=[{'partNumber': 1, 'eTag': 'etag-1'}],
            )

        with self.assertRaises(MultipartUploadError):
            S3MultipartIngestionService.complete(
                self.workspace_a,
                payload['sessionId'],
                upload_id=payload['uploadId'],
                parts=[{'partNumber': 1, 'eTag': 'etag-1'}],
            )

        self.assertEqual(FakeS3StorageBackend.complete_calls, [])

    def test_complete_retry_creates_and_dispatches_exactly_one_job(self):
        payload = self._initiate()
        session = IngestionSession.objects.get(id=payload['sessionId'])
        FakeS3StorageBackend.head_responses[session.raw_storage_path] = {
            'ContentLength': self.part_size,
            'ETag': '"completed-etag"',
            'ChecksumSHA256': '',
        }

        with patch(
            'supplyforge.services.s3_multipart_ingestion.dispatch_import_job'
        ) as dispatch:
            first, created = S3MultipartIngestionService.complete(
                self.workspace_a,
                payload['sessionId'],
                upload_id=payload['uploadId'],
                parts=[{'partNumber': 1, 'eTag': 'etag-1'}],
            )
            retry, retry_created = S3MultipartIngestionService.complete(
                self.workspace_a,
                payload['sessionId'],
                upload_id=payload['uploadId'],
                parts=[{'partNumber': 1, 'eTag': 'etag-1'}],
            )

        self.assertTrue(created)
        self.assertFalse(retry_created)
        self.assertEqual(first['jobId'], retry['jobId'])
        self.assertEqual(BackgroundJob.objects.filter(ingestion_session=session).count(), 1)
        dispatch.assert_called_once()

    def test_duplicate_object_created_events_create_one_job(self):
        payload = self._initiate()
        session = IngestionSession.objects.get(id=payload['sessionId'])
        FakeS3StorageBackend.head_responses[session.raw_storage_path] = {
            'ContentLength': self.part_size,
            'ETag': '"event-etag"',
            'ChecksumSHA256': '',
        }
        event = self._event_for(session)

        with patch(
            'supplyforge.services.s3_multipart_ingestion.dispatch_import_job'
        ) as dispatch:
            first, created = S3MultipartIngestionService.handle_object_created_event(event)
            retry, retry_created = S3MultipartIngestionService.handle_object_created_event(event)

        self.assertTrue(created)
        self.assertFalse(retry_created)
        self.assertEqual(first['jobId'], retry['jobId'])
        self.assertEqual(BackgroundJob.objects.filter(ingestion_session=session).count(), 1)
        dispatch.assert_called_once()

    def test_event_with_workspace_key_mismatch_is_ignored(self):
        payload = self._initiate(workspace=self.workspace_b)
        session = IngestionSession.objects.get(id=payload['sessionId'])
        mismatched_key = session.s3_object_key.replace(
            f'workspace-{self.workspace_b.id}',
            f'workspace-{self.workspace_a.id}',
        )
        event = self._event_for(session)
        event['detail']['object']['key'] = mismatched_key

        result, created = S3MultipartIngestionService.handle_object_created_event(event)

        self.assertIsNone(result)
        self.assertFalse(created)
        self.assertEqual(BackgroundJob.objects.count(), 0)


@override_settings(
    STORAGE_BACKEND='s3',
    S3_BUCKET='supplyforce-dev-raw',
    S3_LAKE_BUCKET='supplyforce-dev-lake',
)
class LakePublishingTests(TestCase):
    def test_raw_to_bronze_uses_server_side_copy(self):
        backend = Mock()
        backend.copy_to_bucket.return_value = 's3://supplyforce-dev-lake/bronze.csv'
        source = 's3://supplyforce-dev-raw/raw/workspace-1/session-1/source.csv'

        with patch.object(StorageBackend, 'get_backend', return_value=backend):
            destination = StorageBackend.publish_raw_to_lake(
                source,
                'bronze/workspace-1/sessions/session-1/source.csv',
            )

        self.assertEqual(destination, 's3://supplyforce-dev-lake/bronze.csv')
        backend.copy_to_bucket.assert_called_once_with(
            source,
            'supplyforce-dev-lake',
            'bronze/workspace-1/sessions/session-1/source.csv',
        )
