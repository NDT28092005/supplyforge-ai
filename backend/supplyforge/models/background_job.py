import uuid
from django.db import models
from .user import Workspace
from .ingestion_session import IngestionSession


class BackgroundJob(models.Model):
    """Platform-generic background job tracker with cooperative cancellation."""

    JOB_TYPE_CHOICES = [
        ('CSV_IMPORT', 'CSV Import Pipeline'),
        ('SHOPEE_SYNC', 'Shopee Data Sync'),
        ('ML_RETRAIN', 'Model Retraining'),
        ('FEATURE_REFRESH', 'Feature Store Refresh'),
        ('MODEL_EVALUATION', 'Model Offline Evaluation'),
        ('DATA_EXPORT', 'Data Export'),
        ('REPORT_GENERATION', 'Report Generation'),
        ('INTEGRATION_SYNC', 'ERP Integration Sync'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Chờ xử lý'),
        ('RUNNING', 'Đang xử lý'),
        ('COMPLETED', 'Hoàn thành'),
        ('FAILED', 'Thất bại'),
        ('CANCEL_REQUESTED', 'Đang hủy'),
        ('CANCELLED', 'Đã hủy'),
    ]

    STAGE_CHOICES = [
        ('PARSING', 'Đọc & kiểm tra file'),
        ('PROFILING', 'Phân tích cấu trúc dữ liệu'),
        ('MAPPING', 'Nhận diện cột dữ liệu'),
        ('IMPORTING', 'Nhập dữ liệu vào hệ thống'),
        ('ML_INFERENCE', 'Chạy mô hình AI đánh giá rủi ro'),
        ('FINALIZING', 'Hoàn tất'),
        ('INTEGRATION_SYNC', 'Đồng bộ ERP'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name='background_jobs'
    )

    # Job metadata
    job_type = models.CharField(max_length=32, choices=JOB_TYPE_CHOICES)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    ingestion_session = models.ForeignKey(
        IngestionSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='background_jobs'
    )

    # Idempotency
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    # Progress tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    current_stage = models.CharField(max_length=20, choices=STAGE_CHOICES, null=True, blank=True)
    progress_pct = models.IntegerField(default=0)  # 0-100 (estimated workflow progress)
    stages_json = models.JSONField(default=dict)    # Per-stage detail

    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Error handling
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=2)

    # File lifecycle
    file_deleted = models.BooleanField(default=False)

    # Result
    result_summary_json = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'background_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(
                fields=['workspace', 'status', 'created_at'],
                name='job_ws_status_created_idx',
            ),
            models.Index(fields=['celery_task_id']),
            models.Index(fields=['idempotency_key']),
        ]

    def __str__(self):
        return f"[{self.job_type}:{self.status}] Job {self.id} ({self.progress_pct}%)"
