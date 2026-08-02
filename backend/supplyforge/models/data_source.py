from django.db import models

from .user import Workspace


class DataSource(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    original_filename = models.CharField(max_length=512)
    storage_key = models.CharField(max_length=1024)
    content_type = models.CharField(max_length=128, null=True, blank=True)
    byte_size = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, default='PENDING')
    row_count = models.BigIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    column_mapping_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'data_sources'
