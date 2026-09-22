"""
Task M5-01 — Capital Exposure Architecture
Module 05: Capital Exposure & Aging Analysis

Defines architecture orchestrator, inventory evidence boundary rules, domain models,
data contracts, and validation guardrails for Module 05.
"""

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROHIBITED_CAUSAL_PHRASES = [
    "nguyên nhân gây ra khoản lỗ",
    "chắc chắn hỏng",
    "gây ra mất vốn",
    "stockout thực tế",
    "kho tồn thực sự bị hủy"
]


class DataAvailabilityState(str, Enum):
    """Data availability & readiness states for inventory and financial cost data."""
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INVALID = "INVALID"
    STALE = "STALE"


class CapitalExposureGuardrailError(Exception):
    """Raised when Module 05 inventory evidence boundaries or guardrails are violated."""
    pass


class InventoryEvidenceBoundary:
    """Enforces strict inventory evidence rules and scope boundaries for Module 05."""

    @staticmethod
    def validate_inventory_evidence(
        stock_on_hand: Optional[Union[int, float]],
        unit_cost: Optional[Union[int, float]]
    ) -> DataAvailabilityState:
        """
        Determines the inventory data availability state without making assumptions.
        """
        if stock_on_hand is None and unit_cost is None:
            return DataAvailabilityState.MISSING

        if stock_on_hand is None or unit_cost is None:
            return DataAvailabilityState.PARTIAL

        if stock_on_hand < 0 or unit_cost <= 0:
            return DataAvailabilityState.INVALID

        return DataAvailabilityState.AVAILABLE

    @staticmethod
    def validate_no_sales_to_stock_substitution(feature_dict: Dict[str, Any]) -> bool:
        """
        Ensures past sales history (e.g. past_total_sold, sales_last_30d) is NEVER substituted
        as physical stock_on_hand when stock_on_hand is missing.
        """
        stock = feature_dict.get("stock_on_hand")
        past_sold = feature_dict.get("past_total_sold") or feature_dict.get("sales_last_30d")

        if stock is None and past_sold is not None and feature_dict.get("inferred_stock_from_sales", False):
            raise CapitalExposureGuardrailError(
                "VIOLATION: Attempted to infer stock_on_hand from sales history (past_total_sold). "
                "Module 05 forbids sales-to-stock substitution."
            )
        return True

    @staticmethod
    def validate_non_causal_text(text: str) -> bool:
        """Enforces non-causal language guardrails."""
        if not text:
            return True
        lower_text = text.lower()
        for phrase in PROHIBITED_CAUSAL_PHRASES:
            if phrase in lower_text:
                raise CapitalExposureGuardrailError(f"Prohibited causal claim phrase detected: '{phrase}'")
        return True


