from django.db import models

from .user import Workspace
from .product import Sku


class InsightAnomaly(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    insight_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=32, default='INFO')
    title = models.CharField(max_length=500)
    summary = models.TextField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    sku = models.ForeignKey(Sku, on_delete=models.SET_NULL, null=True, blank=True, db_column='sku_id')
    computed_at = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'insights_and_anomalies'
