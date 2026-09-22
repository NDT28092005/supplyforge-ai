"""
REST API Serializers for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Defines:
- DecisionSerializer: Serializes DecisionRecord into standard response contract.
- DecisionExplanationSerializer: Serializes DecisionExplanationRecord snapshot.
- DecisionAuditEventSerializer: Serializes DecisionAuditEventRecord.
- DecisionStatusUpdateSerializer: Validates status update requests.
"""

from rest_framework import serializers
from supplyforge.models.decision import (
    DecisionRecord, DecisionExplanationRecord,
    DecisionEvidenceRecord, DecisionAuditEventRecord,
)


class DecisionEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionEvidenceRecord
        fields = ['metric', 'value', 'source_module', 'interpretation', 'created_at']


class DecisionExplanationSerializer(serializers.ModelSerializer):
    evidences = DecisionEvidenceSerializer(many=True, read_only=True, source='decision.evidences')

    class Meta:
        model = DecisionExplanationRecord
        fields = [
            'explanation_id', 'sku', 'decision_summary', 'risk_explanation',
            'capital_explanation', 'aging_explanation', 'recovery_explanation',
            'priority_explanation', 'alternative_analysis', 'reason_codes',
            'limitations', 'confidence', 'evidences', 'created_at'
        ]


class DecisionAuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionAuditEventRecord
        fields = ['event_type', 'old_status', 'new_status', 'actor', 'notes', 'metadata', 'timestamp']


class DecisionSerializer(serializers.ModelSerializer):
    risk = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()
    financial_impact = serializers.SerializerMethodField()
    explanation = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = DecisionRecord
        fields = [
            'decision_id', 'sku', 'risk', 'decision', 'financial_impact',
            'explanation', 'metadata', 'created_at', 'updated_at'
        ]

    def get_risk(self, obj):
        return {
            'class': obj.risk_class,
            'score': obj.risk_score
        }

    def get_decision(self, obj):
        return {
            'action': obj.action_type,
            'discount_rate': obj.discount_rate,
            'action_parameters': obj.action_parameters,
            'priority': obj.priority_tier,
            'priority_score': obj.priority_score,
            'priority_rank': obj.priority_rank,
            'urgency': obj.urgency,
            'confidence': obj.confidence,
            'status': obj.status
        }

    def get_financial_impact(self, obj):
        return {
            'capital_exposure': obj.capital_exposure,
            'expected_recovery_value': obj.expected_recovery_value,
            'recovery_rate': obj.recovery_rate,
            'residual_exposure': obj.residual_exposure
        }

    def get_explanation(self, obj):
        first_exp = obj.explanations.first()
        if first_exp:
            return {
                'explanation_id': first_exp.explanation_id,
                'reason_codes': first_exp.reason_codes
            }
        return {
            'explanation_id': obj.explanation_id,
            'reason_codes': []
        }

    def get_metadata(self, obj):
        return {
            'dataset_version': obj.dataset_version,
            'policy_version': obj.policy_version,
            'engine_version': obj.engine_version
        }


class DecisionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=DecisionRecord.STATUS_CHOICES)
    actor = serializers.CharField(required=False, default='merchant')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
