"""
Django Database Model for ACT-001 & ACT-002 Action Plan & Status Management.
"""

from django.db import models
import uuid


class ActionPlanRecord(models.Model):
    """
    ACT-001 & ACT-002 Action Plan Model.
    
    Fields:
    - campaign_name: Name of campaign (e.g. "Clearance CRIT-024")
    - sku: SKU identifier
    - duration_days: Campaign duration (e.g. 14 days)
    - strategy: Discount/Execution strategy (e.g. "15% discount")
    - owner: Responsible party (e.g. "Merchant")
    - start_date: Campaign start date (e.g. "2026-09-28")
    - status: DRAFT, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED
    """
    STATUS_CHOICES = [
        ("DRAFT", "DRAFT"),
        ("CONFIRMED", "CONFIRMED"),
        ("IN_PROGRESS", "IN_PROGRESS"),
        ("COMPLETED", "COMPLETED"),
        ("CANCELLED", "CANCELLED")
    ]

    plan_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    workspace_id = models.IntegerField(default=1, db_index=True)
    campaign_name = models.CharField(max_length=255)
    sku = models.CharField(max_length=64, db_index=True)
    duration_days = models.IntegerField(default=14)
    strategy = models.CharField(max_length=128, default="15% discount")
    owner = models.CharField(max_length=128, default="Merchant")
    # Retain owner as a display snapshot for legacy plans while new plans can
    # be assigned to an actual workspace member.
    assignee_user = models.ForeignKey(
        'supplyforge.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_action_plans',
    )
    start_date = models.DateField()
    # Legacy records predate SLA tracking; API-created plans always provide it.
    due_date = models.DateField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="DRAFT", db_index=True)
    decision_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    # Preserve the exact operational parameters approved for this plan.  A
    # plan is an execution record, not a mutable copy of the recommendation.
    action_parameters = models.JSONField(default=dict, blank=True)
    # A small structured reason lets a merchant learn from plan changes
    # without treating free-form notes as a reporting contract.
    strategy_override_reason_code = models.CharField(max_length=48, blank=True, default='', db_index=True)
    strategy_override_reason = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # ACT-003: Merchant Confirmation Gate
    confirmed_by = models.CharField(max_length=128, null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    # ACT-004: Outcome Tracking (Decision Usefulness)
    expected_recovery_value = models.BigIntegerField(default=0)
    actual_recovery_value = models.BigIntegerField(null=True, blank=True)
    expected_sales_value = models.BigIntegerField(default=0)
    actual_sales_value = models.BigIntegerField(null=True, blank=True)
    expected_units_sold = models.IntegerField(default=0)
    actual_units_sold = models.IntegerField(null=True, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_notes = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    # This is a merchant close-out note, not a causal measurement.  Keeping it
    # separate from free-form outcome_notes makes the source/coverage boundary
    # visible to the UI and preserves the original reported values.
    outcome_review_json = models.JSONField(default=dict, blank=True)
    outcome_reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "action_plans"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=['workspace_id', 'status', 'due_date'],
                name='action_plan_ws_status_due_idx',
            ),
            models.Index(
                fields=['workspace_id', 'sku'],
                name='action_plan_ws_sku_idx',
            ),
        ]

    def __str__(self):
        return f"{self.campaign_name} [{self.status}]"


class ActionPlanScopeLock(models.Model):
    """One lock row per workspace/SKU serialises conflicting plan creation.

    JSON scope is deliberately kept on the plan itself so existing records stay
    readable.  This tiny table gives the compatibility gate an actual database
    lock instead of relying on a race-prone read-then-create sequence.
    """

    workspace_id = models.IntegerField(db_index=True)
    sku = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'action_plan_scope_locks'
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'sku'], name='action_plan_scope_lock_uq'),
        ]


class ActionPlanEventRecord(models.Model):
    """Immutable lifecycle evidence for an operational SKU action plan."""

    plan = models.ForeignKey(
        ActionPlanRecord,
        on_delete=models.CASCADE,
        related_name='events',
    )
    event_type = models.CharField(max_length=64, db_index=True)
    old_status = models.CharField(max_length=32, null=True, blank=True)
    new_status = models.CharField(max_length=32, null=True, blank=True)
    actor = models.CharField(max_length=128, default='system')
    notes = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'action_plan_events'
        ordering = ['timestamp']

    def __str__(self):
        return f"ActionPlanEvent({self.plan_id}, {self.event_type})"