class CapitalExposureOrchestrator:
    """
    Orchestrator for Module 05 Capital Exposure & Aging Architecture.
    Standardizes payload structures and validates contracts.
    """

    MODULE_VERSION = "5.0"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.join(PROJECT_ROOT, 'config', 'capital_exposure_feature_registry.json')

    def build_canonical_payload(
        self,
        sku: str,
        risk_class: str,
        risk_probability: float,
        risk_score: float,
        stock_on_hand: Optional[Union[int, float]] = None,
        unit_cost: Optional[Union[int, float]] = None,
        canonical_sku_id: Optional[str] = None,
        product_name: Optional[str] = None,
        category: Optional[str] = None,
        inventory_receipt_date: Optional[str] = None,
        analysis_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds Canonical Capital Exposure Payload contract for a SKU.
        Calculates Capital Exposure ONLY if observable physical stock and cost are AVAILABLE.
        """
        # Validate data state
        data_status = InventoryEvidenceBoundary.validate_inventory_evidence(stock_on_hand, unit_cost)

        # Capital calculation (Deterministic)
        capital_exposure = None
        if data_status == DataAvailabilityState.AVAILABLE:
            capital_exposure = round(float(stock_on_hand * unit_cost), 2)

        # Aging calculation placeholder contract
        analysis_date_str = analysis_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        aging_days = None
        aging_bucket = None
        if inventory_receipt_date:
            try:
                t_rec = datetime.strptime(inventory_receipt_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                t_ans = datetime.strptime(analysis_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                aging_days = max(0, (t_ans - t_rec).days)
                aging_bucket = self.classify_aging_bucket(aging_days)
            except Exception as e:
                logger.warning("Could not parse dates for SKU %s: %s", sku, e)

        # Exposure Class
        exposure_class = self.classify_exposure_tier(risk_class, capital_exposure, aging_days)

        payload = {
            "sku": sku,
            "canonical_sku_id": canonical_sku_id or f"CSKU_{sku}",
            "product_name": product_name or f"Product {sku}",
            "category": category or "General",
            "risk_assessment": {
                "risk_class": risk_class,
                "risk_probability": round(float(risk_probability), 4),
                "risk_score": round(float(risk_score), 2)
            },
            "inventory_data_status": data_status.value,
            "inventory_metrics": {
                "stock_on_hand": stock_on_hand,
                "unit_cost": unit_cost,
                "capital_exposure": capital_exposure,
                "currency": "VND"
            },
            "aging_metrics": {
                "inventory_receipt_date": inventory_receipt_date,
                "analysis_date": analysis_date_str,
                "aging_days": aging_days,
                "aging_bucket": aging_bucket
            },
            "exposure_assessment": {
                "exposure_class": exposure_class,
                "risk_capital_index": round(capital_exposure * risk_probability, 2) if capital_exposure is not None else None
            },
            "metadata": {
                "module_version": self.MODULE_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        }

        return payload

    @staticmethod
    def classify_aging_bucket(days: int) -> str:
        if days <= 30:
            return "0-30d"
        elif days <= 60:
            return "31-60d"
        elif days <= 90:
            return "61-90d"
        elif days <= 180:
            return "91-180d"
        elif days <= 365:
            return "181-365d"
        else:
            return ">365d"

    @staticmethod
    def classify_exposure_tier(risk_class: str, capital_exposure: Optional[float], aging_days: Optional[int]) -> Optional[str]:
        if capital_exposure is None:
            return "UNCLASSIFIED"
        if risk_class == "CRITICAL" and capital_exposure > 10000000 and (aging_days or 0) > 180:
            return "SEVERE_EXPOSURE"
        if (risk_class in ["CRITICAL", "HIGH_RISK"]) and capital_exposure > 5000000:
            return "HIGH_EXPOSURE"
        if (risk_class in ["HIGH_RISK", "MEDIUM_RISK"]) and capital_exposure > 1000000:
            return "MODERATE_EXPOSURE"
        if risk_class == "MEDIUM_RISK" or capital_exposure <= 1000000:
            return "LOW_EXPOSURE"
        return "MINIMAL_EXPOSURE"

    def save_architecture_spec_report(self, output_path: Optional[str] = None) -> str:
        """Generates reports/capital_exposure_architecture_spec.json."""
        out_file = output_path or os.path.join(PROJECT_ROOT, 'reports', 'capital_exposure_architecture_spec.json')
        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        spec_data = {
            "task": "M5-01",
            "task_name": "Capital Exposure Architecture",
            "module": "MODULE_05",
            "version": self.MODULE_VERSION,
            "architecture_components": [
                "1. Input & Data Readiness Validation (M5-02)",
                "2. Capital Valuation Engine (M5-03)",
                "3. Inventory Aging Engine (M5-04)",
                "4. Risk × Capital Integration Matrix (M5-05)",
                "5. Exposure Classifier (M5-06)",
                "6. Portfolio Aggregation Engine (M5-07)",
                "7. Financial Impact & Opportunity Cost (M5-08)",
                "8. Exposure API & Persistence (M5-09)",
                "9. Exposure Dashboard Integration (M5-10)"
            ],
            "inventory_evidence_rules": {
                "no_inventory_overclaim": True,
                "no_sales_to_stock_substitution": True,
                "no_causal_loss_claim": True,
                "deterministic_calculation_guaranteed": True
            },
            "status": "APPROVED",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(spec_data, f, indent=2, ensure_ascii=False)

        return out_file
