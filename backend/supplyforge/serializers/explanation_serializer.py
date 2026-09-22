from rest_framework import serializers


class RiskExplanationRecordSerializer(serializers.Serializer):
    """Serializer for M4-08 Canonical Risk Explanation Object REST API response."""

    sku = serializers.CharField(max_length=100)
    canonical_sku_id = serializers.CharField(max_length=100, required=False, allow_null=True)
    product_name = serializers.CharField(max_length=255, required=False, allow_null=True)
    risk_assessment = serializers.DictField()
    model_evidence = serializers.DictField()
    diagnostic_signals = serializers.ListField()
    supporting_metrics = serializers.DictField()
    explanation_summary = serializers.DictField()
    evidence_status = serializers.CharField(max_length=20, default="AVAILABLE")
    metadata = serializers.DictField()
    disclaimer = serializers.CharField()


class BatchExplanationRequestSerializer(serializers.Serializer):
    """Serializer for batch explanation retrieval request body."""

    skus = serializers.ListField(
        child=serializers.CharField(max_length=100),
        allow_empty=False
    )
