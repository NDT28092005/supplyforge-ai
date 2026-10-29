import uuid

from django.db import models


class DatasetVersion(models.Model):
    """Immutable lake version metadata for one ingestion session.

    Product and order tables remain the current operational projection. This
    model records every source/lake version so replacing that projection never
    removes the historical data required for training or audit.
    """

    STATUS_BUILDING = 'BUILDING'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_SUPERSEDED = 'SUPERSEDED'
    STATUS_FAILED = 'FAILED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_CHOICES = [
        (STATUS_BUILDING, 'Building'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_SUPERSEDED, 'Superseded'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace',
        on_delete=models.CASCADE,
        related_name='dataset_versions',
    )
    ingestion_session = models.OneToOneField(
        'supplyforge.IngestionSession',
        on_delete=models.CASCADE,
        related_name='dataset_version_record',
    )
    parent_version = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_versions',
    )
    version_number = models.PositiveIntegerField()
    version_label = models.CharField(max_length=64)
    import_type = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_BUILDING)

    raw_storage_path = models.CharField(max_length=1024, blank=True, default='')
    bronze_storage_path = models.CharField(max_length=1024, blank=True, default='')
    silver_storage_path = models.CharField(max_length=1024, blank=True, default='')
    gold_storage_path = models.CharField(max_length=1024, blank=True, default='')
    source_checksum = models.CharField(max_length=128, blank=True, default='')
    manifest_json = models.JSONField(default=dict, blank=True)
    row_count = models.BigIntegerField(default=0)
    valid_row_count = models.BigIntegerField(default=0)
    rejected_row_count = models.BigIntegerField(default=0)
    data_as_of = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'dataset_versions'
        ordering = ['-version_number']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'version_number'],
                name='dataset_version_workspace_number_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'status'],
                name='dataset_ver_workspa_65e541_idx',
            ),
            models.Index(
                fields=['workspace', 'created_at'],
                name='dataset_ver_workspa_9f5783_idx',
            ),
            models.Index(fields=['status'], name='dataset_version_status_idx'),
        ]

    def __str__(self):
        return f'{self.workspace_id}:{self.version_label} ({self.status})'
