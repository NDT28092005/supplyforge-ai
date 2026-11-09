"""Append-only operational confounder records for slow-moving outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from supplyforge.models import SlowMovingAssessmentRun, SlowMovingDispositionEvent


class SlowMovingDispositionError(ValueError):
    """The disposition cannot be bound to a trusted operational scope."""


class SlowMovingDispositionService:
    """Record a merchant or source disposition against one frozen scope."""

    @staticmethod
    def record(
        *, run: SlowMovingAssessmentRun, canonical_sku: str, event_type: str,
        occurred_at: datetime, evidence_reference: str = '', provenance: dict[str, Any] | None = None,
    ) -> SlowMovingDispositionEvent:
        canonical_sku = str(canonical_sku or '').strip().upper()
        event_type = str(event_type or '').strip().upper()
        if not canonical_sku:
            raise SlowMovingDispositionError('CANONICAL_SKU_REQUIRED')
        valid_types = {value for value, _ in SlowMovingDispositionEvent.TYPE_CHOICES}
        if event_type not in valid_types:
            raise SlowMovingDispositionError('DISPOSITION_TYPE_INVALID')
        if not run.is_current or run.status != SlowMovingAssessmentRun.STATUS_COMPLETED:
            raise SlowMovingDispositionError('CURRENT_COMPLETED_RUN_REQUIRED')
        if not run.source_scope_fingerprint:
            raise SlowMovingDispositionError('SOURCE_SCOPE_FINGERPRINT_REQUIRED')
        if timezone.is_naive(occurred_at):
            occurred_at = timezone.make_aware(occurred_at, timezone.get_current_timezone())
        return SlowMovingDispositionEvent.objects.create(
            workspace_id=run.workspace_id,
            source_type=run.source_type,
            source_key=run.source_key,
            source_scope_fingerprint=run.source_scope_fingerprint,
            canonical_sku=canonical_sku,
            event_type=event_type,
            occurred_at=occurred_at,
            evidence_reference=str(evidence_reference or '').strip()[:512],
            provenance_json=dict(provenance or {}),
        )
