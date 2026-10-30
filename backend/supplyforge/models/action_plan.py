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
