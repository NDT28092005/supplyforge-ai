import uuid
from django.db import models
from django.utils import timezone
from .ingestion_session import IngestionSession


class SlowMovingRiskAssessment(models.Model):
    """Django Persistence Model for M3-07 Risk Assessment Snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(IngestionSession, on_delete=models.CASCADE, related_name='risk_assessments')
    sku = models.CharField(max_length=100, db_index=True)
    canonical_sku_id = models.CharField(max_length=100, db_index=True)
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, default='General')

    # Risk Metrics
    risk_class = models.CharField(max_length=20, db_index=True)  # CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK
    risk_probability = models.FloatField()
    risk_score = models.FloatField(db_index=True)

    # Diagnostics & Evidence
    primary_signals = models.JSONField(default=list)
    supporting_signals = models.JSONField(default=list)
    diagnostics = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)

    # Metadata & Lineage
    decision_cutoff = models.CharField(max_length=50, default='t0')
    model_version = models.CharField(max_length=50, default='xgboost_exp03_v1')
    calibration_version = models.CharField(max_length=50, default='calibration_v1.0')
    diagnostic_rule_version = models.CharField(max_length=50, default='rules_v1.0')
    dataset_version = models.CharField(max_length=50, default='v1.0')
    assessment_status = models.CharField(max_length=20, default='COMPLETE')

    assessment_timestamp = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-risk_score', 'sku']
        indexes = [
            models.Index(fields=['session', 'risk_class']),
            models.Index(fields=['session', 'sku']),
            # The risk queue filters one session/class and then orders by the
            # model score; this avoids a filesort at portfolio scale.
            models.Index(
                fields=['session', 'risk_class', '-risk_score'],
                name='risk_session_class_score_idx',
            ),
            models.Index(
                fields=['session', '-risk_score', 'sku'],
                name='risk_session_score_sku_idx',
            ),
        ]

    def __str__(self):
        return f"Assessment {self.sku} - {self.risk_class} ({self.risk_score})"
