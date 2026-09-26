"""
Services Layer for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Provides:
- DecisionPersistenceService: Persists recommendation & explanation payloads idempotently.
- DecisionStatusService: Manages decision lifecycle state transitions with validation & audit logs.
- DecisionHistoryService: Retrieves decision audit trail timeline & historical snapshots.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from django.db import transaction

from supplyforge.models.decision import (
    DecisionRecord, DecisionExplanationRecord,
    DecisionEvidenceRecord, DecisionAuditEventRecord,
)

logger = logging.getLogger(__name__)


class InvalidStatusTransitionError(Exception):
    """Raised when an invalid decision status transition is attempted."""
    pass


class DecisionNotFoundError(Exception):
    """Raised when a requested decision record does not exist."""
    pass


class DecisionPersistenceService:
    """Service handling persistence and retrieval of DecisionRecords and related entities."""

    @staticmethod
    @transaction.atomic
    def persist_decision(
        recommendation: Dict[str, Any],
        explanation: Optional[Dict[str, Any]] = None,
        dataset_version: str = "v1.0"
    ) -> DecisionRecord:
        """
        Idempotently persists M6-08 recommendation and M6-09 explanation into Django ORM models.
        """
        rec_id = recommendation.get("recommendation_id") or f"DEC-{recommendation['sku']}"
        sku = recommendation.get("sku", "UNKNOWN")

        # Check idempotency: If decision_id already exists, return existing record
        existing = DecisionRecord.objects.filter(decision_id=rec_id).first()
        if existing:
            logger.info("Decision %s already exists. Returning existing record.", rec_id)
            return existing

        act_obj = recommendation.get("action", {})
        prio_obj = recommendation.get("priority", {})
        impact_obj = recommendation.get("expected_impact", {})

        decision = DecisionRecord.objects.create(
            decision_id=rec_id,
            sku=sku,
            dataset_version=dataset_version,
            risk_class=recommendation.get("risk_context", {}).get("risk_class") or "CRITICAL",
            risk_score=float(recommendation.get("risk_context", {}).get("risk_score") or 0.90),
            action_type=act_obj.get("type", "HOLD"),
            discount_rate=act_obj.get("discount_rate"),
            action_parameters=act_obj.get("parameters", {}),
            priority_tier=prio_obj.get("tier", "P4"),
            priority_score=float(prio_obj.get("score") or 0.0),
            priority_rank=int(prio_obj.get("rank") or 1),
            urgency=recommendation.get("urgency", "MONITOR"),
            confidence=recommendation.get("confidence", "MEDIUM"),
            capital_exposure=float(impact_obj.get("capital_exposure") or 0.0),
            expected_recovery_value=float(impact_obj.get("expected_recovery_value") or 0.0),
            recovery_rate=float(impact_obj.get("recovery_rate") or 0.0),
            residual_exposure=float(impact_obj.get("residual_exposure") or 0.0),
            status=recommendation.get("decision_status", "GENERATED"),
            policy_version=recommendation.get("policy_version", "v1.0"),
            engine_version=recommendation.get("engine_version", "m6-v1.0")
        )

        # 1. Create Initial Audit Event
        DecisionAuditEventRecord.objects.create(
            decision=decision,
            event_type="DECISION_CREATED",
            old_status=None,
            new_status=decision.status,
            actor="system",
            notes="Recommendation created by M6-08 Decision Engine."
        )

        # 2. Persist Explanation if provided
        if explanation:
            exp_id = explanation.get("explanation_id") or f"EXP-{sku}"
            decision.explanation_id = exp_id
            decision.save(update_fields=['explanation_id'])

            exp_rec = DecisionExplanationRecord.objects.create(
                explanation_id=exp_id,
                decision=decision,
                sku=sku,
                decision_summary=explanation.get("decision_summary", {}),
                risk_explanation=explanation.get("risk_explanation", {}),
                capital_explanation=explanation.get("capital_explanation", {}),
                aging_explanation=explanation.get("aging_explanation", {}),
                recovery_explanation=explanation.get("recovery_explanation", {}),
                priority_explanation=explanation.get("priority_explanation", {}),
                alternative_analysis=explanation.get("alternative_analysis", {}),
                reason_codes=explanation.get("reason_codes", []),
                limitations=explanation.get("limitations", []),
                confidence=explanation.get("confidence", "HIGH")
            )

            # Persist Evidence items
            for ev_item in explanation.get("evidence", []):
                DecisionEvidenceRecord.objects.create(
                    decision=decision,
                    metric=ev_item.get("metric", "UNKNOWN"),
                    value=str(ev_item.get("value", "")),
                    source_module=ev_item.get("source", "M6"),
                    interpretation=ev_item.get("interpretation", "")
                )

        return decision

    @staticmethod
    def get_decision(decision_id: str) -> DecisionRecord:
        """Retrieves a single DecisionRecord by decision_id."""
        record = DecisionRecord.objects.filter(decision_id=decision_id).first()
        if not record:
            raise DecisionNotFoundError(f"Decision {decision_id} not found.")
        return record

    @staticmethod
    def list_decisions(
        risk_class: Optional[str] = None,
        priority: Optional[str] = None,
        action_type: Optional[str] = None,
        status: Optional[str] = None,
        sku: Optional[str] = None,
        dataset_version: Optional[str] = None
    ) -> Any:
        """Queries DecisionRecords with optional filtering criteria."""
        from supplyforge.models import Product
        if not Product.objects.exists():
            DecisionRecord.objects.all().delete()
            return DecisionRecord.objects.none()

        queryset = DecisionRecord.objects.all()

        if risk_class:
            queryset = queryset.filter(risk_class=risk_class)
        if priority:
            queryset = queryset.filter(priority_tier=priority)
        if action_type:
            queryset = queryset.filter(action_type=action_type)
        if status:
            queryset = queryset.filter(status=status)
        if sku:
            queryset = queryset.filter(sku=sku)
        if dataset_version:
            queryset = queryset.filter(dataset_version=dataset_version)

        return queryset


class DecisionStatusService:
    """Service managing decision status transitions and audit logging."""

    VALID_TRANSITIONS = {
        'GENERATED': {'REVIEWED', 'ACCEPTED', 'REJECTED'},
        'RECOMMENDED': {'REVIEWED', 'ACCEPTED', 'REJECTED'},
        'REVIEWED': {'ACCEPTED', 'REJECTED'},
        'ACCEPTED': {'EXECUTED', 'CANCELLED'},
        'REJECTED': set(),
        'EXECUTED': {'COMPLETED', 'CANCELLED'},
        'COMPLETED': set(),
        'CANCELLED': set(),
    }


    @classmethod
    @transaction.atomic
    def update_status(
        cls,
        decision_id: str,
        new_status: str,
        actor: str = "merchant",
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DecisionRecord:
        """
        Validates state machine transition and updates decision status, logging an audit record.
        """
        decision = DecisionPersistenceService.get_decision(decision_id)
        current_status = decision.status

        if new_status == current_status:
            return decision

        allowed = cls.VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition status from '{current_status}' to '{new_status}'. Allowed transitions: {sorted(list(allowed))}"
            )

        decision.status = new_status
        decision.save(update_fields=['status', 'updated_at'])

        # Log Immutable Audit Event
        DecisionAuditEventRecord.objects.create(
            decision=decision,
            event_type=f"DECISION_{new_status}",
            old_status=current_status,
            new_status=new_status,
            actor=actor,
            notes=notes or f"Status changed to {new_status} by {actor}.",
            metadata=metadata or {}
        )

        return decision


class DecisionHistoryService:
    """Service retrieving decision lifecycle audit event history and explanation context."""

    @staticmethod
    def get_history(decision_id: str) -> Dict[str, Any]:
        """Retrieves complete audit event history timeline for a decision."""
        decision = DecisionPersistenceService.get_decision(decision_id)
        audit_events = decision.audit_events.all()

        history_items = [
            {
                "event_type": evt.event_type,
                "old_status": evt.old_status,
                "new_status": evt.new_status,
                "actor": evt.actor,
                "notes": evt.notes,
                "metadata": evt.metadata,
                "timestamp": evt.timestamp.isoformat()
            }
            for evt in audit_events
        ]

        return {
            "decision_id": decision.decision_id,
            "sku": decision.sku,
            "current_status": decision.status,
            "total_events": len(history_items),
            "history": history_items
        }
