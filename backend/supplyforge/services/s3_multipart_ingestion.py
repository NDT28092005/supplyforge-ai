"""S3 multipart ingestion contract and EventBridge event reconciliation."""

from __future__ import annotations

import base64
import hashlib
import math
import re
from urllib.parse import unquote_plus

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from supplyforge.models import IngestionSession, Workspace
from supplyforge.services.ingestion_jobs import (
    ImportJobDispatchError,
    create_or_get_import_job,
    dispatch_import_job,
)
from supplyforge.services.storage_backend import S3StorageBackend


class MultipartUploadError(ValueError):
    """A safe validation error that can be returned by the HTTP API."""


class S3MultipartIngestionService:
    """Creates tenant-scoped S3 uploads and turns completed objects into one job."""

    KEY_PATTERN = re.compile(
        r'^raw/workspace-(?P<workspace_id>\d+)/session-(?P<session_id>[0-9a-f-]{36})/source\.csv$'
    )

    @staticmethod
    def _require_s3() -> None:
        if getattr(settings, 'STORAGE_BACKEND', 'local') != 's3':
            raise MultipartUploadError('Cloud upload is not enabled in this environment.')
        if not settings.S3_BUCKET:
            raise MultipartUploadError('S3 raw bucket is not configured.')

    @staticmethod
    def _validated_metadata(
        filename: str,
        size_bytes: object,
        session_type: str,
    ) -> tuple[str, int, str]:
        filename = str(filename or '').strip()
        if not filename.lower().endswith('.csv'):
            raise MultipartUploadError('Hệ thống chỉ hỗ trợ tệp CSV.')
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise MultipartUploadError('sizeBytes phải là số nguyên dương.') from exc
        if size_bytes <= 0:
            raise MultipartUploadError('Tệp CSV không được rỗng.')
        max_size = settings.INGESTION_MAX_FILE_SIZE_MB * 1024 * 1024
        if size_bytes > max_size:
            raise MultipartUploadError('Tệp CSV vượt quá giới hạn upload đã cấu hình.')
        if session_type not in {'INITIAL', 'INCREMENTAL'}:
            raise MultipartUploadError('sessionType không hợp lệ.')
        return filename, size_bytes, session_type

    @staticmethod
    def _idempotency_key(workspace_id: int, client_key: str) -> str:
        material = f's3-multipart:{workspace_id}:{client_key}'.encode('utf-8')
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _event_idempotency_key(bucket: str, key: str, etag: str) -> str:
        material = f's3-event:{bucket}:{key}:{etag}'.encode('utf-8')
        return hashlib.sha256(material).hexdigest()

    @classmethod
    def _part_manifest(cls, session: IngestionSession) -> list[dict]:
        if not session.s3_upload_id or not session.s3_object_key:
            raise MultipartUploadError('Upload session is not initialized.')
        part_count = max(
            1,
            math.ceil(session.file_size_bytes / settings.S3_MULTIPART_PART_SIZE_BYTES),
        )
        if part_count > 10_000:
            raise MultipartUploadError('Tệp tạo quá nhiều multipart upload parts.')

        backend = S3StorageBackend()
        return [
            {
                'partNumber': part_number,
                'url': backend.generate_upload_part_url(
                    session.s3_object_key,
                    session.s3_upload_id,
                    part_number,
                    settings.S3_PRESIGNED_UPLOAD_TTL_SECONDS,
                ),
            }
            for part_number in range(1, part_count + 1)
        ]

    @classmethod
    def _initiate_payload(cls, session: IngestionSession, idempotent_retry: bool) -> dict:
        return {
            'sessionId': str(session.id),
            'uploadId': session.s3_upload_id,
            'objectKey': session.s3_object_key,
            'partSizeBytes': settings.S3_MULTIPART_PART_SIZE_BYTES,
            'expiresInSeconds': settings.S3_PRESIGNED_UPLOAD_TTL_SECONDS,
            'parts': cls._part_manifest(session),
            'idempotentRetry': idempotent_retry,
        }

    @classmethod
    def initiate(
        cls,
        workspace: Workspace,
        *,
        filename: str,
        size_bytes: object,
        content_type: str,
        session_type: str,
        client_idempotency_key: str,
    ) -> dict:
        cls._require_s3()
        filename, size_bytes, session_type = cls._validated_metadata(
            filename,
            size_bytes,
            session_type,
        )
        if not client_idempotency_key:
            raise MultipartUploadError('Idempotency-Key là bắt buộc cho cloud upload.')

        idempotency_key = cls._idempotency_key(workspace.id, client_idempotency_key)
        # Lock the tenant row before checking/reusing the key. Every caller
        # follows this path, so concurrent retries cannot create two uploads.
        with transaction.atomic():
            locked_workspace = Workspace.objects.select_for_update().get(id=workspace.id)
            existing = (
                IngestionSession.objects.filter(
                    workspace=locked_workspace,
                    idempotency_key=idempotency_key,
                    status='UPLOADING',
                )
                .exclude(s3_upload_id='')
                .order_by('-created_at')
                .first()
            )
            if existing:
                return cls._initiate_payload(existing, idempotent_retry=True)

            session = IngestionSession.objects.create(
                workspace=locked_workspace,
                original_filename=filename,
                file_size_bytes=size_bytes,
                idempotency_key=idempotency_key,
                session_type=session_type,
                status='UPLOADING',
            )
            object_key = f'raw/workspace-{locked_workspace.id}/session-{session.id}/source.csv'
            raw_uri = S3StorageBackend.uri(settings.S3_BUCKET, object_key)
            session.s3_object_key = object_key
            session.storage_path = raw_uri
            session.raw_storage_path = raw_uri
            session.save(update_fields=[
                's3_object_key', 'storage_path', 'raw_storage_path', 'updated_at'
            ])

            try:
                response = S3StorageBackend().create_multipart_upload(
                    object_key,
                    content_type or 'text/csv',
                )
            except Exception:
                session.status = 'FAILED'
                session.error_code = 'S3_MULTIPART_INIT_FAILED'
                session.error_message = 'Không thể khởi tạo cloud upload.'
                session.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])
                raise

            session.s3_upload_id = response['UploadId']
            session.save(update_fields=['s3_upload_id', 'updated_at'])
            return cls._initiate_payload(session, idempotent_retry=False)

    @staticmethod
    def _normalized_parts(parts: object, expected_part_count: int) -> list[dict]:
        if not isinstance(parts, list) or not parts:
            raise MultipartUploadError('parts phải chứa ít nhất một multipart ETag.')
        normalized = []
        seen_numbers = set()
        for part in parts:
            if not isinstance(part, dict):
                raise MultipartUploadError('Multipart part không hợp lệ.')
            try:
                number = int(part.get('partNumber'))
            except (TypeError, ValueError) as exc:
                raise MultipartUploadError('partNumber không hợp lệ.') from exc
            etag = str(part.get('eTag') or part.get('etag') or '').strip()
            if not 1 <= number <= 10_000 or not etag or number in seen_numbers:
                raise MultipartUploadError('Multipart part không hợp lệ.')
            seen_numbers.add(number)
            normalized.append({'PartNumber': number, 'ETag': etag})
        normalized.sort(key=lambda item: item['PartNumber'])
        expected_numbers = list(range(1, expected_part_count + 1))
        if [part['PartNumber'] for part in normalized] != expected_numbers:
            raise MultipartUploadError('Multipart parts không đầy đủ hoặc không đúng thứ tự.')
        return normalized

    @staticmethod
    def _checksum_hex(metadata: dict) -> str:
        checksum = str(metadata.get('ChecksumSHA256') or '')
        if not checksum:
            return ''
        try:
            decoded = base64.b64decode(checksum, validate=True)
        except Exception:
            return ''
        return decoded.hex() if len(decoded) == 32 else ''

    @classmethod
    def complete(
        cls,
        workspace: Workspace,
        session_id: str,
        *,
        upload_id: str,
        parts: object,
    ) -> tuple[dict, bool]:
        cls._require_s3()
        with transaction.atomic():
            try:
                session = IngestionSession.objects.select_for_update().get(
                    id=session_id,
                    workspace=workspace,
                )
            except IngestionSession.DoesNotExist as exc:
                raise MultipartUploadError('Không tìm thấy upload session.') from exc

            if session.s3_object_etag:
                job, created = create_or_get_import_job(
                    session,
                    cls._event_idempotency_key(
                        settings.S3_BUCKET,
                        session.s3_object_key,
                        session.s3_object_etag,
                    ),
                )
                payload = {'sessionId': str(session.id), 'jobId': str(job.id), 'status': job.status}
            else:
                if not upload_id or upload_id != session.s3_upload_id:
                    raise MultipartUploadError('uploadId không khớp upload session.')

                completed = S3StorageBackend().complete_multipart_upload(
                    session.s3_object_key,
                    upload_id,
                    cls._normalized_parts(
                        parts,
                        math.ceil(session.file_size_bytes / settings.S3_MULTIPART_PART_SIZE_BYTES),
                    ),
                )
                metadata = S3StorageBackend().head_uri(session.raw_storage_path)
                content_length = int(metadata.get('ContentLength') or 0)
                if content_length != session.file_size_bytes:
                    session.status = 'FAILED'
                    session.error_code = 'S3_OBJECT_SIZE_MISMATCH'
                    session.error_message = 'Kích thước object không khớp metadata upload.'
                    session.save(update_fields=['status', 'error_code', 'error_message', 'updated_at'])
                    raise MultipartUploadError('Kích thước object không hợp lệ.')

                etag = str(metadata.get('ETag') or completed.get('ETag') or '').strip('"')
                session.s3_object_etag = etag
                session.s3_checksum_sha256 = str(metadata.get('ChecksumSHA256') or '')
                session.file_hash = cls._checksum_hex(metadata) or session.file_hash
                session.upload_completed_at = timezone.now()
                session.save(update_fields=[
                    's3_object_etag', 's3_checksum_sha256', 'file_hash',
                    'upload_completed_at', 'updated_at',
                ])
                job, created = create_or_get_import_job(
                    session,
                    cls._event_idempotency_key(settings.S3_BUCKET, session.s3_object_key, etag),
                )
                payload = {'sessionId': str(session.id), 'jobId': str(job.id), 'status': 'PENDING'}

        if created:
            try:
                dispatch_import_job(job)
            except ImportJobDispatchError as exc:
                raise MultipartUploadError(
                    'Không thể kết nối hàng chờ xử lý. Vui lòng thử lại sau.'
                ) from exc
        return payload, created

    @classmethod
    def handle_object_created_event(cls, event: dict) -> tuple[dict | None, bool]:
        """Reconcile an EventBridge duplicate/fallback without trusting the event tenant."""
        detail = event.get('detail') if isinstance(event, dict) else None
        if not isinstance(detail, dict):
            return None, False
        bucket = str(detail.get('bucket', {}).get('name') or '')
        key = unquote_plus(str(detail.get('object', {}).get('key') or ''))
        match = cls.KEY_PATTERN.fullmatch(key)
        if bucket != settings.S3_BUCKET or not match:
            return None, False

        workspace_id = int(match.group('workspace_id'))
        session_id = match.group('session_id')
        expected_uri = S3StorageBackend.uri(bucket, key)
        etag = str(detail.get('object', {}).get('etag') or '').strip('"')

        with transaction.atomic():
            session = (
                IngestionSession.objects.select_for_update()
                .filter(
                    id=session_id,
                    workspace_id=workspace_id,
                    raw_storage_path=expected_uri,
                )
                .first()
            )
            if not session or session.status in {'FAILED', 'CANCELLED'}:
                return None, False

            metadata = S3StorageBackend().head_uri(expected_uri)
            session.file_size_bytes = int(metadata.get('ContentLength') or session.file_size_bytes)
            session.s3_object_etag = etag or str(metadata.get('ETag') or '').strip('"')
            session.s3_checksum_sha256 = str(metadata.get('ChecksumSHA256') or '')
            session.file_hash = cls._checksum_hex(metadata) or session.file_hash
            session.upload_completed_at = session.upload_completed_at or timezone.now()
            session.save(update_fields=[
                'file_size_bytes', 's3_object_etag', 's3_checksum_sha256',
                'file_hash', 'upload_completed_at', 'updated_at',
            ])
            job, created = create_or_get_import_job(
                session,
                cls._event_idempotency_key(bucket, key, session.s3_object_etag),
            )

        if created:
            try:
                dispatch_import_job(job)
            except ImportJobDispatchError:
                # The dispatcher has already marked the durable job as FAILED.
                # A replayed storage event can retry dispatch without re-uploading.
                return {'sessionId': str(session.id), 'jobId': str(job.id)}, False
        return {'sessionId': str(session.id), 'jobId': str(job.id)}, created
