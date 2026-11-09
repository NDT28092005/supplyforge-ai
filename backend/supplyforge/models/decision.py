"""
Django ORM Models for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Defines:
- DecisionRecord: Primary entity for recommendations & decision state.
- DecisionExplanationRecord: Snapshot of structured explanations (M6-09).
- DecisionEvidenceRecord: Immutable evidence traceability links.
- DecisionAuditEventRecord: Immutable audit trail for decision lifecycle events.
"""

import uuid

from django.db import models
from django.db.models import Q


class DecisionRecord(models.Model):
    """Primary Decision Record storing M6-08 DecisionRecommendation state."""
    
    STATUS_CHOICES = [
        ('GENERATED', 'GENERATED'),
        ('RECOMMENDED', 'RECOMMENDED'),
        ('NEEDS_REVIEW', 'NEEDS_REVIEW'),
        ('MONITOR', 'MONITOR'),
        ('NOT_APPLICABLE', 'NOT_APPLICABLE'),
        ('REVIEWED', 'REVIEWED'),
        ('ACCEPTED', 'ACCEPTED'),
        ('REJECTED', 'REJECTED'),
        ('EXECUTED', 'EXECUTED'),
        ('COMPLETED', 'COMPLETED'),
        ('CANCELLED', 'CANCELLED'),
        # A refreshed operational run may replace an unreviewed recommendation.
        # The row stays immutable and visible in history; it must not compete in
        # the merchant's current queue.
        ('SUPERSEDED', 'SUPERSEDED'),
    ]


    decision_id = models.CharField(max_length=128, unique=True, db_index=True)
    workspace_id = models.IntegerField(default=1, db_index=True)
    sku = models.CharField(max_length=128, db_index=True)
    dataset_version = models.CharField(max_length=64, default='v1.0')
    # Auto-generated decisions are bound to one immutable operational run.
    # Legacy/manual decisions intentionally retain a null relation, but cannot
    # be used as a source for a newly generated action.
    assessment_run = models.ForeignKey(
        'supplyforge.SlowMovingAssessmentRun', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='decisions',
    )
    source_key = models.CharField(max_length=128, blank=True, default='', db_index=True)
    source_scope_fingerprint = models.CharField(max_length=64, blank=True, default='', db_index=True)
    source_snapshot_fingerprint = models.CharField(max_length=64, blank=True, default='')
    analysis_as_of = models.DateTimeField(null=True, blank=True)
    # The exact compact fact contract used to form the decision.  It is
    # separate from `action_parameters`, which is allowed to carry the chosen
    # execution parameters and review state.
    decision_evidence_snapshot = models.JSONField(default=dict, blank=True)
    superseded_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='superseded_decisions',
    )
    superseded_at = models.DateTimeField(null=True, blank=True)

    risk_class = models.CharField(max_length=64, default='UNKNOWN')
    risk_score = models.FloatField(default=0.0)

    action_type = models.CharField(max_length=64, default='HOLD')
    discount_rate = models.FloatField(null=True, blank=True)
    # Typed queue filter copied from the immutable action snapshot at write
    # time. It prevents the current inbox from casting JSON for every row
    # merely to find decisions whose financial scenario is unavailable.
    projection_status = models.CharField(max_length=32, default='LEGACY_UNVERIFIED', db_index=True)
    # Same treatment for the decision-time fact contract.  Queue summaries
    # must not parse every JSON snapshot simply to tell a merchant whether
    # the underlying facts are complete.
    evidence_state = models.CharField(max_length=32, default='LEGACY_UNVERIFIED', db_index=True)
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
        indexes = [
            models.Index(
                fields=['workspace_id', 'status', 'dataset_version', 'priority_tier'],
                name='decision_ws_stat_ver_pri_idx',
            ),
            models.Index(
                fields=['workspace_id', 'source_key', 'status', 'sku'],
                name='decision_ws_src_status_sku',
            ),
            # Supports the default cursor queue without a deep OFFSET scan.
            models.Index(
                fields=['workspace_id', 'status', 'priority_score', 'created_at', 'decision_id'],
                name='decision_cursor_priority_idx',
            ),
            models.Index(
                fields=['workspace_id', 'status', 'projection_status', 'priority_score'],
                name='decision_queue_projection_idx',
            ),
            models.Index(
                fields=['workspace_id', 'status', 'evidence_state'],
                name='decision_queue_evidence_idx',
            ),
        ]
        constraints = [
            # One automatic decision for one SKU from one immutable run.  This
            # is the final idempotency guard when two refresh workers overlap.
            models.UniqueConstraint(
                fields=['assessment_run', 'sku'],
                condition=Q(assessment_run__isnull=False),
                name='decision_assessment_run_sku_uq',
            ),
        ]

    def __str__(self):
        return f"Decision({self.decision_id}, SKU={self.sku}, Action={self.action_type}, Status={self.status})"


