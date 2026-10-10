"""
SupplyForge AI — Notification & Alert Model (NOTI-001 & NOTI-002)
===============================================================
In-App notification system supporting 6 exact event triggers:
1. NEW_CRITICAL_SKU: New critical/high-risk SKU identified.
2. CAPITAL_EXPOSURE_INCREASE: Capital exposure increased significantly.
3. DATASET_STALE: Data older than 30 days without re-import.
4. IMPORT_FAILED: CSV import/parsing failure.
5. PREDICTION_FAILED: Model/simulation prediction failure.
6. ACTION_DEADLINE_APPROACHING: Action plan deadline approaching.
"""

from django.db import models


class NotificationRecord(models.Model):
    TRIGGER_NEW_CRITICAL_SKU = 'NEW_CRITICAL_SKU'
    TRIGGER_CAPITAL_EXPOSURE_INCREASE = 'CAPITAL_EXPOSURE_INCREASE'
    TRIGGER_DATASET_STALE = 'DATASET_STALE'
    TRIGGER_IMPORT_FAILED = 'IMPORT_FAILED'
    TRIGGER_PREDICTION_FAILED = 'PREDICTION_FAILED'
    TRIGGER_ACTION_DEADLINE_APPROACHING = 'ACTION_DEADLINE_APPROACHING'

    TRIGGER_CHOICES = [
        (TRIGGER_NEW_CRITICAL_SKU, 'Sản phẩm rủi ro cao mới'),
        (TRIGGER_CAPITAL_EXPOSURE_INCREASE, 'Vốn đọng tăng đột biến'),
        (TRIGGER_DATASET_STALE, 'Dữ liệu quá 30 ngày chưa cập nhật'),
        (TRIGGER_IMPORT_FAILED, 'Nạp tệp dữ liệu thất bại'),
        (TRIGGER_PREDICTION_FAILED, 'Lỗi mô hình dự báo'),
        (TRIGGER_ACTION_DEADLINE_APPROACHING, 'Sắp hết hạn thực thi kế hoạch'),
    ]

    SEVERITY_CRITICAL = 'CRITICAL'
    SEVERITY_HIGH = 'HIGH'
    SEVERITY_WARNING = 'WARNING'
    SEVERITY_INFO = 'INFO'

    SEVERITY_CHOICES = [
        (SEVERITY_CRITICAL, 'Khẩn cấp'),
        (SEVERITY_HIGH, 'Rủi ro cao'),
        (SEVERITY_WARNING, 'Cảnh báo'),
        (SEVERITY_INFO, 'Thông tin'),
    ]

    workspace_id = models.IntegerField(default=1, db_index=True)
    notification_type = models.CharField(max_length=64, choices=TRIGGER_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=32, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    is_read = models.BooleanField(default=False, db_index=True)
    related_sku = models.CharField(max_length=128, blank=True, null=True)
    action_url = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'supplyforge_notification'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity}] {self.title} - Read: {self.is_read}"
