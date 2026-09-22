"""
REST API Serializers for Task M5-09 Capital Exposure API & Persistence
Module 05: Capital Exposure & Aging Analysis
"""

from rest_framework import serializers
from supplyforge.models.capital_exposure import (
    CapitalExposureAnalysisRecord,
    CapitalExposureItemRecord
)


class CapitalExposureItemSerializer(serializers.ModelSerializer):
    """Serializer for SKU-level Capital Exposure Item Record."""
    class Meta:
        model = CapitalExposureItemRecord
        fields = [
            'id',
            'analysis_id',
            'sku',
            'canonical_sku_id',
            'product_name',
            'category',
            'inventory_value',
            'capital_exposure',
            'risk_weighted_exposure',
            'probability_adjusted_exposure',
            'aging_days',
            'aging_bucket',
            'aging_risk_level',
            'slow_moving_risk_class',
            'risk_probability',
            'aging_priority',
            'estimated_opportunity_cost',
            'aging_flags',
            'created_at'
        ]


class CapitalExposureAnalysisSerializer(serializers.ModelSerializer):
    """Serializer for Capital Exposure Analysis Record and Summary."""
    class Meta:
        model = CapitalExposureAnalysisRecord
        fields = [
            'analysis_id',
            'merchant_id',
            'dataset_version',
            'status',
            'calculation_version',
            'total_skus',
            'total_inventory_value',
            'total_risk_weighted_exposure',
            'total_probability_adjusted_exposure',
            'total_opportunity_cost',
            'annual_opportunity_rate',
            'summary_payload',
            'risk_distribution',
            'aging_distribution',
            'risk_aging_matrix',
            'reconciliation_status',
            'created_at',
            'completed_at'
        ]


class CreateCapitalExposureAnalysisRequestSerializer(serializers.Serializer):
    """Serializer for POST /api/capital-exposure/analyses request payload."""
    merchant_id = serializers.CharField(required=False, default="default_merchant")
    dataset_version = serializers.CharField(required=False, default="v1.0")
    annual_opportunity_rate = serializers.FloatField(required=False, default=0.12)
    analysis_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
