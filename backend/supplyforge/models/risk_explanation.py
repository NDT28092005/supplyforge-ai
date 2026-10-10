import uuid
from django.db import models
from django.utils import timezone
from .ingestion_session import IngestionSession


class RiskExplanationRecord(models.Model):
    """
    Django Persistence Model for Task M4-08 (Explainability API & Persistence).
    Persists Canonical Risk Explanation Objects from M4-07.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(IngestionSession, on_delete=models.CASCADE, null=True, blank=True, related_name='risk_explanations')
    sku = models.CharField(max_length=100, db_index=True)
    canonical_sku_id = models.CharField(max_length=100, db_index=True, blank=True, null=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)

    # Risk Metrics
    risk_class = models.CharField(max_length=20, db_index=True)  # CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK
    risk_probability = models.FloatField()
    risk_score = models.FloatField(db_index=True)

    # Versioning & Traceability
    model_version = models.CharField(max_length=50, default='xgboost_exp03_v1', db_index=True)
    explanation_version = models.CharField(max_length=50, default='1.0', db_index=True)
    evidence_status = models.CharField(max_length=20, default='AVAILABLE')

    # Full M4-07 Canonical Object Payload
    explanation_payload = models.JSONField(default=dict)

    # Audit Metadata
    pipeline_execution_id = models.CharField(max_length=100, blank=True, null=True)
    generated_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-generated_at', '-risk_score']
        indexes = [
            models.Index(fields=['sku', 'model_version', 'explanation_version']),
            models.Index(fields=['risk_class', 'generated_at']),
        ]

    def __str__(self):
        return f"ExplanationRecord {self.sku} - {self.risk_class} (v{self.explanation_version})"
