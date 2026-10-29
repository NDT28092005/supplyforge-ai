"""
Django ORM Models for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Defines:
- DecisionRecord: Primary entity for recommendations & decision state.
- DecisionExplanationRecord: Snapshot of structured explanations (M6-09).
- DecisionEvidenceRecord: Immutable evidence traceability links.
- DecisionAuditEventRecord: Immutable audit trail for decision lifecycle events.
"""

from django.db import models


class DecisionRecord(models.Model):
    """Primary Decision Record storing M6-08 DecisionRecommendation state."""
    
    STATUS_CHOICES = [
        ('GENERATED', 'GENERATED'),
        ('RECOMMENDED', 'RECOMMENDED'),
        ('REVIEWED', 'REVIEWED'),
        ('ACCEPTED', 'ACCEPTED'),
        ('REJECTED', 'REJECTED'),
        ('EXECUTED', 'EXECUTED'),
        ('COMPLETED', 'COMPLETED'),
        ('CANCELLED', 'CANCELLED'),
    ]


    decision_id = models.CharField(max_length=128, unique=True, db_index=True)
    workspace_id = models.IntegerField(default=1, db_index=True)
    sku = models.CharField(max_length=128, db_index=True)
    dataset_version = models.CharField(max_length=64, default='v1.0')

    risk_class = models.CharField(max_length=64, default='UNKNOWN')
    risk_score = models.FloatField(default=0.0)

    action_type = models.CharField(max_length=64, default='HOLD')
    discount_rate = models.FloatField(null=True, blank=True)
    action_parameters = models.JSONField(default=dict)

    priority_tier = models.CharField(max_length=16, default='P4')
    priority_score = models.FloatField(default=0.0)
    priority_rank = models.IntegerField(default=1)

    urgency = models.CharField(max_length=32, default='MONITOR')
    confidence = models.CharField(max_length=32, default='MEDIUM')

    capital_exposure = models.FloatField(default=0.0)
    expected_recovery_value = models.FloatField(default=0.0)
    recovery_rate = models.FloatField(default=0.0)
    residual_exposure = models.FloatField(default=0.0)

    explanation_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='GENERATED', db_index=True)

    policy_version = models.CharField(max_length=64, default='v1.0')
    engine_version = models.CharField(max_length=64, default='m6-v1.0')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'decision_records'
        ordering = ['-created_at']

    def __str__(self):
        return f"Decision({self.decision_id}, SKU={self.sku}, Action={self.action_type}, Status={self.status})"


class DecisionExplanationRecord(models.Model):
    """Snapshot of M6-09 DecisionExplanation payload associated with a DecisionRecord."""
    
    explanation_id = models.CharField(max_length=128, unique=True, db_index=True)
    decision = models.ForeignKey(DecisionRecord, on_delete=models.CASCADE, related_name='explanations')
    sku = models.CharField(max_length=128, db_index=True)

    decision_summary = models.JSONField(default=dict)
    risk_explanation = models.JSONField(default=dict)
    capital_explanation = models.JSONField(default=dict)
    aging_explanation = models.JSONField(default=dict)
    recovery_explanation = models.JSONField(default=dict)
    priority_explanation = models.JSONField(default=dict)

    alternative_analysis = models.JSONField(default=dict)
    reason_codes = models.JSONField(default=list)
    limitations = models.JSONField(default=list)
    confidence = models.CharField(max_length=32, default='HIGH')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decision_explanation_records'
        ordering = ['-created_at']

    def __str__(self):
        return f"Explanation({self.explanation_id}, Decision={self.decision.decision_id})"


class DecisionEvidenceRecord(models.Model):
    """Source traceability link mapping a decision metric back to its originating module."""
    
    decision = models.ForeignKey(DecisionRecord, on_delete=models.CASCADE, related_name='evidences')
    metric = models.CharField(max_length=128)
    value = models.CharField(max_length=256)
    source_module = models.CharField(max_length=64)
    interpretation = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decision_evidence_records'

    def __str__(self):
        return f"Evidence({self.metric}={self.value}, Source={self.source_module})"


class DecisionAuditEventRecord(models.Model):
    """Immutable audit trail recording state changes and events for a DecisionRecord."""
    
    decision = models.ForeignKey(DecisionRecord, on_delete=models.CASCADE, related_name='audit_events')
    event_type = models.CharField(max_length=64, db_index=True)
    old_status = models.CharField(max_length=32, null=True, blank=True)
    new_status = models.CharField(max_length=32, null=True, blank=True)
    actor = models.CharField(max_length=128, default='system')
    notes = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decision_audit_event_records'
        ordering = ['timestamp']

    def __str__(self):
        return f"AuditEvent({self.decision.decision_id}, Event={self.event_type}, {self.old_status}->{self.new_status})"
