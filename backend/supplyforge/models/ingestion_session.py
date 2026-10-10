import uuid
from django.db import models

from .user import Workspace


class IngestionSession(models.Model):
    """Tracks each CSV upload session with profiling metadata.

    Lifecycle:  UPLOADING → PROFILING → PROFILED → MAPPING → PROCESSING → COMPLETED
                                                                        ↘ FAILED
    """

    SESSION_TYPE_CHOICES = [
        ('INITIAL', 'Initial Upload'),
        ('INCREMENTAL', 'Incremental Upload'),
    ]

    STATUS_CHOICES = [
        ('UPLOADING', 'Uploading'),
        ('PROFILING', 'Profiling'),
        ('PROFILED', 'Profiled'),
        ('MAPPING', 'Column Mapping'),
        ('QUEUED', 'Queued'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name='ingestion_sessions'
    )

    # ── File metadata (IR-016 Raw / Processed Storage & IR-020 Idempotency) ──
    original_filename = models.CharField(max_length=512)
    file_size_bytes = models.BigIntegerField(default=0)
    storage_path = models.CharField(max_length=1024, blank=True, default='')
    raw_storage_path = models.CharField(max_length=1024, blank=True, default='')
    processed_storage_path = models.CharField(max_length=1024, blank=True, default='')
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    file_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    error_code = models.CharField(max_length=64, null=True, blank=True)

    # ── Profiling results (populated after streaming scan) ─────────────
    total_rows = models.BigIntegerField(null=True, blank=True)
    total_columns = models.IntegerField(null=True, blank=True)
    headers_json = models.JSONField(null=True, blank=True)
    column_types_json = models.JSONField(null=True, blank=True)
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    date_column_detected = models.CharField(max_length=255, null=True, blank=True)
    unique_sku_count = models.IntegerField(null=True, blank=True)
    sku_column_detected = models.CharField(max_length=255, null=True, blank=True)
    missing_values_json = models.JSONField(null=True, blank=True)
    preview_rows_json = models.JSONField(null=True, blank=True)

    # ── Dataset Profiling, Column Mapping, Schema Validation, Data Quality, SKU Normalization, Incremental Merge, Freshness, Ingestion History & Quality Report UI (DAT 02-10) ──
    readiness_status = models.CharField(max_length=32, default='PROFILED')
    readiness_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    dataset_profile_json = models.JSONField(null=True, blank=True)
    column_mapping_json = models.JSONField(null=True, blank=True)
    dataset_consistency_status = models.CharField(max_length=32, default='PENDING')
    dataset_consistency_json = models.JSONField(null=True, blank=True)
    schema_validation_status = models.CharField(max_length=32, default='VALID')
    schema_validation_json = models.JSONField(null=True, blank=True)
    quality_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    quality_status = models.CharField(max_length=32, default='GOOD')
    data_quality_json = models.JSONField(null=True, blank=True)
    canonical_sku_count = models.IntegerField(null=True, blank=True)
    sku_normalization_json = models.JSONField(null=True, blank=True)
    dataset_version = models.CharField(max_length=32, default='v1.0')
    incremental_merge_json = models.JSONField(null=True, blank=True)
    freshness_status = models.CharField(max_length=32, default='FRESH')
    freshness_days = models.IntegerField(null=True, blank=True)
    freshness_json = models.JSONField(null=True, blank=True)
    ingestion_id = models.CharField(max_length=64, null=True, blank=True)
    ingestion_history_json = models.JSONField(null=True, blank=True)
    consolidated_quality_json = models.JSONField(null=True, blank=True)
    final_readiness_status = models.CharField(max_length=32, default='NOT_READY')
    data_readiness_json = models.JSONField(null=True, blank=True)
    slow_moving_features_json = models.JSONField(null=True, blank=True)
    demand_pattern_json = models.JSONField(null=True, blank=True)
    risk_features_json = models.JSONField(null=True, blank=True)
    risk_feature_matrix_json = models.JSONField(null=True, blank=True)
    risk_scores_json = models.JSONField(null=True, blank=True)
    risk_classifications_json = models.JSONField(null=True, blank=True)
    risk_prioritized_queue_json = models.JSONField(null=True, blank=True)
    feature_readiness_certificate_json = models.JSONField(null=True, blank=True)
    feature_snapshot_metadata_json = models.JSONField(null=True, blank=True)
    module02_acceptance_json = models.JSONField(null=True, blank=True)
    risk_model_predictions_json = models.JSONField(null=True, blank=True)
    m3_risk_scores_json = models.JSONField(null=True, blank=True)
    m3_risk_classifications_json = models.JSONField(null=True, blank=True)
    m3_probability_calibration_json = models.JSONField(null=True, blank=True)
    m3_risk_diagnostics_json = models.JSONField(null=True, blank=True)
    m3_risk_assessments_json = models.JSONField(null=True, blank=True)

    # ── Session lifecycle ──────────────────────────────────────────────
    session_type = models.CharField(
        max_length=20, choices=SESSION_TYPE_CHOICES, default='INITIAL'
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='UPLOADING'
    )
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ingestion_sessions'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.status}] {self.original_filename} ({self.total_rows or '?'} rows)"
