"""
Django ORM Models for Task M5-09 Capital Exposure API & Persistence
Module 05: Capital Exposure & Aging Analysis
"""

import uuid
from django.db import models


class CapitalExposureAnalysisRecord(models.Model):
    """
    Persists analysis run metadata and portfolio-level aggregations for Module 05.
    """
    analysis_id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
    merchant_id = models.CharField(max_length=64, db_index=True, default="default_merchant")
    dataset_version = models.CharField(max_length=64, db_index=True, default="v1.0")
    status = models.CharField(max_length=20, default="COMPLETED", db_index=True)
    calculation_version = models.CharField(max_length=20, default="5.0")
    
    total_skus = models.IntegerField(default=0)
    total_inventory_value = models.FloatField(default=0.0)
    total_risk_weighted_exposure = models.FloatField(default=0.0)
    total_probability_adjusted_exposure = models.FloatField(default=0.0)
    total_opportunity_cost = models.FloatField(default=0.0)
    annual_opportunity_rate = models.FloatField(default=0.12)
    
    summary_payload = models.JSONField(default=dict)
    risk_distribution = models.JSONField(default=list)
    aging_distribution = models.JSONField(default=list)
    risk_aging_matrix = models.JSONField(default=list)
    reconciliation_status = models.JSONField(default=dict)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "supplyforge_capital_exposure_analysis"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Analysis {self.analysis_id} ({self.dataset_version}) - {self.status}"


class CapitalExposureItemRecord(models.Model):
    """
    Persists detailed SKU-level financial, aging, and exposure metrics.
    """
    analysis = models.ForeignKey(
        CapitalExposureAnalysisRecord,
        on_delete=models.CASCADE,
        related_name="items"
    )
    sku = models.CharField(max_length=64, db_index=True)
    canonical_sku_id = models.CharField(max_length=64, null=True, blank=True)
    product_name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    
    inventory_value = models.FloatField(default=0.0)
    capital_exposure = models.FloatField(default=0.0)
    risk_weighted_exposure = models.FloatField(default=0.0, db_index=True)
    probability_adjusted_exposure = models.FloatField(default=0.0)
    
    aging_days = models.IntegerField(null=True, blank=True)
    aging_bucket = models.CharField(max_length=32, db_index=True)
    aging_risk_level = models.CharField(max_length=32, db_index=True)
    slow_moving_risk_class = models.CharField(max_length=32, db_index=True)
    risk_probability = models.FloatField(default=0.0)
    
    aging_priority = models.CharField(max_length=16, db_index=True)
    estimated_opportunity_cost = models.FloatField(null=True, blank=True)
    aging_flags = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "supplyforge_capital_exposure_item"
        ordering = ["-risk_weighted_exposure"]
        indexes = [
            models.Index(fields=["analysis", "slow_moving_risk_class"]),
            models.Index(fields=["analysis", "aging_risk_level"]),
            models.Index(fields=["analysis", "aging_priority"]),
        ]

    def __str__(self):
        return f"Item {self.sku} ({self.slow_moving_risk_class}) - RWCE: {self.risk_weighted_exposure}"