class DecisionPortfolioRun(models.Model):
    """Immutable, capacity-constrained view of the current decision queue.

    A portfolio run deliberately *does not* create action plans or change a
    price/PO.  It records how the merchant-supplied operating constraints were
    applied at a point in time, so a deferred SKU is explainable and the same
    inputs can be replayed later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.IntegerField(db_index=True)
    policy_version = models.CharField(max_length=64)
    policy_checksum = models.CharField(max_length=64)
    input_config_json = models.JSONField(default=dict, blank=True)
    input_decision_ids_json = models.JSONField(default=list, blank=True)
    result_snapshot_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decision_portfolio_runs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace_id', 'created_at'], name='decision_portfolio_ws_at_idx'),
        ]


class DecisionReviewRecord(models.Model):
    """Append-only proof that a merchant checked a decision before execution.

    A recommendation is deliberately immutable.  This record holds the
    current source snapshot used for a later explicit re-approval, instead of
    silently replacing the snapshot that produced the recommendation.
    """

    STATUS_READY = 'READY'
    STATUS_NEEDS_RECHECK = 'NEEDS_RECHECK'
    STATUS_DATA_NEEDED = 'DATA_NEEDED'
    STATUS_CHOICES = [
        (STATUS_READY, 'Đủ điều kiện thực thi'),
        (STATUS_NEEDS_RECHECK, 'Cần xem lại'),
        (STATUS_DATA_NEEDED, 'Cần bổ sung dữ liệu'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    decision = models.ForeignKey(
        DecisionRecord, on_delete=models.CASCADE, related_name='review_records',
    )
    workspace_id = models.IntegerField(db_index=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, db_index=True)
    baseline_snapshot_json = models.JSONField(default=dict, blank=True)
    current_snapshot_json = models.JSONField(default=dict, blank=True)
    changes_json = models.JSONField(default=list, blank=True)
    summary = models.CharField(max_length=500, blank=True, default='')
    reviewed_by = models.CharField(max_length=128, blank=True, default='')
    review_note = models.TextField(blank=True, default='')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'decision_review_records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace_id', 'decision', 'created_at'], name='decision_review_ws_dec_at_idx'),
            models.Index(fields=['workspace_id', 'status', 'created_at'], name='decision_review_ws_stat_at_idx'),
        ]


class WeeklyActionRun(models.Model):
    """An immutable, merchant-created operating week based on a portfolio run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.IntegerField(db_index=True)
    portfolio_run = models.ForeignKey(
        DecisionPortfolioRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weekly_action_runs',
    )
    week_start = models.DateField(db_index=True)
    week_end = models.DateField(db_index=True)
    source_snapshot_json = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'weekly_action_runs'
        ordering = ['-week_start', '-created_at']
        indexes = [
            models.Index(fields=['workspace_id', 'week_start', 'created_at'], name='weekly_action_ws_week_at_idx'),
        ]


class WeeklyActionItem(models.Model):
    """One read-only commitment item in a weekly run; it never starts a plan."""

    STATE_READY = 'READY'
    STATE_NEEDS_OWNER = 'NEEDS_OWNER'
    STATE_BLOCKED = 'BLOCKED'
    STATE_DEFERRED = 'DEFERRED'
    STATE_CHOICES = [
        (STATE_READY, 'Sẵn sàng xử lý'),
        (STATE_NEEDS_OWNER, 'Cần giao người phụ trách'),
        (STATE_BLOCKED, 'Đang bị chặn'),
        (STATE_DEFERRED, 'Chưa làm trong kỳ này'),
    ]

    run = models.ForeignKey(WeeklyActionRun, on_delete=models.CASCADE, related_name='items')
    decision = models.ForeignKey(
        DecisionRecord, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weekly_action_items',
    )
    decision_id_snapshot = models.CharField(max_length=128, db_index=True)
    sku = models.CharField(max_length=128, db_index=True)
    strategy = models.CharField(max_length=64, blank=True, default='')
    state = models.CharField(max_length=24, choices=STATE_CHOICES, db_index=True)
    owner = models.ForeignKey(
        'supplyforge.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weekly_action_items',
    )
    owner_label = models.CharField(max_length=128, blank=True, default='')
    due_date = models.DateField(null=True, blank=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    reasons_json = models.JSONField(default=list, blank=True)
    next_step = models.CharField(max_length=500, blank=True, default='')
    source_item_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'weekly_action_items'
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['run', 'decision_id_snapshot'], name='weekly_action_run_decision_uq'),
        ]
        indexes = [
            models.Index(fields=['run', 'state', 'sort_order'], name='weekly_action_run_state_idx'),
            models.Index(fields=['owner', 'due_date', 'state'], name='weekly_action_owner_due_idx'),
        ]


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
