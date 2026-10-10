from django.db import models
from .user import Workspace
from .ingestion_session import IngestionSession


class TenantFeatureSnapshot(models.Model):
    """Per-tenant, per-SKU feature vectors. Collection ONLY — not auto-retrain."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    sku_id = models.CharField(max_length=128, db_index=True)

    # 25-feature vector (matches model schema FV-2.0)
    feature_vector_json = models.JSONField()

    # Lineage
    session = models.ForeignKey(IngestionSession, on_delete=models.SET_NULL, null=True)
    computed_at = models.DateTimeField(auto_now=True)

    # Label (if available)
    actual_risk_level = models.CharField(max_length=32, null=True, blank=True)
    label_source = models.CharField(max_length=32, default='HEURISTIC')
    # OPERATIONAL_OUTCOME | FROZEN_GROUND_TRUTH | EXPERT_ANNOTATION | MERCHANT_FEEDBACK | HEURISTIC
    label_quality = models.CharField(max_length=16, default='COPPER')
    # GOLD | SILVER | BRONZE | COPPER
    label_observed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tenant_feature_snapshots'
        unique_together = ['workspace', 'sku_id']
        indexes = [
            models.Index(fields=['computed_at']),
            models.Index(fields=['label_quality']),
        ]


class ModelVersion(models.Model):
    """Model version tracking with full governance and audit trail."""

    STATUS_CHOICES = [
        ('TRAINING', 'Đang train'),
        ('EVALUATING', 'Đang đánh giá offline'),
        ('REGRESSION_GATE', 'Đang chạy ML Regression Gate'),
        ('SHADOW', 'Shadow mode (chạy song song)'),
        ('PROMOTION_REVIEW', 'Chờ admin approve'),
        ('ACTIVE', 'Đang sử dụng (production)'),
        ('RETIRED', 'Đã ngừng'),
        ('REJECTED', 'Bị từ chối (gate failed)'),
        ('FAILED', 'Train thất bại'),
    ]

    version = models.CharField(max_length=32, unique=True)       # risk-v1.3.0
    model_type = models.CharField(max_length=64)                 # XGBClassifier
    artifact_dir = models.CharField(max_length=512)              # models/risk-v1.3.0/
    artifact_sha256 = models.CharField(max_length=64)

    # Metrics
    macro_f1 = models.FloatField(null=True, blank=True)
    weighted_f1 = models.FloatField(null=True, blank=True)
    high_risk_recall = models.FloatField(null=True, blank=True)
    balanced_accuracy = models.FloatField(null=True, blank=True)
    ece = models.FloatField(null=True, blank=True)

    # Governance & Reproducibility
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='TRAINING')
    training_dataset_version = models.CharField(max_length=64, default='v1.0')
    validation_dataset_version = models.CharField(max_length=64, default='v1.0')
    training_cutoff = models.DateField(null=True, blank=True)
    threshold_version = models.CharField(max_length=32, default='TH-1.0')
    calibration_version = models.CharField(max_length=32, default='CAL-1.0')
    code_commit_sha = models.CharField(max_length=64, blank=True, default='')

    # Promotion audit trail
    promoted_by = models.CharField(max_length=128, null=True, blank=True)
    promotion_reason = models.TextField(null=True, blank=True)
    promotion_gate_result_json = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'model_versions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.version} [{self.status}]"
