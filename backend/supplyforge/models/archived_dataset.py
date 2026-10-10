import uuid
from django.db import models


class ArchivedDataSet(models.Model):
    """Stores historical dataset snapshots archived when merchants reset/clear data.
    Preserved for training predictive AI models (Module 05-06).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=64, db_index=True)
    reason = models.CharField(max_length=255, default='MERCHANT_CLEAR_DATA')
    archived_at = models.DateTimeField(auto_now_add=True)
    product_count = models.IntegerField(default=0)
    order_count = models.IntegerField(default=0)
    snapshot_json = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'archived_datasets'
        ordering = ['-archived_at']

    def __str__(self):
        return f"[Archived {self.archived_at.strftime('%Y-%m-%d %H:%M')}] User: {self.user_id} ({self.product_count} prods, {self.order_count} orders)"
