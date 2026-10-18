"""Pluggable ingestion storage.

Local storage is intended for development and tests. Deployed environments
must use an S3-compatible bucket so web and worker replicas share uploads.
Large files are localized to a temporary file only while a parser needs a
filesystem path.
"""

from contextlib import contextmanager
import os
import shutil
import tempfile
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class LocalStorageBackend:
    def save_uploaded_file(self, file_obj):
        upload_dir = os.path.join(settings.INGESTION_UPLOAD_DIR, 'raw')
        os.makedirs(upload_dir, exist_ok=True)
        extension = os.path.splitext(file_obj.name)[1] or '.csv'
        filename = f"{__import__('uuid').uuid4().hex}{extension}"
        path = os.path.join(upload_dir, filename)
        total_bytes = 0
        with open(path, 'wb') as destination:
            for chunk in file_obj.chunks(chunk_size=8192):
                destination.write(chunk)
                total_bytes += len(chunk)
        return path, total_bytes

    def save_bytes(self, content: bytes, key: str):
        path = os.path.join(settings.INGESTION_UPLOAD_DIR, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as destination:
            destination.write(content)
        return path

    def copy_to_lake(self, source_path: str, key: str):
        destination = os.path.join(settings.INGESTION_UPLOAD_DIR, 'lake', key)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source_path, destination)
        return destination

    def save_lake_file(self, source_path: str, key: str):
        """Persist one derived artifact without first reading it into RAM."""
        destination = os.path.join(settings.INGESTION_UPLOAD_DIR, 'lake', key)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source_path, destination)
        return destination

    @staticmethod
    def delete(path):
        if path and os.path.exists(path):
            os.remove(path)

    @staticmethod
    def exists(path):
        return bool(path) and os.path.exists(path)


class S3StorageBackend:
    def __init__(self, bucket: str | None = None):
        import boto3

        self.bucket = bucket or settings.S3_BUCKET
        auth_mode = getattr(settings, 'S3_AUTH_MODE', 'auto').lower()
        access_key = settings.S3_ACCESS_KEY
        secret_key = settings.S3_SECRET_KEY
        has_static_credentials = bool(access_key or secret_key)

        if auth_mode not in {'auto', 'static'}:
            raise ImproperlyConfigured('S3_AUTH_MODE must be either auto or static.')
        if has_static_credentials and not (access_key and secret_key):
            raise ImproperlyConfigured(
                'S3_ACCESS_KEY and S3_SECRET_KEY must be configured together.'
            )
        if auth_mode == 'static' and not has_static_credentials:
            raise ImproperlyConfigured(
                'S3_ACCESS_KEY and S3_SECRET_KEY are required when S3_AUTH_MODE=static.'
            )

        client_options = {
            'endpoint_url': settings.S3_ENDPOINT_URL or None,
            'region_name': settings.S3_REGION or None,
        }
        if auth_mode == 'static' or has_static_credentials:
            client_options.update({
                'aws_access_key_id': access_key,
                'aws_secret_access_key': secret_key,
            })

        # Without explicit keys boto3 resolves ECS task-role, SSO, or other
        # standard AWS SDK credentials; credentials are never embedded in code.
        self.client = boto3.client(
            's3',
            **client_options,
        )

    @staticmethod
    def parse_s3_uri(uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        key = parsed.path.lstrip('/')
        if parsed.scheme != 's3' or not parsed.netloc or not key:
            raise ValueError('Invalid S3 URI.')
        return parsed.netloc, key

    @staticmethod
    def uri(bucket: str, key: str) -> str:
        return f's3://{bucket}/{key}'

    def save_uploaded_file(self, file_obj):
        import uuid

        extension = os.path.splitext(file_obj.name)[1] or '.csv'
        key = f"raw/legacy/{uuid.uuid4().hex}{extension}"
        self.client.upload_fileobj(file_obj, self.bucket, key)
        metadata = self.client.head_object(Bucket=self.bucket, Key=key)
        return self.uri(self.bucket, key), int(metadata['ContentLength'])

    def save_bytes(self, content: bytes, key: str):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType='application/json',
        )
        return self.uri(self.bucket, key)

    def upload_file(self, source_path: str, key: str, content_type: str) -> str:
        extra_args = {'ContentType': content_type} if content_type else None
        if extra_args:
            self.client.upload_file(source_path, self.bucket, key, ExtraArgs=extra_args)
        else:
            self.client.upload_file(source_path, self.bucket, key)
        return self.uri(self.bucket, key)

    def create_multipart_upload(self, key: str, content_type: str) -> dict:
        return self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type or 'text/csv',
            ChecksumAlgorithm='SHA256',
        )

    def generate_upload_part_url(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        expires_in: int,
    ) -> str:
        return self.client.generate_presigned_url(
            'upload_part',
            Params={
                'Bucket': self.bucket,
                'Key': key,
                'UploadId': upload_id,
                'PartNumber': part_number,
            },
            ExpiresIn=expires_in,
            HttpMethod='PUT',
        )

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict],
    ) -> dict:
        return self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={'Parts': parts},
        )

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        self.client.abort_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
        )

    def head_uri(self, uri: str) -> dict:
        bucket, key = self.parse_s3_uri(uri)
        return self.client.head_object(Bucket=bucket, Key=key)

    def copy_to_bucket(
        self,
        source_uri: str,
        destination_bucket: str,
        destination_key: str,
    ) -> str:
        source_bucket, source_key = self.parse_s3_uri(source_uri)
        self.client.copy_object(
            Bucket=destination_bucket,
            Key=destination_key,
            CopySource={'Bucket': source_bucket, 'Key': source_key},
            MetadataDirective='COPY',
        )
        return self.uri(destination_bucket, destination_key)

    def download_to(self, uri: str, destination):
        bucket, key = self.parse_s3_uri(uri)
        self.client.download_file(bucket, key, destination)

    def delete(self, uri):
        bucket, key = self.parse_s3_uri(uri)
        self.client.delete_object(Bucket=bucket, Key=key)

    def exists(self, uri):
        from botocore.exceptions import ClientError

        bucket, key = self.parse_s3_uri(uri)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = str(exc.response.get('Error', {}).get('Code', ''))
            if error_code in {'404', 'NoSuchKey', 'NotFound'}:
                return False
            raise