class ActionPlanOutcomeObservation(models.Model):
    """Read-only ERP observation linked to an action plan.

    This does not overwrite merchant-entered actuals and does not attribute a
    stock or sales change to the action. It preserves a separately auditable
    ERP observation window for later review.
    """

    STATUS_OBSERVED = 'OBSERVED'
    STATUS_PARTIAL = 'PARTIAL'
    STATUS_UNAVAILABLE = 'UNAVAILABLE'
    STATUS_CHOICES = [
        (STATUS_OBSERVED, 'Observed'),
        (STATUS_PARTIAL, 'Partial'),
        (STATUS_UNAVAILABLE, 'Unavailable'),
    ]

    plan = models.OneToOneField(
        ActionPlanRecord,
        on_delete=models.CASCADE,
        related_name='observed_outcome',
    )
    connection = models.ForeignKey(
        'supplyforge.IntegrationConnection',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_outcome_observations',
    )
    observation_start = models.DateField(null=True, blank=True)
    observation_end = models.DateField(null=True, blank=True)
    observed_net_units_sold = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    observed_sales_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    opening_inventory_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    closing_inventory_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    observed_inventory_change = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    observed_inventory_value_change = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_UNAVAILABLE, db_index=True)
    missing_fields_json = models.JSONField(default=list, blank=True)
    source_lineage_json = models.JSONField(default=dict, blank=True)
    reconciled_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'action_plan_outcome_observations'
        indexes = [
            models.Index(fields=['status', 'reconciled_at'], name='action_obs_status_at_idx'),
        ]


class ActionPlanTask(models.Model):
    """A small, auditable unit of work required to execute an action plan."""

    STATUS_PENDING = 'PENDING'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_SKIPPED = 'SKIPPED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Chưa thực hiện'),
        (STATUS_IN_PROGRESS, 'Đang thực hiện'),
        (STATUS_COMPLETED, 'Đã hoàn thành'),
        (STATUS_SKIPPED, 'Không thực hiện'),
    ]

    plan = models.ForeignKey(ActionPlanRecord, on_delete=models.CASCADE, related_name='tasks')
    task_key = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    instruction = models.TextField(blank=True, default='')
    is_required = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    assignee_user = models.ForeignKey(
        'supplyforge.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_action_plan_tasks',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    completion_note = models.TextField(blank=True, default='')
    skipped_reason = models.TextField(blank=True, default='')
    completed_by = models.CharField(max_length=128, blank=True, default='')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'action_plan_tasks'
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'task_key'], name='action_task_plan_key_uq'),
        ]
        indexes = [
            models.Index(fields=['status', 'due_date'], name='action_task_status_due_idx'),
        ]


class ActionPlanEvidence(models.Model):
    """Evidence is a reference, never an unbounded file blob stored in the database."""

    task = models.ForeignKey(ActionPlanTask, on_delete=models.CASCADE, related_name='evidence')
    evidence_type = models.CharField(max_length=32, default='LINK')
    title = models.CharField(max_length=255)
    reference_url = models.URLField(max_length=1024, blank=True, default='')
    note = models.TextField(blank=True, default='')
    submitted_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'action_plan_evidence'
        ordering = ['-created_at']


class ActionPlanReminderDelivery(models.Model):
    """Delivery ledger makes scheduled reminders idempotent and supportable."""

    CHANNEL_IN_APP = 'IN_APP'
    CHANNEL_EMAIL = 'EMAIL'
    STATUS_PENDING = 'PENDING'
    STATUS_SENT = 'SENT'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [(STATUS_PENDING, 'Pending'), (STATUS_SENT, 'Sent'), (STATUS_FAILED, 'Failed')]

    plan = models.ForeignKey(ActionPlanRecord, on_delete=models.CASCADE, related_name='reminder_deliveries')
    task = models.ForeignKey(ActionPlanTask, on_delete=models.CASCADE, null=True, blank=True, related_name='reminder_deliveries')
    channel = models.CharField(max_length=16)
    reminder_key = models.CharField(max_length=128)
    recipient = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=512, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'action_plan_reminder_deliveries'
        constraints = [
            models.UniqueConstraint(fields=['plan', 'channel', 'reminder_key'], name='action_reminder_delivery_uq'),
        ]
