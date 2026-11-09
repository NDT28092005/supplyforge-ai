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
        parameters = obj.action_parameters if isinstance(obj.action_parameters, dict) else {}
        return {
            'action': obj.action_type,
            'discount_rate': obj.discount_rate,
            'action_parameters': parameters,
            # This is the stable, localised merchant display model. Legacy
            # records may not have it; clients must then render their safe
            # fallback rather than invent an option-level financial result.
            'options': parameters.get('merchant_option_set'),
            'priority': obj.priority_tier,
            'priority_score': obj.priority_score,
            'priority_rank': obj.priority_rank,
            'urgency': obj.urgency,
            'confidence': obj.confidence,
            'status': obj.status
        }

    def get_financial_impact(self, obj):
        parameters = obj.action_parameters if isinstance(obj.action_parameters, dict) else {}
        projection = parameters.get('projection') if isinstance(parameters.get('projection'), dict) else {}
        projection_status = projection.get('status') or 'LEGACY_UNVERIFIED'
        return {
            'capital_exposure': obj.capital_exposure,
            'projected_inventory_cost_rotation': obj.expected_recovery_value,
            'inventory_cost_rotation_rate': obj.recovery_rate,
            'remaining_inventory_cost_exposure': obj.residual_exposure,
            'projection_status': projection_status,
            'interpretation': (
                'Giá vốn của lượng tồn dự kiến bán trong kịch bản; không phải doanh thu, tiền thực nhận hoặc vốn đã giải phóng thực tế.'
                if projection_status == 'SCENARIO_ESTIMATE'
                else 'Chưa có kịch bản giá/chi phí đã xác thực cho giá trị này; không dùng làm dự báo tài chính.'
            ),
            # Legacy response fields retained for consumers during migration.
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
            'engine_version': obj.engine_version,
            'assessment_run_id': str(obj.assessment_run_id) if obj.assessment_run_id else None,
            'source_key': obj.source_key or None,
            'source_scope_fingerprint': obj.source_scope_fingerprint or None,
            'source_snapshot_fingerprint': obj.source_snapshot_fingerprint or None,
            'analysis_as_of': obj.analysis_as_of.isoformat() if obj.analysis_as_of else None,
            'evidence_state': obj.evidence_state,
            'evidence_fingerprint': (obj.decision_evidence_snapshot or {}).get('fingerprint'),
        }


class DecisionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=DecisionRecord.STATUS_CHOICES)
    actor = serializers.CharField(required=False, default='merchant')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    feedback_reason = serializers.ChoiceField(
        choices=[
            'ALREADY_HAS_PLAN', 'DATA_DOES_NOT_MATCH', 'KEEP_PRICE_OR_STOCK',
            'SUPPLIER_OR_PO_LOCKED', 'TIMING_NOT_RIGHT', 'OTHER',
        ], required=False, allow_blank=True, default='',
    )
    feedback_note = serializers.CharField(required=False, allow_blank=True, default='', max_length=500)
