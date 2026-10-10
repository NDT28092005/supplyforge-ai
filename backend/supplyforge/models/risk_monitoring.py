import uuid
from django.db import models
from django.utils import timezone
from .ingestion_session import IngestionSession


class RiskMonitoringRun(models.Model):
    """Django Persistence Model for M3-08 Risk Monitoring Run Snapshots."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(IngestionSession, on_delete=models.CASCADE, related_name='monitoring_runs')
    status = models.CharField(max_length=20, db_index=True)  # HEALTHY, WARNING, CRITICAL, INVALID
    total_skus_evaluated = models.IntegerField(default=0)

    risk_distribution = models.JSONField(default=dict)
    probability_stats = models.JSONField(default=dict)
    validation_summary = models.JSONField(default=dict)
    alerts = models.JSONField(default=list)

    run_timestamp = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-run_timestamp']
        indexes = [
            models.Index(fields=['session', 'status']),
        ]

    def __str__(self):
        return f"Monitoring Run {self.id} - {self.status} ({self.total_skus_evaluated} SKUs)"
