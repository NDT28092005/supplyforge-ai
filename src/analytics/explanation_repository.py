"""
Task M4-08 — Explainability API & Persistence
Module 04: Slow-Moving Risk Explainability (XAI)

Repository layer for storing, versioning, auditing, filtering, and retrieving
Canonical Risk Explanation Objects from Django ORM or file backup.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.analytics.explainability_architecture import (
    ExplainabilityOrchestrator,
    ExplainabilityGuardrailError,
    PROJECT_ROOT
)
from src.analytics.explanation_assembly_engine import ExplanationValidator

logger = logging.getLogger(__name__)


class ExplanationRepositoryError(Exception):
    """Raised when repository operation or validation fails."""
    pass


class ExplanationRepository:
    """
    Production Explanation Repository for Task M4-08.
    
    Provides:
    - Persistence with validation & idempotency checks.
    - Historical versioning by model_version and explanation_version.
    - Filtering by risk_class, diagnostic_signal, model_version, generated_at.
    - Global explanation retrieval.
    - Graceful fallback if Django database is not migrated in test scripts.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.orchestrator = ExplainabilityOrchestrator(config_path=config_path) if config_path else ExplainabilityOrchestrator()

    def _get_model_class(self):
        try:
            from supplyforge.models import RiskExplanationRecord
            return RiskExplanationRecord
        except Exception as e:
            logger.warning("RiskExplanationRecord model unavailable: %s. Using file fallback repository.", e)
            return None

    def save_explanation(
        self,
        explanation_payload: Dict[str, Any],
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validates and persists a single Canonical Risk Explanation Object.
        Guarantees idempotency (prevents duplicate execution records).
        """
        # Validate canonical object structure & non-causal rules
        ExplanationValidator.validate(explanation_payload)

        sku = explanation_payload["sku"]
        ra = explanation_payload["risk_assessment"]
        meta = explanation_payload["metadata"]

        r_class = ra["risk_class"]
        r_prob = float(ra["risk_probability"])
        r_score = float(ra["risk_score"])
        m_ver = meta.get("model_version", "xgboost_exp03_v1")
        e_ver = meta.get("explanation_version", "1.0")
        gen_at_str = meta.get("generated_at", datetime.now(timezone.utc).isoformat())

        # Validate range constraints
        if not (0.0 <= r_prob <= 1.0):
            raise ExplanationRepositoryError(f"PERSISTENCE_REJECTED: Invalid risk_probability {r_prob}. Must be in [0, 1].")
        if r_class not in ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]:
            raise ExplanationRepositoryError(f"PERSISTENCE_REJECTED: Invalid risk_class '{r_class}'.")

        ModelClass = self._get_model_class()
        if ModelClass is not None:
            try:
                # Idempotency check: look for identical execution record
                existing = ModelClass.objects.filter(
                    sku=sku,
                    model_version=m_ver,
                    explanation_version=e_ver,
                    generated_at=gen_at_str
                ).first()

                if existing:
                    logger.info("Idempotent hit: Explanation record already exists for SKU %s at %s", sku, gen_at_str)
                    return existing.explanation_payload

                record = ModelClass.objects.create(
                    sku=sku,
                    canonical_sku_id=explanation_payload.get("canonical_sku_id"),
                    product_name=explanation_payload.get("product_name"),
                    risk_class=r_class,
                    risk_probability=r_prob,
                    risk_score=r_score,
                    model_version=m_ver,
                    explanation_version=e_ver,
                    evidence_status=explanation_payload.get("evidence_status", "AVAILABLE"),
                    explanation_payload=explanation_payload,
                    pipeline_execution_id=execution_id or f"exec_{sku}_{m_ver}",
                    generated_at=gen_at_str
                )
                return record.explanation_payload
            except Exception as e:
                logger.error("Failed to save explanation in Django DB: %s. Using file storage.", e)

        # File-based backup persistence
        reports_dir = os.path.join(PROJECT_ROOT, 'reports', 'persistent_explanations')
        os.makedirs(reports_dir, exist_ok=True)
        file_path = os.path.join(reports_dir, f"{sku}_{m_ver}_{e_ver}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(explanation_payload, f, indent=2, ensure_ascii=False)

        return explanation_payload

    def save_batch_explanations(
        self,
        canonical_batch: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Bulk persists multiple Canonical Risk Explanation Objects.
        """
        results = []
        for obj in canonical_batch:
            res = self.save_explanation(obj, session_id=session_id, execution_id=execution_id)
            results.append(res)
        return results

    def get_latest_sku_explanation(self, sku: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves latest Canonical Risk Explanation Object for a SKU.
        """
        ModelClass = self._get_model_class()
        if ModelClass is not None:
            try:
                record = ModelClass.objects.filter(sku=sku).order_by('-generated_at').first()
                if record:
                    return record.explanation_payload
            except Exception as e:
                logger.warning("DB read failed for SKU %s: %s", sku, e)

        # File backup fallback
        reports_dir = os.path.join(PROJECT_ROOT, 'reports', 'persistent_explanations')
        if os.path.exists(reports_dir):
            for fname in os.listdir(reports_dir):
                if fname.startswith(f"{sku}_") and fname.endswith(".json"):
                    with open(os.path.join(reports_dir, fname), 'r', encoding='utf-8') as f:
                        return json.load(f)

        # Default fallback reading risk_explanations.json
        risk_exp_file = os.path.join(PROJECT_ROOT, 'reports', 'risk_explanations.json')
        if os.path.exists(risk_exp_file):
            with open(risk_exp_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if item.get("sku") == sku:
                            return item

        return None

    def get_sku_explanation_history(self, sku: str) -> List[Dict[str, Any]]:
        """
        Retrieves historical Canonical Risk Explanation Objects for a SKU across model/explanation versions.
        """
        ModelClass = self._get_model_class()
        if ModelClass is not None:
            try:
                records = ModelClass.objects.filter(sku=sku).order_by('-generated_at')
                if records.exists():
                    return [r.explanation_payload for r in records]
            except Exception as e:
                logger.warning("DB history read failed for SKU %s: %s", sku, e)

        latest = self.get_latest_sku_explanation(sku)
        return [latest] if latest else []

    def get_batch_explanations(self, skus: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Retrieves latest explanation for a list of SKUs.
        """
        result = {}
        for s in skus:
            result[s] = self.get_latest_sku_explanation(s)
        return result

    def filter_explanations(
        self,
        risk_class: Optional[str] = None,
        diagnostic_signal: Optional[str] = None,
        model_version: Optional[str] = None,
        explanation_version: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Filters explanation records by risk_class, diagnostic_signal, model_version, etc.
        """
        ModelClass = self._get_model_class()
        if ModelClass is not None:
            try:
                qs = ModelClass.objects.all()
                if risk_class:
                    qs = qs.filter(risk_class=risk_class)
                if model_version:
                    qs = qs.filter(model_version=model_version)
                if explanation_version:
                    qs = qs.filter(explanation_version=explanation_version)

                records = qs.order_by('-generated_at')[:limit]

                results = []
                for r in records:
                    payload = r.explanation_payload
                    if diagnostic_signal:
                        # Check if diagnostic_signal is active in signals
                        signals = payload.get("diagnostic_signals", [])
                        active_codes = [s.get("code") for s in signals if isinstance(s, dict) and s.get("active")]
                        if diagnostic_signal not in active_codes:
                            continue
                    results.append(payload)
                return results
            except Exception as e:
                logger.warning("DB filter failed: %s", e)

        # File backup filtering
        risk_exp_file = os.path.join(PROJECT_ROOT, 'reports', 'risk_explanations.json')
        if os.path.exists(risk_exp_file):
            with open(risk_exp_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    filtered = []
                    for item in data:
                        ra = item.get("risk_assessment", {})
                        if risk_class and ra.get("risk_class") != risk_class:
                            continue
                        if diagnostic_signal:
                            signals = item.get("diagnostic_signals", [])
                            active_codes = [s.get("code") for s in signals if isinstance(s, dict) and s.get("active")]
                            if diagnostic_signal not in active_codes:
                                continue
                        filtered.append(item)
                    return filtered[:limit]

        return []

    def get_global_explanation(self) -> Dict[str, Any]:
        """
        Retrieves latest Global Risk Explanation payload.
        """
        global_path = os.path.join(PROJECT_ROOT, 'reports', 'global_risk_explanation.json')
        if os.path.exists(global_path):
            with open(global_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        return {
            "explanation_type": "GLOBAL",
            "explanation_version": "1.0",
            "population": {"total_skus": 0},
            "top_features": [],
            "disclaimer": "No global explanation computed yet."
        }