class StorageBackend:
    @classmethod
    def get_backend(cls):
        backend_type = getattr(settings, 'STORAGE_BACKEND', 'local')
        if backend_type == 's3':
            return S3StorageBackend()
        return LocalStorageBackend()

    @classmethod
    def save_uploaded_file(cls, file_obj):
        return cls.get_backend().save_uploaded_file(file_obj)

    @classmethod
    def save_bytes(cls, content: bytes, key: str):
        return cls.get_backend().save_bytes(content, key)

    @classmethod
    def save_processed_bytes(cls, content: bytes, key: str):
        """Store derived artifacts in the lake rather than the immutable raw bucket."""
        if getattr(settings, 'STORAGE_BACKEND', 'local') == 's3':
            lake_bucket = getattr(settings, 'S3_LAKE_BUCKET', '')
            if not lake_bucket:
                raise ImproperlyConfigured('S3_LAKE_BUCKET is required for lake output.')
            return S3StorageBackend(bucket=lake_bucket).save_bytes(content, key)
        return LocalStorageBackend().save_bytes(content, os.path.join('lake', key))

    @classmethod
    def save_processed_file(cls, source_path: str, key: str, content_type: str = ''):
        """Write a derived file to the lake using streaming file transfer."""
        if getattr(settings, 'STORAGE_BACKEND', 'local') == 's3':
            lake_bucket = getattr(settings, 'S3_LAKE_BUCKET', '')
            if not lake_bucket:
                raise ImproperlyConfigured('S3_LAKE_BUCKET is required for lake output.')
            return S3StorageBackend(bucket=lake_bucket).upload_file(
                source_path,
                key,
                content_type,
            )
        return LocalStorageBackend().save_lake_file(source_path, key)

    @classmethod
    def lake_uri(cls, key: str) -> str:
        """Return the canonical lake URI/path for metadata without uploading."""
        if getattr(settings, 'STORAGE_BACKEND', 'local') == 's3':
            lake_bucket = getattr(settings, 'S3_LAKE_BUCKET', '')
            if not lake_bucket:
                raise ImproperlyConfigured('S3_LAKE_BUCKET is required for lake output.')
            return S3StorageBackend.uri(lake_bucket, key)
        return os.path.join(settings.INGESTION_UPLOAD_DIR, 'lake', key)

    @classmethod
    def publish_raw_to_lake(cls, raw_storage_path: str, lake_key: str):
        """Copy the immutable source object to the bronze lake without buffering it."""
        if raw_storage_path.startswith('s3://'):
            lake_bucket = getattr(settings, 'S3_LAKE_BUCKET', '')
            if not lake_bucket:
                raise ImproperlyConfigured('S3_LAKE_BUCKET is required for lake output.')
            return cls.get_backend().copy_to_bucket(
                raw_storage_path,
                lake_bucket,
                lake_key,
            )
        return LocalStorageBackend().copy_to_lake(raw_storage_path, lake_key)

    @classmethod
    def exists(cls, storage_path: str):
        """Check local paths and object-storage URIs without treating a URI as a file."""
        if not storage_path:
            return False
        if storage_path.startswith('s3://'):
            return cls.get_backend().exists(storage_path)
        return LocalStorageBackend.exists(storage_path)

    @classmethod
    @contextmanager
    def localize(cls, storage_path: str):
        """Yield a local filesystem path for local and remote objects."""
        if not storage_path or not storage_path.startswith('s3://'):
            yield storage_path
            return

        suffix = os.path.splitext(storage_path)[1] or '.tmp'
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_path = temp_file.name
        temp_file.close()
        try:
            cls.get_backend().download_to(storage_path, temp_path)
            yield temp_path
        finally:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass

    @classmethod
    def delete(cls, storage_path: str):
        if not storage_path:
            return
        if storage_path.startswith('s3://'):
            cls.get_backend().delete(storage_path)
        else:
            LocalStorageBackend.delete(storage_path)
