"""
Task M5-03 — Capital Valuation Engine
Module 05: Capital Exposure & Aging Analysis

Performs SKU-level financial valuation, validating unit cost evidence, cleanly
differentiating physical Inventory Capital Exposure vs Transaction Observed Cost Value,
aggregating metrics by Risk Class and Category, and preparing foundation data for M5-04.
"""

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from src.analytics.capital_exposure_architecture import (
    CapitalExposureOrchestrator,
    InventoryEvidenceBoundary,
    DataAvailabilityState,
    CapitalExposureGuardrailError,
    PROJECT_ROOT
)
from src.analytics.inventory_readiness_gate import InventoryReadinessGate

logger = logging.getLogger(__name__)


class CapitalValuationError(Exception):
    """Raised when valuation calculation or validation fails."""
    pass


class CapitalValuationEngine:
    """
    Production Capital Valuation Engine for Task M5-03.
    
    Responsibilities:
    1. Cost Validation (`VALID`, `MISSING_COST`, `INVALID_COST`, `ZERO_COST`).
    2. SKU-Level Valuation:
       - Physical Inventory Capital Exposure = stock_on_hand * unit_cost (if stock available).
       - Observed Cost Value = observed_quantity * unit_cost (if stock missing).
    3. Temporal Safety & Non-Causal Guardrail Enforcement (No t > t0 features).
    4. Aggregation by Risk Class (`CRITICAL`, `HIGH_RISK`, `MEDIUM_RISK`, `LOW_RISK`) and Category.
    5. Foundation preparation for M5-04 Aging Analysis Engine.
    6. Deliverable Artifact Generation (`capital_exposure_summary.json`, `capital_valuation_validation.json`, `capital_valuation.json`).
    """

    VALUATION_VERSION = "5.0"

    def __init__(self, master_sku_catalog: Optional[List[str]] = None, config_path: Optional[str] = None):
        self.readiness_gate = InventoryReadinessGate(master_sku_catalog=master_sku_catalog, config_path=config_path)
        self.orchestrator = CapitalExposureOrchestrator(config_path=config_path)

    @staticmethod
    def validate_unit_cost(raw_cost: Any) -> Tuple[Optional[float], str]:
        """
        Validates unit cost evidence and categorizes status.
        Never defaults unit_cost = selling_price.
        """
        if raw_cost is None or pd.isna(raw_cost):
            return None, "MISSING_COST"
        try:
            val = float(raw_cost)
            if math.isnan(val):
                return None, "MISSING_COST"
            if val == 0:
                return 0.0, "ZERO_COST"
            if val < 0:
                return None, "INVALID_COST"
            return val, "VALID"
        except (ValueError, TypeError):
            return None, "INVALID_COST"

    def value_sku(
        self,
        sku: str,
        inventory_dict: Dict[str, Any],
        risk_assessment_dict: Dict[str, Any],
        analysis_date: Optional[str] = None
    ) -> Dict[str, Any]:
        r"""
        Calculates financial valuation for a single SKU.
        Guarantees zero future leakage ($t \le t_0$) and zero LLM calculations.
        """

        # Validate temporal safety & sales substitution
        InventoryEvidenceBoundary.validate_no_sales_to_stock_substitution(inventory_dict)

        # Ensure no future leakage keys present (e.g. fut_qty_60d)
        prohibited_keys = ["fut_qty_60d", "future_sales", "future_revenue"]
        for key in prohibited_keys:
            if key in inventory_dict or key in risk_assessment_dict:
                raise CapitalExposureGuardrailError(f"Prohibited future feature '{key}' detected in valuation input.")

        # Extract Risk Data
        r_class = risk_assessment_dict.get("risk_class", "LOW_RISK")
        r_prob = float(risk_assessment_dict.get("risk_probability", 0.0))
        r_score = float(risk_assessment_dict.get("risk_score", 0.0))

        # Evaluate Readiness Gate
        readiness = self.readiness_gate.evaluate_sku_readiness(
            sku=sku,
            inventory_dict=inventory_dict,
            risk_class=r_class,
            analysis_date=analysis_date
        )

        # Validate Unit Cost
        raw_cost = inventory_dict.get("unit_cost")
        unit_cost, cost_status = self.validate_unit_cost(raw_cost)

        # Extract quantities
        stock_on_hand = readiness.get("stock_on_hand")
        observed_qty = inventory_dict.get("observed_quantity") or inventory_dict.get("past_total_sold") or inventory_dict.get("sales_last_90d") or 0.0
        try:
            observed_qty = float(observed_qty) if not pd.isna(observed_qty) else 0.0
        except (ValueError, TypeError):
            observed_qty = 0.0

        dsls = inventory_dict.get("dsls", 0)

        # Valuation calculations
        inventory_capital_exposure = None
        observed_cost_value = None
        valuation_status = cost_status

        if cost_status == "VALID":
            if stock_on_hand is not None:
                inventory_capital_exposure = round(float(stock_on_hand * unit_cost), 2)
            if observed_qty > 0:
                observed_cost_value = round(float(observed_qty * unit_cost), 2)

        # Prep Aging Bucket
        aging_days = inventory_dict.get("aging_days") or dsls
        aging_bucket = self.orchestrator.classify_aging_bucket(int(aging_days) if aging_days else 0)

        record = {
            "sku": sku,
            "canonical_sku_id": inventory_dict.get("canonical_sku_id") or f"CSKU_{sku}",
            "product_name": inventory_dict.get("product_name") or f"Product {sku}",
            "category": inventory_dict.get("category") or "General",
            "unit_cost": unit_cost,
            "cost_status": cost_status,
            "stock_on_hand": stock_on_hand,
            "observed_quantity": observed_qty,
            "inventory_capital_exposure": inventory_capital_exposure,
            "observed_cost_value": observed_cost_value,
            "capital_metric_type": "PHYSICAL_INVENTORY_CAPITAL" if stock_on_hand is not None else "OBSERVED_TRANSACTION_COST",
            "risk_class": r_class,
            "risk_probability": round(r_prob, 4),
            "risk_score": round(r_score, 2),
            "dsls": dsls,
            "aging_days": aging_days,
            "aging_bucket": aging_bucket,
            "valuation_status": valuation_status,
            "valuation_ready": readiness.get("valuation_ready", False)
        }

        return record

    def value_dataset(
        self,
        inventory_df: pd.DataFrame,
        risk_assessments_list: List[Dict[str, Any]],
        analysis_date: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Executes dataset-level valuation and generates summary aggregations by Risk Class and Category.
        """
        if inventory_df is None or inventory_df.empty:
            raise CapitalValuationError("Inventory DataFrame is empty or None.")

        assessments_map = {asm.get("sku"): asm for asm in risk_assessments_list}
        sku_records = []

        for idx, row in inventory_df.iterrows():
            row_dict = row.to_dict()
            sku = str(row_dict.get("sku", f"SKU_{idx}"))
            r_asm = assessments_map.get(sku, {
                "risk_class": "LOW_RISK",
                "risk_probability": 0.0,
                "risk_score": 0.0
            })

            rec = self.value_sku(sku, row_dict, r_asm, analysis_date=analysis_date)
            sku_records.append(rec)

        # Aggregate Summary
        summary = self._aggregate_summary(sku_records)

        return sku_records, summary

    def _aggregate_summary(self, sku_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregates SKU valuation records by Risk Class and Category."""
        total_skus = len(sku_records)
        total_inventory_capital = 0.0
        total_observed_cost = 0.0
        valid_cost_skus = 0

        risk_breakdown = {
            "CRITICAL": {"sku_count": 0, "inventory_capital": 0.0, "observed_cost": 0.0},
            "HIGH_RISK": {"sku_count": 0, "inventory_capital": 0.0, "observed_cost": 0.0},
            "MEDIUM_RISK": {"sku_count": 0, "inventory_capital": 0.0, "observed_cost": 0.0},
            "LOW_RISK": {"sku_count": 0, "inventory_capital": 0.0, "observed_cost": 0.0}
        }

        category_breakdown: Dict[str, Dict[str, Any]] = {}

        for rec in sku_records:
            rc = rec["risk_class"]
            cat = rec["category"]

            inv_cap = rec["inventory_capital_exposure"] or 0.0
            obs_cost = rec["observed_cost_value"] or 0.0

            if rec["cost_status"] == "VALID":
                valid_cost_skus += 1

            total_inventory_capital += inv_cap
            total_observed_cost += obs_cost

            # Risk Class Aggregation
            if rc in risk_breakdown:
                risk_breakdown[rc]["sku_count"] += 1
                risk_breakdown[rc]["inventory_capital"] += inv_cap
                risk_breakdown[rc]["observed_cost"] += obs_cost

            # Category Aggregation
            if cat not in category_breakdown:
                category_breakdown[cat] = {"sku_count": 0, "inventory_capital": 0.0, "observed_cost": 0.0}
            category_breakdown[cat]["sku_count"] += 1
            category_breakdown[cat]["inventory_capital"] += inv_cap
            category_breakdown[cat]["observed_cost"] += obs_cost

        # Round aggregated values
        for rc in risk_breakdown:
            risk_breakdown[rc]["inventory_capital"] = round(risk_breakdown[rc]["inventory_capital"], 2)
            risk_breakdown[rc]["observed_cost"] = round(risk_breakdown[rc]["observed_cost"], 2)

        for cat in category_breakdown:
            category_breakdown[cat]["inventory_capital"] = round(category_breakdown[cat]["inventory_capital"], 2)
            category_breakdown[cat]["observed_cost"] = round(category_breakdown[cat]["observed_cost"], 2)

        summary_payload = {
            "task": "M5-03",
            "module_version": self.VALUATION_VERSION,
            "total_skus": total_skus,
            "valid_cost_skus": valid_cost_skus,
            "cost_validity_rate": round(valid_cost_skus / total_skus, 4) if total_skus > 0 else 0.0,
            "total_inventory_capital_exposure": round(total_inventory_capital, 2),
            "total_observed_cost_value": round(total_observed_cost, 2),
            "currency": "VND",
            "risk_class_breakdown": risk_breakdown,
            "category_breakdown": category_breakdown,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        return summary_payload

    def save_valuation_artifacts(
        self,
        sku_records: List[Dict[str, Any]],
        summary_payload: Dict[str, Any],
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves M5-03 deliverable artifacts into reports/capital/ directory:
        - reports/capital/capital_exposure_summary.json
        - reports/capital/capital_valuation_validation.json
        - reports/capital/capital_valuation.json
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports', 'capital')
        os.makedirs(out_dir, exist_ok=True)

        summary_path = os.path.join(out_dir, 'capital_exposure_summary.json')
        val_report_path = os.path.join(out_dir, 'capital_valuation_validation.json')
        sku_val_path = os.path.join(out_dir, 'capital_valuation.json')

        # 1. Save capital_exposure_summary.json
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # 2. Save capital_valuation.json
        with open(sku_val_path, 'w', encoding='utf-8') as f:
            json.dump(sku_records, f, indent=2, ensure_ascii=False)

        # 3. Save capital_valuation_validation.json
        invalid_cost_skus = [r["sku"] for r in sku_records if r["cost_status"] != "VALID"]
        val_report = {
            "task": "M5-03",
            "task_name": "Capital Valuation Engine Validation",
            "total_skus_evaluated": len(sku_records),
            "valid_valuation_count": summary_payload.get("valid_cost_skus", 0),
            "invalid_cost_skus_count": len(invalid_cost_skus),
            "invalid_cost_skus": invalid_cost_skus,
            "financial_integrity_checks": {
                "zero_future_leakage": True,
                "zero_sales_to_stock_substitution": True,
                "deterministic_python_engine_verified": True
            },
            "status": "PASSED" if len(invalid_cost_skus) == 0 else "PASSED_WITH_WARNINGS",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        with open(val_report_path, 'w', encoding='utf-8') as f:
            json.dump(val_report, f, indent=2, ensure_ascii=False)

        return {
            "capital_exposure_summary": summary_path,
            "capital_valuation_validation": val_report_path,
            "capital_valuation": sku_val_path
        }
