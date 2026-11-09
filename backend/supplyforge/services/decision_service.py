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
from django.db import IntegrityError, transaction
from django.utils import timezone

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
        dataset_version: str = "v1.0",
        workspace_id: Optional[int] = None,
        assessment_run=None,
        decision_evidence_snapshot: Optional[Dict[str, Any]] = None,
    ) -> DecisionRecord:
        """
        Idempotently persists M6-08 recommendation and M6-09 explanation into Django ORM models.
        """
        base_rec_id = recommendation.get("recommendation_id") or f"DEC-{recommendation['sku']}"
        rec_id = f"WS{workspace_id}-{base_rec_id}" if workspace_id else base_rec_id
        sku = recommendation.get("sku", "UNKNOWN")

        # Check idempotency: If decision_id already exists, return existing record.
        existing = DecisionRecord.objects.filter(decision_id=rec_id).first()
        if existing:
            logger.info("Decision %s already exists. Returning existing record.", rec_id)
            return existing
        if assessment_run is not None:
            run_existing = DecisionRecord.objects.filter(
                assessment_run=assessment_run, sku=sku,
            ).first()
            if run_existing:
                logger.info(
                    "Decision for run %s / SKU %s already exists. Returning existing record.",
                    assessment_run.id, sku,
                )
                return run_existing

        act_obj = recommendation.get("action", {})
        prio_obj = recommendation.get("priority", {})
        impact_obj = recommendation.get("expected_impact", {})
        action_parameters = act_obj.get("parameters", {}) if isinstance(act_obj.get("parameters", {}), dict) else {}
        projection = action_parameters.get('projection') if isinstance(action_parameters.get('projection'), dict) else {}
        projection_status = str(projection.get('status') or 'LEGACY_UNVERIFIED')[:32]

        source_snapshot = decision_evidence_snapshot or {}
        if not isinstance(source_snapshot, dict):
            source_snapshot = {}
        evidence_state = str(source_snapshot.get('state') or 'LEGACY_UNVERIFIED')[:32]
        try:
            decision = DecisionRecord.objects.create(
                decision_id=rec_id,
                workspace_id=workspace_id or 1,
                sku=sku,
                dataset_version=dataset_version,
                assessment_run=assessment_run,
                source_key=getattr(assessment_run, 'source_key', '') or '',
                source_scope_fingerprint=getattr(assessment_run, 'source_scope_fingerprint', '') or '',
                source_snapshot_fingerprint=getattr(assessment_run, 'source_snapshot_fingerprint', '') or '',
                analysis_as_of=getattr(assessment_run, 'analysis_as_of', None),
                decision_evidence_snapshot=source_snapshot,
                evidence_state=evidence_state,
                risk_class=recommendation.get("risk_context", {}).get("risk_class") or "CRITICAL",
                risk_score=float(recommendation.get("risk_context", {}).get("risk_score") or 0.0),
                action_type=act_obj.get("type", "HOLD"),
                discount_rate=act_obj.get("discount_rate"),
                projection_status=projection_status,
                action_parameters=action_parameters,
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
        except IntegrityError:
            # Conditional uniqueness on assessment run/SKU is the final guard
            # for concurrent refresh workers.
            if assessment_run is not None:
                existing = DecisionRecord.objects.filter(assessment_run=assessment_run, sku=sku).first()
                if existing:
                    return existing
            raise

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
            base_exp_id = explanation.get("explanation_id") or f"EXP-{sku}"
            exp_id = f"WS{workspace_id}-{base_exp_id}" if workspace_id else base_exp_id
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

        from supplyforge.metrics import record_decision
        record_decision(decision_type=decision.action_type, action='generated', status='success')

        return decision

    @staticmethod
    @transaction.atomic
    def supersede_replaceable_for_sources(
        *, workspace_id: Optional[int], source_keys: List[str], current_run_ids: List[Any],
    ) -> int:
        """Retire stale draft recommendations without deleting merchant history."""
        if workspace_id is None or not source_keys:
            return 0
        rows = list(
            DecisionRecord.objects.select_for_update().filter(
                workspace_id=workspace_id,
                source_key__in=[key for key in source_keys if key],
                status__in={'GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW', 'MONITOR', 'NOT_APPLICABLE', 'REVIEWED'},
            ).exclude(assessment_run_id__in=current_run_ids)
        )
        if not rows:
            return 0
        now = timezone.now()
        for row in rows:
            old_status = row.status
            row.status = 'SUPERSEDED'
            row.superseded_at = now
            row.save(update_fields=['status', 'superseded_at', 'updated_at'])
            DecisionAuditEventRecord.objects.create(
                decision=row,
                event_type='DECISION_SUPERSEDED',
                old_status=old_status,
                new_status='SUPERSEDED',
                actor='system',
                notes='A newer current operational assessment run replaced this unreviewed recommendation.',
                metadata={'source_key': row.source_key},
            )
        return len(rows)

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
        dataset_version: Optional[str] = None,
        workspace_id: Optional[int] = None,
        include_superseded: bool = False,
    ) -> Any:
        """Queries DecisionRecords with optional filtering criteria."""
        queryset = DecisionRecord.objects.all()

        if not include_superseded:
            queryset = queryset.exclude(status='SUPERSEDED')

        if risk_class:
            queryset = queryset.filter(risk_class=risk_class)
        if priority:
            priority_tiers = [item.strip() for item in str(priority).split(',') if item.strip()]
            queryset = queryset.filter(priority_tier__in=priority_tiers)
        if action_type:
            queryset = queryset.filter(action_type=action_type)
        if status:
            statuses = [item.strip() for item in str(status).split(',') if item.strip()]
            queryset = queryset.filter(status__in=statuses)
        if sku:
            queryset = queryset.filter(sku=sku)
        if dataset_version:
            queryset = queryset.filter(dataset_version=dataset_version)
        if workspace_id is not None:
            queryset = queryset.filter(workspace_id=workspace_id)

        return queryset


class DecisionStatusService:
    """Service managing decision status transitions and audit logging."""

    VALID_TRANSITIONS = {
        'GENERATED': {'REVIEWED', 'ACCEPTED', 'REJECTED'},
        'RECOMMENDED': {'REVIEWED', 'ACCEPTED', 'REJECTED'},
        'NEEDS_REVIEW': {'REVIEWED', 'ACCEPTED', 'REJECTED'},
        'MONITOR': set(),
        'NOT_APPLICABLE': set(),
        'REVIEWED': {'ACCEPTED', 'REJECTED'},
        'ACCEPTED': {'EXECUTED', 'CANCELLED'},
        'REJECTED': set(),
        'EXECUTED': {'COMPLETED', 'CANCELLED'},
        'COMPLETED': set(),
        'CANCELLED': set(),
        'SUPERSEDED': set(),
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

        from supplyforge.metrics import record_decision
        if new_status in ('ACCEPTED', 'REVIEWED', 'EXECUTED', 'COMPLETED'):
            record_decision(decision_type=decision.action_type, action='approved', status='success')
        elif new_status in ('REJECTED', 'CANCELLED'):
            record_decision(decision_type=decision.action_type, action='rejected', status='success')

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
