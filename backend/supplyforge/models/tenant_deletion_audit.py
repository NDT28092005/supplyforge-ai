import uuid

from django.db import models


class TenantDeletionAudit(models.Model):
    """Immutable audit trail for the two-step tenant data deletion flow."""

    STATUS_PREVIEWED = 'PREVIEWED'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_EXECUTED = 'EXECUTED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PREVIEWED, 'Previewed'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_EXECUTED, 'Executed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE)
    actor = models.ForeignKey(
        'supplyforge.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tenant_deletion_audits',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PREVIEWED)
    confirmation_hash = models.CharField(max_length=64, blank=True, default='')
    preview_json = models.JSONField(default=dict, blank=True)
    purged_counts_json = models.JSONField(default=dict, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tenant_deletion_audits'
        indexes = [models.Index(fields=['workspace', 'created_at'], name='tenant_delete_ws_created_idx')]
