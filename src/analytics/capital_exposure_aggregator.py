"""
Task M5-07 — Capital Exposure Aggregation
Module 05: Capital Exposure & Aging Analysis

Aggregates SKU-level valuation, aging, and exposure metrics into portfolio-level KPIs,
risk breakdowns, aging risk breakdowns, priority distributions, 2D Risk x Aging matrix,
concentration indicators, and mathematical reconciliation validations.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from src.analytics.capital_exposure_architecture import (
    CapitalExposureOrchestrator,
    InventoryEvidenceBoundary,
    CapitalExposureGuardrailError,
    PROJECT_ROOT
)
from src.analytics.aging_risk_classifier import AgingRiskClassifier

logger = logging.getLogger(__name__)


class CapitalExposureAggregationError(Exception):
    """Raised when capital exposure aggregation or reconciliation fails."""
    pass


class CapitalExposureAggregator:
    """
    Production Capital Exposure Aggregator for Task M5-07.
    
    Responsibilities:
    1. Total Capital & Risk-Weighted Exposure Aggregation.
    2. Multi-Dimensional Portfolio Breakdowns:
       - Slow-Moving Risk Level Breakdown (CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK)
       - Aging Risk Level Breakdown (FRESH, AGING, AT_RISK, CRITICAL_AGING)
       - Aging Priority Breakdown (P1, P2, P3, P4)
    3. Cross-Dimensional 2D Matrix (Slow-Moving Risk x Aging Risk Level).
    4. Capital Concentration Indicators (Top-10 Exposure & Top-10 Exposure Share).
    5. Mathematical Reconciliation Verification (SUM(groups) == Total).
    6. Deliverable Artifact Generation (capital_exposure_summary.json, matrix, top_skus, validation).
    """

    AGGREGATOR_VERSION = "5.0"

    def __init__(self, config_path: Optional[str] = None):
        self.classifier = AgingRiskClassifier(config_path=config_path)

    def aggregate_portfolio(
        self,
        assessment_records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Executes portfolio-level capital exposure aggregation across all dimensions.
        """
        if not assessment_records:
            raise CapitalExposureAggregationError("Assessment records list is empty or None.")

        total_skus = len(assessment_records)
        total_inv_val = sum(float(r.get("capital_exposure") or r.get("inventory_value") or 0.0) for r in assessment_records)
        total_rwce = sum(float(r.get("risk_weighted_exposure") or 0.0) for r in assessment_records)
        total_pae = sum(float(r.get("capital_exposure", 0.0)) * float(r.get("risk_probability", 0.0)) for r in assessment_records)

        # 1. Slow-Moving Risk Level Distribution
        risk_dist = self._aggregate_by_key(
            records=assessment_records,
            key_name="slow_moving_risk_class",
            keys_order=["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"],
            total_inv_val=total_inv_val,
            total_rwce=total_rwce
        )

        # 2. Aging Risk Level Distribution
        aging_dist = self._aggregate_by_key(
            records=assessment_records,
            key_name="aging_risk_level",
            keys_order=["FRESH", "AGING", "AT_RISK", "CRITICAL_AGING"],
            total_inv_val=total_inv_val,
            total_rwce=total_rwce
        )

        # 3. Priority Distribution
        prio_dist = self._aggregate_by_key(
            records=assessment_records,
            key_name="aging_priority",
            keys_order=["P1", "P2", "P3", "P4"],
            total_inv_val=total_inv_val,
            total_rwce=total_rwce
        )

        # 4. Cross-Dimensional Risk x Aging Matrix
        matrix_cells = self._build_risk_aging_matrix_cells(assessment_records)

        # 5. Top-N Exposure SKUs & Concentration
        sorted_records = sorted(
            assessment_records,
            key=lambda x: (float(x.get("risk_weighted_exposure", 0.0)), float(x.get("capital_exposure", 0.0))),
            reverse=True
        )

        top_skus = []
        for rec in sorted_records[:10]:
            top_skus.append({
                "sku": rec["sku"],
                "canonical_sku_id": rec.get("canonical_sku_id", f"CSKU_{rec['sku']}"),
                "product_name": rec.get("product_name", f"Product {rec['sku']}"),
                "inventory_value": round(float(rec.get("capital_exposure") or 0.0), 2),
                "risk_weighted_exposure": round(float(rec.get("risk_weighted_exposure") or 0.0), 2),
                "slow_moving_risk": rec.get("slow_moving_risk_class"),
                "aging_risk": rec.get("aging_risk_level"),
                "priority": rec.get("aging_priority")
            })

        top_10_rwce = sum(s["risk_weighted_exposure"] for s in top_skus)
        top_10_share = round(top_10_rwce / total_rwce, 4) if total_rwce > 0 else 0.0

        summary_payload = {
            "task": "M5-07",
            "module_version": self.AGGREGATOR_VERSION,
            "currency": "VND",
            "summary": {
                "sku_count": total_skus,
                "total_inventory_value": round(total_inv_val, 2),
                "total_risk_weighted_exposure": round(total_rwce, 2),
                "total_probability_adjusted_exposure": round(total_pae, 2)
            },
            "risk_distribution": risk_dist,
            "aging_distribution": aging_dist,
            "priority_distribution": prio_dist,
            "risk_aging_matrix": matrix_cells,
            "top_exposure_skus": top_skus,
            "exposure_concentration": {
                "top_10_exposure": round(top_10_rwce, 2),
                "top_10_exposure_share": top_10_share
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        # Execute Reconciliation Verification
        reconciliation_status = self.run_reconciliation_checks(summary_payload)
        summary_payload["reconciliation_status"] = reconciliation_status

        return summary_payload

    def _aggregate_by_key(
        self,
        records: List[Dict[str, Any]],
        key_name: str,
        keys_order: List[str],
        total_inv_val: float,
        total_rwce: float
    ) -> List[Dict[str, Any]]:
        """Helper to aggregate SKU records by a categorical dimension key."""
        agg_map = {
            k: {"group": k, "sku_count": 0, "inventory_value": 0.0, "risk_weighted_exposure": 0.0}
            for k in keys_order
        }

        for rec in records:
            k_val = rec.get(key_name, "UNKNOWN")
            inv_val = float(rec.get("capital_exposure") or rec.get("inventory_value") or 0.0)
            rwce = float(rec.get("risk_weighted_exposure") or 0.0)

            if k_val not in agg_map:
                agg_map[k_val] = {"group": k_val, "sku_count": 0, "inventory_value": 0.0, "risk_weighted_exposure": 0.0}

            agg_map[k_val]["sku_count"] += 1
            agg_map[k_val]["inventory_value"] += inv_val
            agg_map[k_val]["risk_weighted_exposure"] += rwce

        results = []
        for k in keys_order:
            if k in agg_map:
                item = agg_map[k]
                item["inventory_value"] = round(item["inventory_value"], 2)
                item["risk_weighted_exposure"] = round(item["risk_weighted_exposure"], 2)
                item["exposure_share"] = round(item["risk_weighted_exposure"] / total_rwce, 4) if total_rwce > 0 else 0.0
                results.append(item)
        return results

    def _build_risk_aging_matrix_cells(
        self,
        records: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Helper to build 2D Risk Class x Aging Risk Level matrix cells."""
        risk_classes = ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]
        aging_levels = ["FRESH", "AGING", "AT_RISK", "CRITICAL_AGING"]

        matrix_map = {
            (rc, al): {"slow_moving_risk": rc, "aging_risk": al, "sku_count": 0, "inventory_value": 0.0, "risk_weighted_exposure": 0.0}
            for rc in risk_classes for al in aging_levels
        }

        for rec in records:
            rc = rec.get("slow_moving_risk_class", "LOW_RISK")
            al = rec.get("aging_risk_level", "FRESH")
            inv_val = float(rec.get("capital_exposure") or rec.get("inventory_value") or 0.0)
            rwce = float(rec.get("risk_weighted_exposure") or 0.0)

            key = (rc, al)
            if key in matrix_map:
                matrix_map[key]["sku_count"] += 1
                matrix_map[key]["inventory_value"] += inv_val
                matrix_map[key]["risk_weighted_exposure"] += rwce

        cells = []
        for rc in risk_classes:
            for al in aging_levels:
                cell = matrix_map[(rc, al)]
                cell["inventory_value"] = round(cell["inventory_value"], 2)
                cell["risk_weighted_exposure"] = round(cell["risk_weighted_exposure"], 2)
                cells.append(cell)
        return cells

    def run_reconciliation_checks(self, summary_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes mathematical reconciliation verification ensuring SUM(groups) == Total.
        """
        summary_tot_inv = summary_payload["summary"]["total_inventory_value"]
        summary_tot_rwce = summary_payload["summary"]["total_risk_weighted_exposure"]
        tot_skus = summary_payload["summary"]["sku_count"]

        # Risk breakdown check
        risk_sum_skus = sum(r["sku_count"] for r in summary_payload["risk_distribution"])
        risk_sum_rwce = round(sum(r["risk_weighted_exposure"] for r in summary_payload["risk_distribution"]), 2)

        # Aging breakdown check
        aging_sum_skus = sum(r["sku_count"] for r in summary_payload["aging_distribution"])
        aging_sum_rwce = round(sum(r["risk_weighted_exposure"] for r in summary_payload["aging_distribution"]), 2)

        # Priority breakdown check
        prio_sum_skus = sum(r["sku_count"] for r in summary_payload["priority_distribution"])
        prio_sum_rwce = round(sum(r["risk_weighted_exposure"] for r in summary_payload["priority_distribution"]), 2)

        risk_reconciled = (risk_sum_skus == tot_skus) and abs(risk_sum_rwce - summary_tot_rwce) < 1.0
        aging_reconciled = (aging_sum_skus == tot_skus) and abs(aging_sum_rwce - summary_tot_rwce) < 1.0
        prio_reconciled = (prio_sum_skus == tot_skus) and abs(prio_sum_rwce - summary_tot_rwce) < 1.0

        all_passed = risk_reconciled and aging_reconciled and prio_reconciled

        return {
            "all_reconciled": all_passed,
            "risk_reconciled": risk_reconciled,
            "aging_reconciled": aging_reconciled,
            "priority_reconciled": prio_reconciled,
            "diff_risk_rwce": round(abs(risk_sum_rwce - summary_tot_rwce), 2),
            "diff_aging_rwce": round(abs(aging_sum_rwce - summary_tot_rwce), 2)
        }

    def save_aggregation_artifacts(
        self,
        summary_payload: Dict[str, Any],
        output_dir: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Saves M5-07 deliverable artifacts into reports/capital/ directory:
        - reports/capital/capital_exposure_summary.json
        - reports/capital/capital_exposure_by_risk.json
        - reports/capital/capital_exposure_by_aging.json
        - reports/capital/risk_aging_exposure_matrix.json
        - reports/capital/top_exposure_skus.json
        - reports/capital/capital_exposure_aggregation_validation.json
        """
        out_dir = output_dir or os.path.join(PROJECT_ROOT, 'reports', 'capital')
        os.makedirs(out_dir, exist_ok=True)

        summary_path = os.path.join(out_dir, 'capital_exposure_summary.json')
        by_risk_path = os.path.join(out_dir, 'capital_exposure_by_risk.json')
        by_aging_path = os.path.join(out_dir, 'capital_exposure_by_aging.json')
        matrix_path = os.path.join(out_dir, 'risk_aging_exposure_matrix.json')
        top_skus_path = os.path.join(out_dir, 'top_exposure_skus.json')
        val_report_path = os.path.join(out_dir, 'capital_exposure_aggregation_validation.json')

        # 1. Save capital_exposure_summary.json
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # 2. Save capital_exposure_by_risk.json
        with open(by_risk_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload.get("risk_distribution", []), f, indent=2, ensure_ascii=False)

        # 3. Save capital_exposure_by_aging.json
        with open(by_aging_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload.get("aging_distribution", []), f, indent=2, ensure_ascii=False)

        # 4. Save risk_aging_exposure_matrix.json
        with open(matrix_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload.get("risk_aging_matrix", []), f, indent=2, ensure_ascii=False)

        # 5. Save top_exposure_skus.json
        with open(top_skus_path, 'w', encoding='utf-8') as f:
            json.dump(summary_payload.get("top_exposure_skus", []), f, indent=2, ensure_ascii=False)

        # 6. Save capital_exposure_aggregation_validation.json
        rec_status = summary_payload.get("reconciliation_status", {})
        val_report = {
            "task": "M5-07",
            "task_name": "Capital Exposure Aggregation Validation",
            "total_skus": summary_payload["summary"]["sku_count"],
            "total_inventory_value": summary_payload["summary"]["total_inventory_value"],
            "total_risk_weighted_exposure": summary_payload["summary"]["total_risk_weighted_exposure"],
            "reconciliation_checks": rec_status,
            "status": "PASSED" if rec_status.get("all_reconciled", False) else "FAILED",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        with open(val_report_path, 'w', encoding='utf-8') as f:
            json.dump(val_report, f, indent=2, ensure_ascii=False)

        return {
            "capital_exposure_summary": summary_path,
            "capital_exposure_by_risk": by_risk_path,
            "capital_exposure_by_aging": by_aging_path,
            "risk_aging_exposure_matrix": matrix_path,
            "top_exposure_skus": top_skus_path,
            "capital_exposure_aggregation_validation": val_report_path
        }
