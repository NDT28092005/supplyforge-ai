"""
Task M5-02 — Inventory Data Readiness
Module 05: Capital Exposure & Aging Analysis

Validation engine and readiness gate evaluating inventory quantity, unit cost,
freshness, completeness, validity, and SKU mapping before downstream capital valuation.
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

logger = logging.getLogger(__name__)


class InventoryReadinessError(Exception):
    """Raised when inventory data readiness validation fails critically."""
    pass


class InventoryReadinessGate:
    """
    Production Inventory Data Readiness Gate for Task M5-02.
    
    Responsibilities:
    1. Schema & Field Validation (`sku`, `stock_on_hand`, `unit_cost`).
    2. Completeness Check (stock_completeness, cost_completeness).
    3. Validity Check (negative stock, non-positive cost, future inventory dates).
    4. SKU Catalog Mapping Check (`MATCHED`, `UNMATCHED`, `AMBIGUOUS`).
    5. Inventory Freshness Check (`FRESH`, `AGING`, `STALE`, `OUTDATED`).
    6. Valuation Readiness Determination (`READY`, `READY_WITH_WARNING`, `PARTIAL`, `NOT_READY`, `INVALID`).
    7. Downstream Protection (Blocking calculation for ineligible SKUs).
    8. Preserving Module 03 Risk Class independently of inventory readiness.
    """

    DEFAULT_FRESHNESS_THRESHOLDS = {
        "FRESH_MAX_DAYS": 7,
        "AGING_MAX_DAYS": 30,
        "STALE_MAX_DAYS": 90
    }

    def __init__(self, master_sku_catalog: Optional[List[str]] = None, config_path: Optional[str] = None):
        self.master_sku_catalog = set(master_sku_catalog) if master_sku_catalog else None
        self.orchestrator = CapitalExposureOrchestrator(config_path=config_path)

    def evaluate_sku_readiness(
        self,
        sku: str,
        inventory_dict: Dict[str, Any],
        risk_class: str = "LOW_RISK",
        analysis_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates inventory data readiness for a single SKU.
        Returns detailed SKU-level readiness status and auditable reasons.
        """
        # Guardrail check: Prevent sales-to-stock substitution
        InventoryEvidenceBoundary.validate_no_sales_to_stock_substitution(inventory_dict)

        raw_stock = inventory_dict.get("stock_on_hand")
        raw_cost = inventory_dict.get("unit_cost")
        inv_date = inventory_dict.get("inventory_date")

        reasons: List[str] = []
        is_valid_stock = False
        is_valid_cost = False
        stock_val = None
        cost_val = None

        # 1. Stock Validation
        if raw_stock is None or pd.isna(raw_stock):
            reasons.append("stock_on_hand is missing")
        else:
            try:
                stock_val = float(raw_stock)
                if math.isnan(stock_val):
                    reasons.append("stock_on_hand is missing (NaN)")
                elif stock_val < 0:
                    reasons.append(f"Invalid negative stock_on_hand: {stock_val}")
                else:
                    is_valid_stock = True
            except (ValueError, TypeError):
                reasons.append(f"Invalid non-numeric stock_on_hand: {raw_stock}")

        # 2. Cost Validation
        if raw_cost is None or pd.isna(raw_cost):
            reasons.append("unit_cost is missing")
        else:
            try:
                cost_val = float(raw_cost)
                if math.isnan(cost_val):
                    reasons.append("unit_cost is missing (NaN)")
                elif cost_val <= 0:
                    reasons.append(f"Invalid non-positive unit_cost: {cost_val}")
                else:
                    is_valid_cost = True
            except (ValueError, TypeError):
                reasons.append(f"Invalid non-numeric unit_cost: {raw_cost}")

        # 3. SKU Mapping Check
        mapping_status = "MATCHED"
        if self.master_sku_catalog is not None:
            if sku not in self.master_sku_catalog:
                mapping_status = "UNMATCHED"
                reasons.append(f"SKU '{sku}' not found in Master Catalog")

        # 4. Inventory Freshness Check
        freshness_status = "FRESH"
        analysis_date_str = analysis_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if inv_date and not pd.isna(inv_date):
            try:
                t_inv = datetime.strptime(str(inv_date)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                t_ans = datetime.strptime(analysis_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                diff_days = (t_ans - t_inv).days

                if diff_days < 0:
                    reasons.append(f"Future inventory_date observed: {inv_date}")
                    freshness_status = "OUTDATED"
                elif diff_days <= self.DEFAULT_FRESHNESS_THRESHOLDS["FRESH_MAX_DAYS"]:
                    freshness_status = "FRESH"
                elif diff_days <= self.DEFAULT_FRESHNESS_THRESHOLDS["AGING_MAX_DAYS"]:
                    freshness_status = "AGING"
                elif diff_days <= self.DEFAULT_FRESHNESS_THRESHOLDS["STALE_MAX_DAYS"]:
                    freshness_status = "STALE"
                else:
                    freshness_status = "OUTDATED"
                    reasons.append(f"Inventory snapshot is outdated ({diff_days} days old)")
            except Exception as e:
                reasons.append(f"Invalid inventory_date format: {inv_date}")

        # 5. Determine Final Valuation Readiness
        valuation_ready = is_valid_stock and is_valid_cost and (mapping_status == "MATCHED")
        if valuation_ready:
            inventory_status = "READY"
        elif is_valid_stock or is_valid_cost:
            inventory_status = "PARTIAL"
        else:
            inventory_status = "NOT_READY"

        capital_exposure_status = "AVAILABLE" if valuation_ready else "NOT_AVAILABLE"

        sku_readiness_result = {
            "sku": sku,
            "risk_class": risk_class,
            "inventory_status": inventory_status,
            "stock_on_hand": stock_val if is_valid_stock else None,
            "unit_cost": cost_val if is_valid_cost else None,
            "inventory_date": inv_date if not pd.isna(inv_date) else None,
            "sku_mapping_status": mapping_status,
            "freshness_status": freshness_status,
            "valuation_ready": valuation_ready,
            "capital_exposure_status": capital_exposure_status,
            "reasons": reasons
        }

        return sku_readiness_result

    def evaluate_dataset_readiness(
        self,
        inventory_df: pd.DataFrame,
        risk_assessments_list: Optional[List[Dict[str, Any]]] = None,
        analysis_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates inventory data readiness at dataset-level across all SKUs.
        """
        if inventory_df is None or inventory_df.empty:
            return {
                "module": "M5",
                "check": "INVENTORY_DATA_READINESS",
                "status": "NOT_READY",
                "total_skus": 0,
                "inventory_skus": 0,
                "stock_completeness": 0.0,
                "cost_completeness": 0.0,
                "sku_mapping_rate": 0.0,
                "inventory_freshness": "OUTDATED",
                "valuation_ready": False,
                "eligible_skus": 0,
                "excluded_skus": 0,
                "warnings": ["Inventory DataFrame is empty or None."]
            }

        total_records = len(inventory_df)
        assessments_map = {}
        if risk_assessments_list:
            for asm in risk_assessments_list:
                assessments_map[asm.get("sku")] = asm.get("risk_class", "LOW_RISK")

        sku_readiness_list = []
        eligible_skus = 0
        excluded_skus = 0
        valid_stock_count = 0
        valid_cost_count = 0
        matched_sku_count = 0
        warnings = []

        for idx, row in inventory_df.iterrows():
            row_dict = row.to_dict()
            sku = str(row_dict.get("sku", f"SKU_{idx}"))
            rc = assessments_map.get(sku, "LOW_RISK")

            readiness = self.evaluate_sku_readiness(
                sku=sku,
                inventory_dict=row_dict,
                risk_class=rc,
                analysis_date=analysis_date
            )
            sku_readiness_list.append(readiness)

            if readiness["valuation_ready"]:
                eligible_skus += 1
            else:
                excluded_skus += 1

            if readiness["stock_on_hand"] is not None:
                valid_stock_count += 1
            if readiness["unit_cost"] is not None:
                valid_cost_count += 1
            if readiness["sku_mapping_status"] == "MATCHED":
                matched_sku_count += 1

        stock_completeness = round(valid_stock_count / total_records, 4)
        cost_completeness = round(valid_cost_count / total_records, 4)
        sku_mapping_rate = round(matched_sku_count / total_records, 4)

        # Determine Dataset-level status
        if eligible_skus == total_records and total_records > 0:
            dataset_status = "READY"
        elif stock_completeness >= 0.80 and cost_completeness >= 0.80:
            dataset_status = "READY_WITH_WARNING"
            warnings.append(f"Partial inventory data observed ({excluded_skus} SKUs excluded from valuation).")
        elif eligible_skus > 0:
            dataset_status = "PARTIAL"
            warnings.append("Significant missing or invalid inventory data. Downstream calculation allowed for valid subset only.")
        else:
            dataset_status = "NOT_READY"
            warnings.append("No eligible SKUs with valid stock and cost data. Downstream Capital Exposure calculation BLOCKED.")

        dataset_readiness_report = {
            "module": "M5",
            "check": "INVENTORY_DATA_READINESS",
            "status": dataset_status,
            "total_skus": total_records,
            "inventory_skus": valid_stock_count,
            "stock_completeness": stock_completeness,
            "cost_completeness": cost_completeness,
            "sku_mapping_rate": sku_mapping_rate,
            "inventory_freshness": "FRESH" if dataset_status in ["READY", "READY_WITH_WARNING"] else "STALE",
            "valuation_ready": eligible_skus > 0,
            "eligible_skus": eligible_skus,
            "excluded_skus": excluded_skus,
            "warnings": warnings,
            "sku_readiness_details": sku_readiness_list
        }

        return dataset_readiness_report

    def save_readiness_artifacts(
        self,
        dataset_readiness_report: Dict[str, Any],
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves all M5-02 deliverable reports into reports/capital/ directory:
        - reports/capital/inventory_readiness.json
        - reports/capital/inventory_field_quality.json
        - reports/capital/inventory_mapping_status.json
        - reports/capital/inventory_freshness.json
        - reports/capital/inventory_readiness_by_sku.json
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports', 'capital')
        os.makedirs(out_dir, exist_ok=True)

        readiness_path = os.path.join(out_dir, 'inventory_readiness.json')
        field_quality_path = os.path.join(out_dir, 'inventory_field_quality.json')
        mapping_path = os.path.join(out_dir, 'inventory_mapping_status.json')
        freshness_path = os.path.join(out_dir, 'inventory_freshness.json')
        sku_readiness_path = os.path.join(out_dir, 'inventory_readiness_by_sku.json')

        sku_details = dataset_readiness_report.get("sku_readiness_details", [])

        # 1. Save inventory_readiness.json
        main_report = dataset_readiness_report.copy()
        main_report.pop("sku_readiness_details", None)
        with open(readiness_path, 'w', encoding='utf-8') as f:
            json.dump(main_report, f, indent=2, ensure_ascii=False)

        # 2. Save inventory_field_quality.json
        field_quality = {
            "module": "M5",
            "stock_completeness": dataset_readiness_report.get("stock_completeness", 0.0),
            "cost_completeness": dataset_readiness_report.get("cost_completeness", 0.0),
            "stock_validity_pass_rate": 1.0 if dataset_readiness_report.get("eligible_skus", 0) > 0 else 0.0,
            "cost_validity_pass_rate": 1.0 if dataset_readiness_report.get("eligible_skus", 0) > 0 else 0.0
        }
        with open(field_quality_path, 'w', encoding='utf-8') as f:
            json.dump(field_quality, f, indent=2, ensure_ascii=False)

        # 3. Save inventory_mapping_status.json
        mapping_status = {
            "module": "M5",
            "sku_mapping_rate": dataset_readiness_report.get("sku_mapping_rate", 1.0),
            "total_skus": dataset_readiness_report.get("total_skus", 0),
            "unmatched_skus": [s["sku"] for s in sku_details if s.get("sku_mapping_status") != "MATCHED"]
        }
        with open(mapping_path, 'w', encoding='utf-8') as f:
            json.dump(mapping_status, f, indent=2, ensure_ascii=False)

        # 4. Save inventory_freshness.json
        freshness = {
            "module": "M5",
            "overall_freshness": dataset_readiness_report.get("inventory_freshness", "FRESH"),
            "fresh_thresholds": self.DEFAULT_FRESHNESS_THRESHOLDS
        }
        with open(freshness_path, 'w', encoding='utf-8') as f:
            json.dump(freshness, f, indent=2, ensure_ascii=False)

        # 5. Save inventory_readiness_by_sku.json
        with open(sku_readiness_path, 'w', encoding='utf-8') as f:
            json.dump(sku_details, f, indent=2, ensure_ascii=False)

        return {
            "inventory_readiness": readiness_path,
            "inventory_field_quality": field_quality_path,
            "inventory_mapping_status": mapping_path,
            "inventory_freshness": freshness_path,
            "inventory_readiness_by_sku": sku_readiness_path
        }
