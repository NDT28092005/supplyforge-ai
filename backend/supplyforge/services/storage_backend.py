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

from django.conf import settings


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

    @staticmethod
    def delete(path):
        if path and os.path.exists(path):
            os.remove(path)

    @staticmethod
    def exists(path):
        return bool(path) and os.path.exists(path)


class S3StorageBackend:
    def __init__(self):
        import boto3

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            's3',
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION or None,
        )

    def save_uploaded_file(self, file_obj):
        import uuid

        extension = os.path.splitext(file_obj.name)[1] or '.csv'
        key = f"ingestion/raw/{uuid.uuid4().hex}{extension}"
        self.client.upload_fileobj(file_obj, self.bucket, key)
        metadata = self.client.head_object(Bucket=self.bucket, Key=key)
        return f"s3://{self.bucket}/{key}", int(metadata['ContentLength'])

    def save_bytes(self, content: bytes, key: str):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType='application/json',
        )
        return f"s3://{self.bucket}/{key}"

    def download_to(self, uri: str, destination):
        key = uri.split('/', 3)[-1]
        self.client.download_file(self.bucket, key, destination)

    def delete(self, uri):
        key = uri.split('/', 3)[-1]
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, uri):
        from botocore.exceptions import ClientError

        key = uri.split('/', 3)[-1]
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
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
