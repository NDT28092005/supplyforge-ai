#!/usr/bin/env python3
"""Reproducible temporal benchmark for the operational ``orders_full`` source.

This runner is deliberately independent from the Online Retail research workflow.
It reads only order fields required to construct fulfilled item demand; buyer PII,
``updatedAt``, and all other post-cutoff fields are never loaded as model features.

The generated model is an evaluation candidate, not an automatically deployed model.
Production promotion requires a runtime feature-contract migration and review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.base import clone
from sklearn.calibration import calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    cohen_kappa_score,
    f1_score,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from supplyforge.ml.temporal_operating_mode import (
    OPERATING_MODE_POLICY_PATH,
    load_operating_mode_policy,
    select_operating_mode_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = PROJECT_ROOT / "config" / "temporal_demand_risk_feature_contract.json"
GROUND_TRUTH_CONTRACT_PATH = PROJECT_ROOT / "config" / "temporal_demand_risk_ground_truth_contract.json"
RISK_CLASSES = ("CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK")
RISK_TO_CODE = {label: code for code, label in enumerate(RISK_CLASSES)}
VALID_STATUSES = {"COMPLETED", "SHIPPED"}
HORIZON_DAYS = 60
HISTORY_DAYS = 90
CUTOFF_FREQUENCY_DAYS = 28
DISCRIMINABILITY_FEATURES = (
    "sales_qty_30d",
    "sales_qty_60d",
    "sales_velocity_90d",
    "zero_rate_90d",
    "dsls",
    "adi_90d",
    "cv2_90d",
    "lifetime_velocity",
)


def load_feature_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    """Load and validate the serving contract shared by training and runtime."""
    if not path.is_file():
        raise FileNotFoundError(f"Temporal feature contract not found: {path}")
    contract = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "class_order", "feature_columns", "label_definition", "source_policy"}
    missing = sorted(required.difference(contract))
    if missing:
        raise ValueError(f"Temporal feature contract is missing keys: {missing}")
    if tuple(contract["class_order"]) != RISK_CLASSES:
        raise ValueError("Temporal feature contract class_order does not match the benchmark label order")
    if int(contract["label_definition"].get("horizon_days", -1)) != HORIZON_DAYS:
        raise ValueError("Temporal feature contract horizon does not match the benchmark horizon")
    if set(contract["source_policy"].get("accepted_order_statuses", [])) != VALID_STATUSES:
        raise ValueError("Temporal feature contract accepted statuses do not match the source filter")
    if not contract["feature_columns"]:
        raise ValueError("Temporal feature contract has no feature_columns")
    prohibited = set(contract["source_policy"].get("pii_columns_prohibited", []))
    if prohibited.intersection(contract["feature_columns"]):
        raise ValueError("Temporal feature contract includes prohibited PII columns")
    return contract


def load_ground_truth_contract(path: Path = GROUND_TRUTH_CONTRACT_PATH) -> dict[str, Any]:
    """Load the independently versioned policy used to construct target labels.

    It is deliberately separate from the runtime feature contract: validating a
    target policy must not silently invalidate a serving feature schema.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground-truth contract not found: {path}")
    contract = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "task",
        "decision_protocol",
        "selected_strategy",
        "threshold_sensitivity_policies",
        "alternative_strategy",
    }
    missing = sorted(required.difference(contract))
    if missing:
        raise ValueError(f"Ground-truth contract is missing keys: {missing}")
    if contract["task"] != "future_fulfilled_demand_risk":
        raise ValueError("Ground-truth contract task does not match the temporal benchmark")
    protocol = contract["decision_protocol"]
    if int(protocol.get("horizon_days", -1)) != HORIZON_DAYS:
        raise ValueError("Ground-truth contract horizon does not match the benchmark horizon")
    horizon_sensitivity_days = [int(days) for days in protocol.get("horizon_sensitivity_days", [])]
    if HORIZON_DAYS not in horizon_sensitivity_days or any(days <= 0 for days in horizon_sensitivity_days):
        raise ValueError("Ground-truth horizon sensitivity must contain positive horizons including the benchmark horizon")
    strategy = contract["selected_strategy"]
    if tuple(strategy.get("risk_order", ())) != RISK_CLASSES:
        raise ValueError("Ground-truth contract risk order does not match the benchmark")
    thresholds = strategy.get("thresholds") or {}
    high_max = int(thresholds.get("high_risk_future_quantity_max", -1))
    medium_max = int(thresholds.get("medium_risk_future_quantity_max", -1))
    if int(thresholds.get("critical_future_quantity", -1)) != 0 or high_max < 1 or medium_max <= high_max:
        raise ValueError("Ground-truth absolute-demand thresholds are invalid")
    policy_ids = [str(policy.get("id", "")) for policy in contract["threshold_sensitivity_policies"]]
    if len(policy_ids) != len(set(policy_ids)) or "baseline_0_5_25" not in policy_ids:
        raise ValueError("Ground-truth sensitivity policies require a unique baseline_0_5_25 entry")
    alternative = contract["alternative_strategy"]
    if float(alternative.get("denominator_floor", 0)) <= 0:
        raise ValueError("Ground-truth DRR denominator floor must be positive")
    if not 0 < float(alternative.get("high_risk_drr_max", 0)) < float(alternative.get("medium_risk_drr_max", 0)):
        raise ValueError("Ground-truth DRR thresholds must be increasing positive values")
    return contract


@dataclass(frozen=True)
class SourceProfile:
    raw_rows: int
    retained_orders: int
    retained_item_lines: int
    duplicate_internal_ids: int
    duplicate_order_ids: int
    invalid_status_orders: int
    returned_orders: int
    excluded_not_calculate_money: int
    malformed_item_payloads: int
    orders_without_items: int
    invalid_item_quantities: int
    missing_sku_items: int
    start_date: str
    end_date: str
    unique_skus: int
    status_counts: dict[str, int]
    warehouse_counts: dict[str, int]
    loaded_columns: list[str]
    excluded_columns: list[str]


def log(message: str) -> None:
    print(message, flush=True)


def is_real_value(value: Any) -> bool:
    """Return whether an export placeholder represents a real value."""
    if value is None or pd.isna(value):
        return False
    return str(value).strip().upper() not in {"", "NULL", "NONE", "NAN", "[]", "{}"}


def parse_items(payload: Any) -> list[dict[str, Any]] | None:
    if not is_real_value(payload):
        return []
    try:
        decoded = json.loads(str(payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    items = decoded.get("item_list", [])
    return items if isinstance(items, list) else None


def extract_daily_demand(source_zip: Path, chunk_size: int) -> tuple[pd.DataFrame, SourceProfile]:
    """Read the ZIP in chunks and aggregate valid order lines by day and model SKU."""
    required_columns = [
        "_id",
        "orderId",
        "status",
        "time",
        "returnId",
        "notCaculateMoney",
        "warehouse",
        "data",
    ]
    excluded_columns = [
        "buyerId", "buyerUserName", "phone", "name", "city", "district", "ward",
        "address", "createdAt", "updatedAt", "returnedAt", "returnLastTimeChecking",
    ]
    daily_qty: defaultdict[tuple[pd.Timestamp, str], float] = defaultdict(float)
    product_names: dict[str, str] = {}
    statuses: Counter[str] = Counter()
    warehouses: Counter[str] = Counter()
    seen_internal_ids: set[str] = set()
    seen_order_ids: set[str] = set()
    counters: Counter[str] = Counter()
    start_date: pd.Timestamp | None = None
    end_date: pd.Timestamp | None = None

    with ZipFile(source_zip) as archive:
        members = [member for member in archive.namelist() if member.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected exactly one CSV in {source_zip}, found: {members}")
        with archive.open(members[0]) as raw_csv:
            reader = pd.read_csv(
                raw_csv,
                usecols=required_columns,
                chunksize=chunk_size,
                low_memory=False,
                dtype={
                    "_id": "string",
                    "orderId": "string",
                    "status": "string",
                    "returnId": "string",
                    "warehouse": "string",
                    "data": "string",
                },
            )
            for chunk_number, chunk in enumerate(reader, start=1):
                counters["raw_rows"] += len(chunk)
                statuses.update(chunk["status"].fillna("<NULL>").astype(str))
                warehouses.update(chunk["warehouse"].fillna("<NULL>").astype(str))

                for row in chunk.itertuples(index=False):
                    counters["rows_seen"] += 1
                    internal_id = str(row._0) if is_real_value(row._0) else ""
                    order_id = str(row.orderId) if is_real_value(row.orderId) else ""
                    if internal_id and internal_id in seen_internal_ids:
                        counters["duplicate_internal_ids"] += 1
                        continue
                    if order_id and order_id in seen_order_ids:
                        counters["duplicate_order_ids"] += 1
                        continue
                    if internal_id:
                        seen_internal_ids.add(internal_id)
                    if order_id:
                        seen_order_ids.add(order_id)

                    status = str(row.status).upper().strip() if is_real_value(row.status) else ""
                    if status not in VALID_STATUSES:
                        counters["invalid_status_orders"] += 1
                        continue
                    if is_real_value(row.returnId):
                        counters["returned_orders"] += 1
                        continue
                    if pd.to_numeric(row.notCaculateMoney, errors="coerce") == 1:
                        counters["excluded_not_calculate_money"] += 1
                        continue
                    order_day = pd.to_datetime(row.time, errors="coerce")
                    if pd.isna(order_day):
                        counters["invalid_time_orders"] += 1
                        continue
                    order_day = order_day.normalize()
                    items = parse_items(row.data)
                    if items is None:
                        counters["malformed_item_payloads"] += 1
                        continue
                    if not items:
                        counters["orders_without_items"] += 1
                        continue

                    counters["retained_orders"] += 1
                    start_date = order_day if start_date is None or order_day < start_date else start_date
                    end_date = order_day if end_date is None or order_day > end_date else end_date
                    for item in items:
                        if not isinstance(item, dict):
                            counters["malformed_item_payloads"] += 1
                            continue
                        raw_sku = item.get("model_sku") or item.get("item_sku") or item.get("model_id")
                        if not is_real_value(raw_sku):
                            counters["missing_sku_items"] += 1
                            continue
                        quantity = pd.to_numeric(
                            item.get("model_quantity_purchased", item.get("quantity_purchased")),
                            errors="coerce",
                        )
                        if pd.isna(quantity) or float(quantity) <= 0:
                            counters["invalid_item_quantities"] += 1
                            continue
                        sku = str(raw_sku).strip()
                        daily_qty[(order_day, sku)] += float(quantity)
                        product_names.setdefault(sku, str(item.get("item_name") or item.get("model_name") or sku))
                        counters["retained_item_lines"] += 1

                if chunk_number % 10 == 0:
                    log(f"  Parsed {counters['raw_rows']:,} order rows; retained {counters['retained_item_lines']:,} item lines")

    if not daily_qty or start_date is None or end_date is None:
        raise ValueError("No valid fulfilled item demand could be extracted from orders_full.zip")
    records = [
        {"date": date, "sku": sku, "quantity": quantity, "product_name": product_names[sku]}
        for (date, sku), quantity in daily_qty.items()
    ]
    daily = pd.DataFrame.from_records(records).sort_values(["date", "sku"]).reset_index(drop=True)
    profile = SourceProfile(
        raw_rows=int(counters["raw_rows"]),
        retained_orders=int(counters["retained_orders"]),
        retained_item_lines=int(counters["retained_item_lines"]),
        duplicate_internal_ids=int(counters["duplicate_internal_ids"]),
        duplicate_order_ids=int(counters["duplicate_order_ids"]),
        invalid_status_orders=int(counters["invalid_status_orders"]),
        returned_orders=int(counters["returned_orders"]),
        excluded_not_calculate_money=int(counters["excluded_not_calculate_money"]),
        malformed_item_payloads=int(counters["malformed_item_payloads"]),
        orders_without_items=int(counters["orders_without_items"]),
        invalid_item_quantities=int(counters["invalid_item_quantities"]),
        missing_sku_items=int(counters["missing_sku_items"]),
        start_date=start_date.date().isoformat(),
        end_date=end_date.date().isoformat(),
        unique_skus=int(daily["sku"].nunique()),
        status_counts=dict(statuses.most_common()),
        warehouse_counts=dict(warehouses.most_common()),
        loaded_columns=required_columns,
        excluded_columns=excluded_columns,
    )
    return daily, profile


def build_daily_matrix(daily: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    all_dates = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    sku_order = sorted(daily["sku"].unique())
    matrix = (
        daily.pivot_table(index="date", columns="sku", values="quantity", aggfunc="sum", fill_value=0.0)
        .reindex(index=all_dates, columns=sku_order, fill_value=0.0)
        .astype("float32")
    )
    product_names = daily.drop_duplicates("sku").set_index("sku")["product_name"].astype(str).to_dict()
    return matrix, sku_order, product_names


def label_absolute_future_demand(
    future_quantity: np.ndarray,
    historical_total: np.ndarray,
    *,
    high_risk_max: int = 5,
    medium_risk_max: int = 25,
) -> np.ndarray:
    """Assign the frozen absolute-future-demand target without model feedback."""
    if high_risk_max < 1 or medium_risk_max <= high_risk_max:
        raise ValueError("Absolute-demand thresholds must satisfy 1 <= high < medium")
    labels = np.full(len(future_quantity), RISK_TO_CODE["LOW_RISK"], dtype=np.int8)
    labels[future_quantity <= medium_risk_max] = RISK_TO_CODE["MEDIUM_RISK"]
    labels[future_quantity <= high_risk_max] = RISK_TO_CODE["HIGH_RISK"]
    labels[(future_quantity == 0) & (historical_total > 5)] = RISK_TO_CODE["CRITICAL"]
    return labels


def label_future_demand(future_quantity: np.ndarray, historical_total: np.ndarray) -> np.ndarray:
    """Backward-compatible wrapper for the selected 0/5/25 ground-truth policy."""
    return label_absolute_future_demand(future_quantity, historical_total)


def label_demand_retention_ratio(
    future_quantity: np.ndarray,
    historical_total: np.ndarray,
    lifetime_days: np.ndarray,
    *,
    denominator_floor: float,
    high_risk_drr_max: float,
    medium_risk_drr_max: float,
    horizon_days: int = HORIZON_DAYS,
) -> tuple[np.ndarray, np.ndarray]:
    """Assign the predeclared DRR robustness comparator and return its ratio.

    This intentionally remains an alternative target policy. It is never used
    to tune a classifier or replace the selected target automatically.
    """
    if denominator_floor <= 0 or not 0 < high_risk_drr_max < medium_risk_drr_max:
        raise ValueError("DRR policy thresholds must be positive and increasing")
    lifetime_velocity = np.divide(
        historical_total,
        np.maximum(lifetime_days, 1),
        out=np.zeros_like(future_quantity, dtype=float),
        where=np.maximum(lifetime_days, 1) > 0,
    )
    future_velocity = future_quantity / horizon_days
    drr = future_velocity / np.maximum(lifetime_velocity, denominator_floor)
    labels = np.full(len(future_quantity), RISK_TO_CODE["LOW_RISK"], dtype=np.int8)
    labels[drr <= medium_risk_drr_max] = RISK_TO_CODE["MEDIUM_RISK"]
    labels[drr <= high_risk_drr_max] = RISK_TO_CODE["HIGH_RISK"]
    labels[(future_quantity == 0) & (historical_total > 5)] = RISK_TO_CODE["CRITICAL"]
    return labels, drr


def create_snapshots(
    matrix: pd.DataFrame,
    sku_order: list[str],
    product_names: dict[str, str],
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Create leakage-safe SKU snapshots at fixed historical decision dates."""
    dates = matrix.index
    values = matrix.to_numpy(dtype=np.float64)
    first_possible = dates.min() + pd.Timedelta(days=HISTORY_DAYS)
    final_possible = dates.max() - pd.Timedelta(days=HORIZON_DAYS)
    cutoffs = list(pd.date_range(first_possible, final_possible, freq=f"{CUTOFF_FREQUENCY_DAYS}D"))
    snapshots: list[pd.DataFrame] = []

    for cutoff in cutoffs:
        cutoff_pos = int(dates.get_loc(cutoff))
        history = values[: cutoff_pos + 1]
        future = values[cutoff_pos + 1 : cutoff_pos + 1 + HORIZON_DAYS]
        if len(future) != HORIZON_DAYS:
            continue
        future_30 = values[cutoff_pos + 1 : cutoff_pos + 31]
        future_90 = values[cutoff_pos + 1 : cutoff_pos + 91]
        historical_total = history.sum(axis=0)
        eligible = historical_total > 5
        if not eligible.any():
            continue

        recent_7 = history[-7:]
        recent_30 = history[-30:]
        recent_60 = history[-60:]
        recent_90 = history[-90:]
        sum_7, sum_30 = recent_7.sum(axis=0), recent_30.sum(axis=0)
        sum_60, sum_90 = recent_60.sum(axis=0), recent_90.sum(axis=0)
        nonzero_90 = recent_90 > 0
        nonzero_count = nonzero_90.sum(axis=0)
        last_positions = np.where(history > 0, np.arange(history.shape[0])[:, None], -1).max(axis=0)
        dsls = cutoff_pos - last_positions
        quantity_sum = recent_90.sum(axis=0)
        quantity_sq_sum = np.square(recent_90).sum(axis=0)
        positive_mean = np.divide(quantity_sum, nonzero_count, out=np.zeros_like(quantity_sum), where=nonzero_count > 0)
        variance = np.divide(
            quantity_sq_sum - np.divide(np.square(quantity_sum), nonzero_count, out=np.zeros_like(quantity_sum), where=nonzero_count > 0),
            np.maximum(nonzero_count - 1, 1),
        )
        variance = np.maximum(variance, 0)
        cv2 = np.divide(variance, np.square(positive_mean), out=np.zeros_like(variance), where=positive_mean > 0)
        future_quantity = future.sum(axis=0)
        future_quantity_30 = future_30.sum(axis=0)
        # Late cutoffs remain valid for the 60-day model but cannot be used in
        # the 90-day sensitivity analysis because their outcomes are not mature.
        future_quantity_90 = future_90.sum(axis=0) if len(future_90) == 90 else np.full(len(sku_order), np.nan)
        labels = label_future_demand(future_quantity, historical_total)
        lifetime_days = np.maximum(1, cutoff_pos + 1 - np.where(history > 0, np.arange(history.shape[0])[:, None], history.shape[0]).min(axis=0))

        frame = pd.DataFrame(
            {
                "cutoff": cutoff,
                "sku": sku_order,
                "product_name": [product_names[sku] for sku in sku_order],
                "historical_total_qty": historical_total,
                "future_net_qty_30d": future_quantity_30,
                "future_net_qty_60d": future_quantity,
                "future_net_qty_90d": future_quantity_90,
                "sales_qty_7d": sum_7,
                "sales_qty_30d": sum_30,
                "sales_qty_60d": sum_60,
                "sales_qty_90d": sum_90,
                "sales_velocity_7d": sum_7 / 7,
                "sales_velocity_30d": sum_30 / 30,
                "sales_velocity_60d": sum_60 / 60,
                "sales_velocity_90d": sum_90 / 90,
                "zero_rate_30d": (recent_30 == 0).mean(axis=0),
                "zero_rate_60d": (recent_60 == 0).mean(axis=0),
                "zero_rate_90d": (recent_90 == 0).mean(axis=0),
                "dsls": dsls,
                "adi_90d": np.divide(90, nonzero_count, out=np.full(len(sku_order), 90.0), where=nonzero_count > 0),
                "cv2_90d": cv2,
                "lifetime_days": lifetime_days,
                "lifetime_velocity": np.divide(historical_total, lifetime_days),
                "recent_7_to_30_ratio": np.divide(sum_7 / 7, sum_30 / 30, out=np.zeros_like(sum_7), where=sum_30 > 0),
                "recent_30_to_90_ratio": np.divide(sum_30 / 30, sum_90 / 90, out=np.zeros_like(sum_30), where=sum_90 > 0),
                "risk_label": labels,
            }
        )
        snapshots.append(frame.loc[eligible].copy())

    if not snapshots:
        raise ValueError("No valid snapshots were created. Check date range and eligibility rules.")
    return pd.concat(snapshots, ignore_index=True), cutoffs


def temporal_split(cutoffs: list[pd.Timestamp]) -> tuple[list[pd.Timestamp], list[pd.Timestamp], list[pd.Timestamp], dict[str, str]]:
    """Split by decision date and purge training labels that touch later features."""
    if len(cutoffs) < 12:
        raise ValueError(f"Need at least 12 cutoffs for a temporal benchmark; found {len(cutoffs)}")
    validation_start = cutoffs[int(len(cutoffs) * 0.60)]
    test_start = cutoffs[int(len(cutoffs) * 0.80)]
    embargo = pd.Timedelta(days=HORIZON_DAYS)
    train = [cutoff for cutoff in cutoffs if cutoff < validation_start - embargo]
    validation = [cutoff for cutoff in cutoffs if validation_start <= cutoff < test_start - embargo]
    test = [cutoff for cutoff in cutoffs if cutoff >= test_start]
    if not train or not validation or not test:
        raise ValueError("Temporal split produced an empty segment; extend the source period or reduce cutoff frequency.")
    audit = {
        "horizon_days": str(HORIZON_DAYS),
        "cutoff_frequency_days": str(CUTOFF_FREQUENCY_DAYS),
        "embargo_days": str(HORIZON_DAYS),
        "train_last_cutoff": train[-1].date().isoformat(),
        "validation_first_cutoff": validation[0].date().isoformat(),
        "validation_last_cutoff": validation[-1].date().isoformat(),
        "test_first_cutoff": test[0].date().isoformat(),
        "test_last_cutoff": test[-1].date().isoformat(),
        "train_label_window_ends": (train[-1] + embargo).date().isoformat(),
        "validation_feature_window_starts": validation[0].date().isoformat(),
        "validation_label_window_ends": (validation[-1] + embargo).date().isoformat(),
        "test_feature_window_starts": test[0].date().isoformat(),
    }
    return train, validation, test, audit


def align_proba(model: Any, features: pd.DataFrame) -> np.ndarray:
    raw = model.predict_proba(features)
    aligned = np.zeros((len(features), len(RISK_CLASSES)), dtype=float)
    for position, class_code in enumerate(model.classes_):
        aligned[:, int(class_code)] = raw[:, position]
    return aligned


def ece_score(y_binary: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    bucket = np.clip((probabilities * bins).astype(int), 0, bins - 1)
    total = len(probabilities)
    ece = 0.0
    for index in range(bins):
        mask = bucket == index
        if mask.any():
            ece += mask.mean() * abs(float(y_binary[mask].mean()) - float(probabilities[mask].mean()))
    return float(ece)


def metrics_for_predictions(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    predicted = probabilities.argmax(axis=1)
    high_true = np.isin(y_true, [RISK_TO_CODE["CRITICAL"], RISK_TO_CODE["HIGH_RISK"]])
    high_predicted = np.isin(predicted, [RISK_TO_CODE["CRITICAL"], RISK_TO_CODE["HIGH_RISK"]])
    high_probability = probabilities[:, RISK_TO_CODE["CRITICAL"]] + probabilities[:, RISK_TO_CODE["HIGH_RISK"]]
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, predicted, labels=list(range(len(RISK_CLASSES))), zero_division=0
    )
    top_k = max(1, int(np.ceil(len(y_true) * 0.05)))
    top_indices = np.argsort(-high_probability, kind="stable")[:top_k]
    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "macro_f1": float(f1_score(y_true, predicted, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "high_risk_precision": float(precision_score(high_true, high_predicted, zero_division=0)),
        "high_risk_recall": float(recall_score(high_true, high_predicted, zero_division=0)),
        "high_risk_f1": float(f1_score(high_true, high_predicted, zero_division=0)),
        "high_risk_fnr": float(1 - recall_score(high_true, high_predicted, zero_division=0)),
        "high_risk_pr_auc": float(average_precision_score(high_true, high_probability)),
        "high_risk_brier": float(brier_score_loss(high_true, high_probability)),
        "high_risk_ece": ece_score(high_true, high_probability),
        "precision_at_5pct": float(high_true[top_indices].mean()),
        "recall_at_5pct": float(high_true[top_indices].sum() / max(1, high_true.sum())),
        "evaluated_skus": float(len(y_true)),
    }
    for index, label in enumerate(RISK_CLASSES):
        metrics[f"precision_{label}"] = float(precision[index])
        metrics[f"recall_{label}"] = float(recall[index])
        metrics[f"f1_{label}"] = float(f1[index])
    return metrics


def recent_60d_rule(snapshots: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return a deterministic, auditable recent-sales baseline.

    The rule deliberately uses only fulfilled quantity in the prior 60 days.
    It is not a learned model and it is never eligible for model selection.  A
    monotonic high-risk score is emitted solely for PR-AUC and top-K comparison.
    """
    recent = snapshots["sales_qty_60d"].to_numpy(dtype=float)
    predicted = np.full(len(recent), RISK_TO_CODE["LOW_RISK"], dtype=np.int8)
    predicted[recent <= 25] = RISK_TO_CODE["MEDIUM_RISK"]
    predicted[recent <= 5] = RISK_TO_CODE["HIGH_RISK"]
    predicted[recent == 0] = RISK_TO_CODE["CRITICAL"]

    # Preserve the deterministic class decision while exposing a continuous,
    # non-learned ranking score derived only from the same prior-60-day input.
    high_score = 1.0 / (1.0 + np.maximum(recent, 0.0))
    probabilities = np.full((len(recent), len(RISK_CLASSES)), 0.01, dtype=float)
    for index, class_code in enumerate(predicted):
        if class_code == RISK_TO_CODE["CRITICAL"]:
            probabilities[index] = (0.96, 0.02, 0.01, 0.01)
        elif class_code == RISK_TO_CODE["HIGH_RISK"]:
            probabilities[index] = (0.08, 0.82, 0.07, 0.03)
        elif class_code == RISK_TO_CODE["MEDIUM_RISK"]:
            probabilities[index] = (0.03, 0.17, 0.74, 0.06)
        else:
            probabilities[index] = (0.01, 0.04, 0.10, 0.85)

    # The total P(CRITICAL)+P(HIGH_RISK) needs to retain granular ordering.
    # Allocate each score between the two high-risk classes without changing
    # the rule's argmax label.
    for index, class_code in enumerate(predicted):
        if class_code in (RISK_TO_CODE["CRITICAL"], RISK_TO_CODE["HIGH_RISK"]):
            high_probability = max(0.60, min(0.99, 0.55 + 0.44 * high_score[index]))
            critical_share = 0.88 if class_code == RISK_TO_CODE["CRITICAL"] else 0.12
            probabilities[index, 0] = high_probability * critical_share
            probabilities[index, 1] = high_probability * (1.0 - critical_share)
            remaining = 1.0 - high_probability
            probabilities[index, 2] = remaining * 0.75
            probabilities[index, 3] = remaining * 0.25
        elif class_code == RISK_TO_CODE["MEDIUM_RISK"]:
            high_probability = min(0.49, 0.04 + 0.42 * high_score[index])
            probabilities[index, 0] = high_probability * 0.20
            probabilities[index, 1] = high_probability * 0.80
            probabilities[index, 2] = 0.70
            probabilities[index, 3] = 0.30 - high_probability
        else:
            high_probability = min(0.19, 0.01 + 0.18 * high_score[index])
            probabilities[index, 0] = high_probability * 0.20
            probabilities[index, 1] = high_probability * 0.80
            probabilities[index, 2] = 0.10
            probabilities[index, 3] = 0.90 - high_probability
    return predicted, probabilities


def write_prediction_table(
    path: Path,
    snapshots: pd.DataFrame,
    probabilities: np.ndarray,
    predicted: np.ndarray | None = None,
) -> None:
    """Persist prediction-level evidence for reproducibility and audit."""
    predicted_codes = probabilities.argmax(axis=1) if predicted is None else predicted
    output = snapshots[["cutoff", "sku", "product_name", "future_net_qty_60d", "risk_label"]].copy()
    output["actual_risk_class"] = output["risk_label"].map(dict(enumerate(RISK_CLASSES)))
    output["predicted_risk_class"] = pd.Series(predicted_codes, index=output.index).map(dict(enumerate(RISK_CLASSES)))
    output["high_risk_probability"] = probabilities[:, 0] + probabilities[:, 1]
    for index, label in enumerate(RISK_CLASSES):
        output[f"probability_{label.lower()}"] = probabilities[:, index]
    output.to_csv(path, index=False)


def bootstrap_cutoff_ci(per_cutoff: pd.DataFrame, metric: str, iterations: int = 2_000, seed: int = 42) -> tuple[float, float]:
    values = per_cutoff[metric].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=float)
    for index in range(iterations):
        means[index] = rng.choice(values, size=len(values), replace=True).mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def paired_cutoff_bootstrap(
    candidate_per_cutoff: pd.DataFrame,
    baseline_per_cutoff: pd.DataFrame,
    metric: str,
    iterations: int = 2_000,
    seed: int = 42,
) -> dict[str, float]:
    """Compare candidate and baseline using decision cutoffs as paired blocks."""
    merged = candidate_per_cutoff[["cutoff", metric]].merge(
        baseline_per_cutoff[["cutoff", metric]], on="cutoff", suffixes=("_candidate", "_baseline"), validate="one_to_one"
    )
    if merged.empty:
        raise ValueError(f"No paired cutoff rows available for {metric}")
    differences = (merged[f"{metric}_candidate"] - merged[f"{metric}_baseline"]).to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=float)
    for index in range(iterations):
        means[index] = rng.choice(differences, size=len(differences), replace=True).mean()
    return {
        "mean_difference": float(differences.mean()),
        "ci_lower": float(np.quantile(means, 0.025)),
        "ci_upper": float(np.quantile(means, 0.975)),
        "probability_candidate_better": float((means > 0).mean()),
        "paired_cutoffs": int(len(differences)),
    }


def label_comparison(reference: np.ndarray, alternative: np.ndarray) -> dict[str, float | int]:
    """Compare ordinal four-level labels without treating every snapshot as IID."""
    if len(reference) != len(alternative) or not len(reference):
        raise ValueError("Label comparisons require equally sized, non-empty arrays")
    distance = np.abs(reference.astype(int) - alternative.astype(int))
    changed = distance > 0
    critical = reference == RISK_TO_CODE["CRITICAL"]
    return {
        "evaluated_skus": int(len(reference)),
        "label_agreement": float((~changed).mean()),
        "weighted_cohen_kappa": float(
            cohen_kappa_score(reference, alternative, labels=list(range(len(RISK_CLASSES))), weights="linear")
        ),
        "changed_label_share": float(changed.mean()),
        "adjacent_transition_share": float((changed & (distance == 1)).mean()),
        "non_adjacent_transition_share": float((distance > 1).mean()),
        "critical_reference_count": int(critical.sum()),
        "critical_retained_share": float((alternative[critical] == RISK_TO_CODE["CRITICAL"]).mean()) if critical.any() else float("nan"),
    }


def class_distribution_rows(
    labels: np.ndarray,
    *,
    cutoff: pd.Timestamp,
    split: str,
    strategy: str,
) -> list[dict[str, Any]]:
    total = max(1, len(labels))
    return [
        {
            "cutoff": pd.Timestamp(cutoff).date().isoformat(),
            "split": split,
            "strategy": strategy,
            "risk_class": risk_class,
            "snapshot_count": int((labels == code).sum()),
            "share": float((labels == code).sum() / total),
            "eligible_snapshot_count": int(len(labels)),
        }
        for code, risk_class in enumerate(RISK_CLASSES)
    ]


def cohens_d(left: np.ndarray, right: np.ndarray) -> float:
    """Return standardized mean difference, or NaN when a comparison is undefined."""
    if len(left) < 2 or len(right) < 2:
        return float("nan")
    left_variance = float(np.var(left, ddof=1))
    right_variance = float(np.var(right, ddof=1))
    pooled_denominator = len(left) + len(right) - 2
    if pooled_denominator <= 0:
        return float("nan")
    pooled_std = np.sqrt(((len(left) - 1) * left_variance + (len(right) - 1) * right_variance) / pooled_denominator)
    if np.isclose(pooled_std, 0.0):
        return 0.0 if np.isclose(float(np.mean(left)), float(np.mean(right))) else float("nan")
    return float((float(np.mean(left)) - float(np.mean(right))) / pooled_std)


def discriminability_rows(
    frame: pd.DataFrame,
    labels: np.ndarray,
    *,
    cutoff: pd.Timestamp,
    split: str,
    strategy: str,
) -> list[dict[str, Any]]:
    """Measure historical-signal separation for a label policy at one cutoff."""
    rows: list[dict[str, Any]] = []
    for feature in DISCRIMINABILITY_FEATURES:
        values = frame[feature].to_numpy(dtype=float)
        for left_class, right_class in combinations(range(len(RISK_CLASSES)), 2):
            left = values[labels == left_class]
            right = values[labels == right_class]
            effect = cohens_d(left, right)
            rows.append(
                {
                    "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                    "split": split,
                    "strategy": strategy,
                    "feature": feature,
                    "left_risk_class": RISK_CLASSES[left_class],
                    "right_risk_class": RISK_CLASSES[right_class],
                    "left_count": int(len(left)),
                    "right_count": int(len(right)),
                    "cohens_d": effect,
                    "absolute_cohens_d": abs(effect) if np.isfinite(effect) else float("nan"),
                }
            )
    return rows


def ground_truth_validation(
    snapshots: pd.DataFrame,
    ground_truth_contract: dict[str, Any],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Validate a frozen target policy across rolling temporal cutoffs.

    All outputs are descriptive target-policy evidence. In particular, no
    downstream model metric is read here, preventing post-hoc target tuning.
    """
    required = {
        "cutoff", "split", "sku", "future_net_qty_30d", "future_net_qty_60d", "future_net_qty_90d", "historical_total_qty",
        "lifetime_days", "risk_label", *DISCRIMINABILITY_FEATURES,
    }
    missing = sorted(required.difference(snapshots.columns))
    if missing:
        raise ValueError(f"Ground-truth validation requires snapshot columns: {missing}")
    selected = ground_truth_contract["selected_strategy"]
    selected_thresholds = selected["thresholds"]
    sensitivity_policies = ground_truth_contract["threshold_sensitivity_policies"]
    drr_policy = ground_truth_contract["alternative_strategy"]
    horizon_sensitivity_days = [int(days) for days in ground_truth_contract["decision_protocol"]["horizon_sensitivity_days"]]
    baseline_policy = next(policy for policy in sensitivity_policies if policy["id"] == "baseline_0_5_25")
    if (
        int(baseline_policy["high_risk_future_quantity_max"]) != int(selected_thresholds["high_risk_future_quantity_max"])
        or int(baseline_policy["medium_risk_future_quantity_max"]) != int(selected_thresholds["medium_risk_future_quantity_max"])
    ):
        raise ValueError("Ground-truth baseline sensitivity policy differs from selected strategy")

    strategy_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    horizon_sensitivity_rows: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    discriminability_pair_rows: list[dict[str, Any]] = []
    temporal_transition_rows: list[dict[str, Any]] = []
    labels_by_cutoff: dict[tuple[str, pd.Timestamp], pd.DataFrame] = {}

    eligible = snapshots.loc[snapshots["split"].isin(["train", "validation", "test"])].copy()
    for cutoff in sorted(pd.to_datetime(eligible["cutoff"].unique()).tolist()):
        frame = eligible.loc[eligible["cutoff"].eq(cutoff)].copy()
        if frame.empty:
            continue
        split = str(frame["split"].iloc[0])
        future = frame["future_net_qty_60d"].to_numpy(dtype=float)
        historical = frame["historical_total_qty"].to_numpy(dtype=float)
        lifetime_days = frame["lifetime_days"].to_numpy(dtype=float)
        absolute_labels = label_absolute_future_demand(
            future,
            historical,
            high_risk_max=int(selected_thresholds["high_risk_future_quantity_max"]),
            medium_risk_max=int(selected_thresholds["medium_risk_future_quantity_max"]),
        )
        if not np.array_equal(absolute_labels, frame["risk_label"].to_numpy(dtype=np.int8)):
            raise ValueError("Snapshot labels do not match the selected ground-truth contract")
        drr_labels, drr = label_demand_retention_ratio(
            future,
            historical,
            lifetime_days,
            denominator_floor=float(drr_policy["denominator_floor"]),
            high_risk_drr_max=float(drr_policy["high_risk_drr_max"]),
            medium_risk_drr_max=float(drr_policy["medium_risk_drr_max"]),
        )
        comparison = label_comparison(absolute_labels, drr_labels)
        strategy_rows.append(
            {
                "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                "split": split,
                "reference_strategy": selected["id"],
                "alternative_strategy": drr_policy["id"],
                "drr_median": float(np.median(drr)),
                "drr_p10": float(np.quantile(drr, 0.10)),
                "drr_p90": float(np.quantile(drr, 0.90)),
                **comparison,
            }
        )
        distribution_rows.extend(class_distribution_rows(absolute_labels, cutoff=cutoff, split=split, strategy=selected["id"]))
        distribution_rows.extend(class_distribution_rows(drr_labels, cutoff=cutoff, split=split, strategy=drr_policy["id"]))
        discriminability_pair_rows.extend(
            discriminability_rows(frame, absolute_labels, cutoff=cutoff, split=split, strategy=selected["id"])
        )
        discriminability_pair_rows.extend(
            discriminability_rows(frame, drr_labels, cutoff=cutoff, split=split, strategy=drr_policy["id"])
        )

        for policy in sensitivity_policies:
            alternative_labels = label_absolute_future_demand(
                future,
                historical,
                high_risk_max=int(policy["high_risk_future_quantity_max"]),
                medium_risk_max=int(policy["medium_risk_future_quantity_max"]),
            )
            sensitivity_rows.append(
                {
                    "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                    "split": split,
                    "policy_id": policy["id"],
                    "high_risk_future_quantity_max": int(policy["high_risk_future_quantity_max"]),
                    "medium_risk_future_quantity_max": int(policy["medium_risk_future_quantity_max"]),
                    **label_comparison(absolute_labels, alternative_labels),
                }
            )
        for horizon_days in horizon_sensitivity_days:
            quantity_column = f"future_net_qty_{horizon_days}d"
            if quantity_column not in frame:
                raise ValueError(f"Ground-truth horizon sensitivity requires {quantity_column}")
            horizon_future = frame[quantity_column].to_numpy(dtype=float)
            mature = np.isfinite(horizon_future)
            if not mature.any():
                # Retain the row rather than silently dropping a late cutoff:
                # coverage must disclose why no 90-day comparison exists.
                horizon_sensitivity_rows.append(
                    {
                        "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                        "split": split,
                        "reference_horizon_days": HORIZON_DAYS,
                        "comparison_horizon_days": horizon_days,
                        "eligible_snapshot_count": int(len(frame)),
                        "mature_snapshot_count": 0,
                        "mature_coverage": 0.0,
                        "evaluated_skus": 0,
                        "label_agreement": float("nan"),
                        "weighted_cohen_kappa": float("nan"),
                        "changed_label_share": float("nan"),
                        "adjacent_transition_share": float("nan"),
                        "non_adjacent_transition_share": float("nan"),
                        "critical_reference_count": 0,
                        "critical_retained_share": float("nan"),
                    }
                )
                continue
            horizon_labels = label_absolute_future_demand(
                horizon_future[mature],
                historical[mature],
                high_risk_max=int(selected_thresholds["high_risk_future_quantity_max"]),
                medium_risk_max=int(selected_thresholds["medium_risk_future_quantity_max"]),
            )
            horizon_sensitivity_rows.append(
                {
                    "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                    "split": split,
                    "reference_horizon_days": HORIZON_DAYS,
                    "comparison_horizon_days": horizon_days,
                    "eligible_snapshot_count": int(len(frame)),
                    "mature_snapshot_count": int(mature.sum()),
                    "mature_coverage": float(mature.mean()),
                    **label_comparison(absolute_labels[mature], horizon_labels),
                }
            )
        labels_by_cutoff[(split, pd.Timestamp(cutoff))] = pd.DataFrame(
            {"sku": frame["sku"].to_numpy(), "risk_label": absolute_labels}
        )

    for split in ("train", "validation", "test"):
        cutoff_keys = sorted(cutoff for current_split, cutoff in labels_by_cutoff if current_split == split)
        for previous, current in zip(cutoff_keys, cutoff_keys[1:]):
            pair = labels_by_cutoff[(split, previous)].merge(
                labels_by_cutoff[(split, current)], on="sku", suffixes=("_previous", "_current"), validate="one_to_one"
            )
            if pair.empty:
                continue
            transition = label_comparison(
                pair["risk_label_previous"].to_numpy(dtype=np.int8),
                pair["risk_label_current"].to_numpy(dtype=np.int8),
            )
            temporal_transition_rows.append(
                {
                    "split": split,
                    "previous_cutoff": previous.date().isoformat(),
                    "cutoff": current.date().isoformat(),
                    **transition,
                }
            )

    strategy_comparison = pd.DataFrame(strategy_rows)
    threshold_sensitivity = pd.DataFrame(sensitivity_rows)
    horizon_sensitivity = pd.DataFrame(horizon_sensitivity_rows)
    class_distribution = pd.DataFrame(distribution_rows)
    discriminability_pairs = pd.DataFrame(discriminability_pair_rows)
    temporal_transitions = pd.DataFrame(temporal_transition_rows)
    if discriminability_pairs.empty:
        discriminability_summary = pd.DataFrame()
    else:
        discriminability_summary = (
            discriminability_pairs.groupby(["split", "strategy", "cutoff"], observed=True)
            .agg(
                mean_absolute_cohens_d=("absolute_cohens_d", "mean"),
                median_absolute_cohens_d=("absolute_cohens_d", "median"),
                valid_feature_class_pairs=("absolute_cohens_d", "count"),
                large_effect_pair_share=("absolute_cohens_d", lambda values: float((values >= 0.8).mean())),
            )
            .reset_index()
        )
    summary: dict[str, Any] = {
        "ground_truth_contract_schema_version": ground_truth_contract["schema_version"],
        "ground_truth_contract_status": ground_truth_contract["status"],
        "selected_strategy": selected["id"],
        "alternative_strategy": drr_policy["id"],
        "selection_boundary": "No downstream model metric is used to alter target thresholds.",
        "evaluation_scope": "Rolling temporal cutoffs, reported separately for train, validation and held-out test.",
        "rows": {
            "strategy_comparison": int(len(strategy_comparison)),
            "threshold_sensitivity": int(len(threshold_sensitivity)),
            "horizon_sensitivity": int(len(horizon_sensitivity)),
            "class_distribution": int(len(class_distribution)),
            "temporal_transitions": int(len(temporal_transitions)),
            "discriminability_pairs": int(len(discriminability_pairs)),
        },
    }
    if not strategy_comparison.empty:
        summary["strategy_comparison_by_split"] = (
            strategy_comparison.groupby("split", observed=True)[["label_agreement", "weighted_cohen_kappa"]]
            .mean()
            .reset_index()
            .to_dict(orient="records")
        )
    if not threshold_sensitivity.empty:
        summary["threshold_sensitivity_by_split"] = (
            threshold_sensitivity.groupby(["split", "policy_id"], observed=True)[
                ["label_agreement", "weighted_cohen_kappa", "critical_retained_share", "non_adjacent_transition_share"]
            ]
            .mean()
            .reset_index()
            .to_dict(orient="records")
        )
    if not horizon_sensitivity.empty:
        summary["horizon_sensitivity_by_split"] = (
            horizon_sensitivity.groupby(["split", "comparison_horizon_days"], observed=True)[
                ["label_agreement", "weighted_cohen_kappa", "critical_retained_share", "mature_coverage"]
            ]
            .mean()
            .reset_index()
            .to_dict(orient="records")
        )
    if not discriminability_summary.empty:
        summary["discriminability_by_split"] = (
            discriminability_summary.groupby(["split", "strategy"], observed=True)[
                ["mean_absolute_cohens_d", "large_effect_pair_share"]
            ]
            .mean()
            .reset_index()
            .to_dict(orient="records")
        )
    return {
        "strategy_comparison": strategy_comparison,
        "threshold_sensitivity": threshold_sensitivity,
        "horizon_sensitivity": horizon_sensitivity,
        "class_distribution": class_distribution,
        "temporal_transitions": temporal_transitions,
        "discriminability_pairs": discriminability_pairs,
        "discriminability_summary": discriminability_summary,
    }, summary


def model_candidates() -> dict[str, Any]:
    models: dict[str, Any] = {
        "LogisticRegression": Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("classifier", LogisticRegression(max_iter=3_000, class_weight="balanced", random_state=42)),
            ]
        ),
        "RandomForest": RandomForestClassifier(
            n_estimators=400,
            min_samples_leaf=2,
            max_features="sqrt",
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        ),
        "LightGBM": LGBMClassifier(
            objective="multiclass",
            num_class=len(RISK_CLASSES),
            n_estimators=400,
            learning_rate=0.04,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
            verbosity=-1,
        ),
    }
    try:
        from xgboost import XGBClassifier

        models["XGBoost"] = XGBClassifier(
            objective="multi:softprob",
            num_class=len(RISK_CLASSES),
            n_estimators=400,
            max_depth=6,
            learning_rate=0.04,
            min_child_weight=3,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=-1,
        )
    except ImportError:
        log("XGBoost is not installed; benchmark will report the three available baselines.")
    return models


def feature_importance(model: Any, features: list[str]) -> pd.DataFrame:
    estimator = model
    if isinstance(model, Pipeline):
        estimator = model.named_steps["classifier"]
    if not hasattr(estimator, "feature_importances_"):
        return pd.DataFrame(columns=["feature", "importance"])
    return (
        pd.DataFrame({"feature": features, "importance": estimator.feature_importances_})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_ground_truth_validation_outputs(
    output_dir: Path,
    artifacts: dict[str, pd.DataFrame],
    summary: dict[str, Any],
) -> None:
    """Persist target-policy evidence independently of model benchmarks."""
    artifact_names = {
        "strategy_comparison": "ground_truth_strategy_comparison.csv",
        "threshold_sensitivity": "ground_truth_threshold_sensitivity.csv",
        "horizon_sensitivity": "ground_truth_horizon_sensitivity.csv",
        "class_distribution": "ground_truth_per_cutoff_stability.csv",
        "temporal_transitions": "ground_truth_temporal_transitions.csv",
        "discriminability_pairs": "ground_truth_discriminability_pairs.csv",
        "discriminability_summary": "ground_truth_discriminability.csv",
    }
    for key, filename in artifact_names.items():
        artifacts[key].to_csv(output_dir / filename, index=False)
    write_json(output_dir / "ground_truth_validation.json", summary)
    lines = [
        "# Ground Truth Validation: orders_full",
        "",
        "## Scope",
        "",
        f"- Selected policy: `{summary['selected_strategy']}`.",
        f"- Alternative robustness comparator: `{summary['alternative_strategy']}`.",
        "- Metrics are reported by rolling temporal cutoff. No downstream model metric is used to alter the target policy.",
        "- The target is future fulfilled-demand risk, not direct evidence of physical inventory or capital exposure.",
        "",
        "## Strategy Comparison",
        "",
        "| Split | Label agreement | Weighted Cohen's kappa |",
        "| --- | ---: | ---: |",
    ]
    for row in summary.get("strategy_comparison_by_split", []):
        lines.append(
            f"| {row['split']} | {row['label_agreement']:.4f} | {row['weighted_cohen_kappa']:.4f} |"
        )
    selected_distribution = artifacts["class_distribution"].loc[
        artifacts["class_distribution"]["strategy"].eq(summary["selected_strategy"])
    ]
    distribution_summary = (
        selected_distribution.groupby(["split", "risk_class"], observed=True)
        .agg(snapshot_count=("snapshot_count", "sum"), eligible_snapshot_count=("eligible_snapshot_count", "sum"))
        .reset_index()
    )
    distribution_summary["share"] = (
        distribution_summary["snapshot_count"] / distribution_summary["eligible_snapshot_count"].clip(lower=1)
    )
    distribution_summary["risk_order"] = distribution_summary["risk_class"].map(RISK_TO_CODE)
    distribution_summary = distribution_summary.sort_values(["split", "risk_order"])
    lines.extend([
        "",
        "## Selected-Policy Class Distribution",
        "",
        "| Split | Risk class | Snapshots | Share |",
        "| --- | --- | ---: | ---: |",
    ])
    for row in distribution_summary.to_dict(orient="records"):
        lines.append(
            f"| {row['split']} | {row['risk_class']} | {row['snapshot_count']:,} | {row['share']:.4f} |"
        )
    lines.extend([
        "",
        "## Discriminability",
        "",
        "| Split | Strategy | Mean abs. Cohen's d | Large-effect pair share |",
        "| --- | --- | ---: | ---: |",
    ])
    for row in summary.get("discriminability_by_split", []):
        lines.append(
            f"| {row['split']} | {row['strategy']} | {row['mean_absolute_cohens_d']:.4f} | {row['large_effect_pair_share']:.4f} |"
        )
    lines.extend([
        "",
        "## Horizon Sensitivity",
        "",
        "| Split | Comparison horizon | Mature coverage | Label agreement | Weighted Cohen's kappa |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for row in summary.get("horizon_sensitivity_by_split", []):
        lines.append(
            f"| {row['split']} | {int(row['comparison_horizon_days'])}d | {row['mature_coverage']:.4f} | "
            f"{row['label_agreement']:.4f} | {row['weighted_cohen_kappa']:.4f} |"
        )
    lines.extend([
        "",
        "## Threshold Sensitivity",
        "",
        "See `ground_truth_threshold_sensitivity.csv` for each predeclared alternative policy and cutoff. "
        "The report records agreement, weighted kappa, CRITICAL retention, and whether a non-adjacent class transition occurs.",
        "",
        "## Interpretation Boundary",
        "",
        "The selected policy can be frozen only through an explicit governance decision and a new contract status/version. "
        "The evidence here does not establish stock aging, overstock, capital exposure, or the causal effect of a merchant action.",
        "",
    ])
    (output_dir / "ground_truth_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_summary(
    path: Path,
    profile: SourceProfile,
    split_audit: dict[str, str],
    selected_name: str,
    operating_mode_selection: dict[str, Any],
    validation_results: pd.DataFrame,
    test_results: pd.DataFrame,
    selected_test: dict[str, float],
    calibration: dict[str, float],
    ci: dict[str, tuple[float, float]],
    baseline_comparison: dict[str, dict[str, float]],
    contract: dict[str, Any],
    ground_truth_summary: dict[str, Any],
) -> None:
    selected_validation = validation_results.loc[validation_results["model"] == selected_name].iloc[0]
    lines = [
        "# System ML Rerun: orders_full",
        "",
        "## Scope",
        "",
        "This report evaluates the operational `orders_full.zip` source only. It does not use Online Retail or buyer PII. "
        "The target is future fulfilled demand risk, not physical inventory or capital exposure.",
        "",
        "## Source and split",
        "",
        f"- Raw orders: {profile.raw_rows:,}; retained order lines: {profile.retained_item_lines:,}; SKUs: {profile.unique_skus:,}.",
        f"- Valid demand period: {profile.start_date} to {profile.end_date}.",
        f"- Labels: next {HORIZON_DAYS} days of net fulfilled quantity. Critical=0, High=1-5, Medium=6-25, Low>25.",
        f"- Split: time ordered with a {HORIZON_DAYS}-day embargo. Train ends {split_audit['train_last_cutoff']}; validation starts {split_audit['validation_first_cutoff']}; test starts {split_audit['test_first_cutoff']}.",
        "",
        "## Selection",
        "",
        f"Selected candidate: **{selected_name}** in `{operating_mode_selection['mode']}` mode. "
        "Selection used validation only; held-out test metrics were not an input.",
        f"Eligibility constraints: `{json.dumps(operating_mode_selection['eligibility_constraints'], sort_keys=True)}`. "
        f"Ranking metrics: `{', '.join(operating_mode_selection['ranking_metrics'])}`. "
        f"Fallback used: `{operating_mode_selection['used_fallback']}`.",
        f"Validation Macro-F1: {selected_validation['macro_f1']:.4f}; high-risk recall: {selected_validation['high_risk_recall']:.4f}; PR-AUC: {selected_validation['high_risk_pr_auc']:.4f}.",
        "",
        "## Held-out test",
        "",
        f"- Macro-F1: {selected_test['macro_f1']:.4f} (cutoff-block bootstrap 95% CI {ci['macro_f1'][0]:.4f}-{ci['macro_f1'][1]:.4f}).",
        f"- Balanced accuracy: {selected_test['balanced_accuracy']:.4f} (95% CI {ci['balanced_accuracy'][0]:.4f}-{ci['balanced_accuracy'][1]:.4f}).",
        f"- High-risk recall: {selected_test['high_risk_recall']:.4f}; precision: {selected_test['high_risk_precision']:.4f}; PR-AUC: {selected_test['high_risk_pr_auc']:.4f}.",
        f"- Operational top 5%: Precision@5%={selected_test['precision_at_5pct']:.4f}; Recall@5%={selected_test['recall_at_5pct']:.4f}.",
        f"- Raw probability quality: Brier={selected_test['high_risk_brier']:.4f}, ECE={selected_test['high_risk_ece']:.4f}. Isotonic calibration trained on validation yields test Brier={calibration['brier']:.4f}, ECE={calibration['ece']:.4f}.",
        "",
        "## Comparison with recent-sales rule",
        "",
        "The `Recent60Rule` uses only the prior 60-day fulfilled quantity and is retained as a non-learned operational baseline.",
        f"- Macro-F1 difference ({selected_name} - Recent60Rule): {baseline_comparison['macro_f1']['mean_difference']:.4f} (paired cutoff bootstrap 95% CI {baseline_comparison['macro_f1']['ci_lower']:.4f}-{baseline_comparison['macro_f1']['ci_upper']:.4f}).",
        f"- High-risk recall difference: {baseline_comparison['high_risk_recall']['mean_difference']:.4f} (95% CI {baseline_comparison['high_risk_recall']['ci_lower']:.4f}-{baseline_comparison['high_risk_recall']['ci_upper']:.4f}).",
        "",
        "## Feature contract",
        "",
        f"- Schema: `{contract['schema_version']}` with {len(contract['feature_columns'])} time-safe demand features.",
        "- The contract prohibits buyer PII and requires completed/shipped, non-returned, accounting order events only.",
        "",
        "## Ground-truth validation",
        "",
        f"- Selected target policy: `{ground_truth_summary['selected_strategy']}`; alternative robustness comparator: `{ground_truth_summary['alternative_strategy']}`.",
        "- Target thresholds are evaluated independently of downstream model metrics and are not selected from held-out test performance.",
        "- Threshold, 30/60/90-day horizon sensitivity, and Strategy A-vs-DRR comparison are reported per rolling cutoff in `ground_truth_*.csv`.",
        "- This target remains a proxy for future fulfilled-demand risk; it is not evidence of physical inventory or capital exposure.",
        "",
        "## Important boundary",
        "",
        "The selected pickle is retained as an evaluation candidate only. Runtime serving requires the same contract checksum, a verified temporal-source import, explicit parity attestation and a staged ACTIVE manifest; none of these steps happens automatically.",
        "",
        "Detailed metrics are in `validation_benchmark.csv`, `test_benchmark.csv`, `recent60_rule_per_cutoff.csv`, `ground_truth_validation.json`, `ground_truth_*.csv`, `selected_vs_recent60_paired_cutoff_bootstrap.json`, and `model_manifest.json` in this directory.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "test-data" / "Database - NCKH" / "orders_full.zip",
        help="ZIP containing exactly one orders CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / f"system_ml_rerun_orders_full_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        help="Directory for reproducible evaluation outputs",
    )
    parser.add_argument("--chunk-size", type=int, default=20_000)
    parser.add_argument(
        "--feature-contract",
        type=Path,
        default=CONTRACT_PATH,
        help="Versioned temporal-demand feature contract JSON",
    )
    parser.add_argument(
        "--ground-truth-contract",
        type=Path,
        default=GROUND_TRUTH_CONTRACT_PATH,
        help="Versioned target-label policy JSON, separate from the serving feature contract",
    )
    parser.add_argument(
        "--operating-mode-policy",
        type=Path,
        default=OPERATING_MODE_POLICY_PATH,
        help="Versioned validation-only model-selection policy JSON",
    )
    parser.add_argument(
        "--operating-mode",
        default="balanced",
        help="Declared decision posture from the operating-mode policy (default: balanced)",
    )
    args = parser.parse_args(argv)
    if not args.source.is_file():
        raise FileNotFoundError(f"Missing source ZIP: {args.source}")
    contract = load_feature_contract(args.feature_contract.resolve())
    ground_truth_contract = load_ground_truth_contract(args.ground_truth_contract.resolve())
    operating_mode_policy = load_operating_mode_policy(args.operating_mode_policy.resolve())
    if args.operating_mode not in operating_mode_policy["modes"]:
        available_modes = ", ".join(sorted(operating_mode_policy["modes"]))
        raise ValueError(f"Unknown --operating-mode {args.operating_mode!r}; available modes: {available_modes}")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    log(f"Reading operational source: {args.source}")
    daily, profile = extract_daily_demand(args.source, args.chunk_size)
    daily.to_parquet(output_dir / "daily_net_fulfilled_demand.parquet", index=False)
    write_json(output_dir / "source_profile.json", asdict(profile))
    log(f"Extracted {len(daily):,} daily SKU records across {profile.unique_skus:,} model SKUs")

    matrix, sku_order, product_names = build_daily_matrix(daily)
    snapshots, all_cutoffs = create_snapshots(matrix, sku_order, product_names)
    created_cutoffs = sorted(pd.to_datetime(snapshots["cutoff"].unique()).tolist())
    train_cutoffs, validation_cutoffs, test_cutoffs, split_audit = temporal_split(created_cutoffs)
    split_audit.update(
        {
            "all_cutoffs": [cutoff.date().isoformat() for cutoff in created_cutoffs],
            "train_cutoffs": [cutoff.date().isoformat() for cutoff in train_cutoffs],
            "validation_cutoffs": [cutoff.date().isoformat() for cutoff in validation_cutoffs],
            "test_cutoffs": [cutoff.date().isoformat() for cutoff in test_cutoffs],
        }
    )
    write_json(output_dir / "temporal_split_audit.json", split_audit)

    feature_columns = list(contract["feature_columns"])
    leakage_columns = {
        "future_net_qty_30d", "future_net_qty_60d", "future_net_qty_90d",
        "risk_label", "cutoff", "sku", "product_name",
    }
    assert not leakage_columns.intersection(feature_columns), "Future or identifier feature detected"
    snapshots["split"] = np.select(
        [
            snapshots["cutoff"].isin(train_cutoffs),
            snapshots["cutoff"].isin(validation_cutoffs),
            snapshots["cutoff"].isin(test_cutoffs),
        ],
        ["train", "validation", "test"],
        default="excluded_by_embargo",
    )
    snapshots.to_parquet(output_dir / "risk_snapshots.parquet", index=False)
    ground_truth_artifacts, ground_truth_summary = ground_truth_validation(snapshots, ground_truth_contract)
    write_ground_truth_validation_outputs(output_dir, ground_truth_artifacts, ground_truth_summary)
    class_distribution = (
        snapshots.loc[snapshots["split"].isin(["train", "validation", "test"])]
        .assign(risk_class=lambda frame: frame["risk_label"].map(dict(enumerate(RISK_CLASSES))))
        .groupby(["split", "risk_class"], observed=True)
        .size()
        .rename("snapshot_count")
        .reset_index()
    )
    class_distribution.to_csv(output_dir / "class_distribution.csv", index=False)

    train = snapshots.loc[snapshots["split"] == "train"]
    validation = snapshots.loc[snapshots["split"] == "validation"]
    test = snapshots.loc[snapshots["split"] == "test"]
    log(f"Snapshots train/validation/test: {len(train):,}/{len(validation):,}/{len(test):,}")
    candidates = model_candidates()
    validation_rows: list[dict[str, Any]] = []
    fitted_models: dict[str, Any] = {}

    baseline_validation_predicted, baseline_validation_probabilities = recent_60d_rule(validation)
    validation_rows.append(
        {
            "model": "Recent60Rule",
            "model_family": "DETERMINISTIC_BASELINE",
            **metrics_for_predictions(validation["risk_label"].to_numpy(), baseline_validation_probabilities),
        }
    )
    write_prediction_table(
        output_dir / "recent60_rule_validation_predictions.csv",
        validation,
        baseline_validation_probabilities,
        baseline_validation_predicted,
    )
    baseline_validation_per_cutoff = pd.DataFrame([
        {
            "cutoff": pd.Timestamp(cutoff).date().isoformat(),
            **metrics_for_predictions(
                validation.loc[validation["cutoff"].eq(cutoff), "risk_label"].to_numpy(),
                baseline_validation_probabilities[validation["cutoff"].eq(cutoff).to_numpy()],
            ),
        }
        for cutoff in sorted(validation["cutoff"].unique())
    ])
    baseline_validation_per_cutoff.to_csv(output_dir / "recent60_rule_validation_per_cutoff.csv", index=False)
    for name, candidate in candidates.items():
        log(f"Fitting {name} on temporal train set")
        model = clone(candidate)
        model.fit(train[feature_columns], train["risk_label"])
        probabilities = align_proba(model, validation[feature_columns])
        validation_rows.append(
            {"model": name, "model_family": "ML_CANDIDATE", **metrics_for_predictions(validation["risk_label"].to_numpy(), probabilities)}
        )
        fitted_models[name] = model
    validation_benchmark = pd.DataFrame(validation_rows).sort_values(
        ["macro_f1", "high_risk_recall", "high_risk_pr_auc"], ascending=False
    )
    validation_benchmark.to_csv(output_dir / "validation_benchmark.csv", index=False)

    # Keep model selection structurally isolated from the held-out test table.
    selected_name, operating_mode_selection = select_operating_mode_candidate(
        validation_benchmark,
        operating_mode_policy,
        args.operating_mode,
    )
    selected_train_model = fitted_models[selected_name]

    test_rows: list[dict[str, Any]] = []
    all_test_probabilities: dict[str, np.ndarray] = {}

    baseline_test_predicted, baseline_test_probabilities = recent_60d_rule(test)
    test_rows.append(
        {
            "model": "Recent60Rule",
            "model_family": "DETERMINISTIC_BASELINE",
            **metrics_for_predictions(test["risk_label"].to_numpy(), baseline_test_probabilities),
        }
    )
    write_prediction_table(
        output_dir / "recent60_rule_test_predictions.csv",
        test,
        baseline_test_probabilities,
        baseline_test_predicted,
    )
    for name, model in fitted_models.items():
        probabilities = align_proba(model, test[feature_columns])
        all_test_probabilities[name] = probabilities
        test_rows.append(
            {"model": name, "model_family": "ML_CANDIDATE", **metrics_for_predictions(test["risk_label"].to_numpy(), probabilities)}
        )
    test_benchmark = pd.DataFrame(test_rows).sort_values(
        ["macro_f1", "high_risk_recall", "high_risk_pr_auc"], ascending=False
    )
    test_benchmark.to_csv(output_dir / "test_benchmark.csv", index=False)

    selected_probabilities = all_test_probabilities[selected_name]
    selected_test_metrics = metrics_for_predictions(test["risk_label"].to_numpy(), selected_probabilities)
    write_prediction_table(output_dir / "selected_model_test_predictions.csv", test, selected_probabilities)

    per_cutoff_rows: list[dict[str, Any]] = []
    for cutoff in sorted(test["cutoff"].unique()):
        mask = test["cutoff"].eq(cutoff).to_numpy()
        per_cutoff_rows.append(
            {"cutoff": pd.Timestamp(cutoff).date().isoformat(), **metrics_for_predictions(test.loc[mask, "risk_label"].to_numpy(), selected_probabilities[mask])}
        )
    per_cutoff = pd.DataFrame(per_cutoff_rows)
    per_cutoff.to_csv(output_dir / "selected_model_per_cutoff.csv", index=False)

    baseline_per_cutoff_rows: list[dict[str, Any]] = []
    for cutoff in sorted(test["cutoff"].unique()):
        mask = test["cutoff"].eq(cutoff).to_numpy()
        baseline_per_cutoff_rows.append(
            {
                "cutoff": pd.Timestamp(cutoff).date().isoformat(),
                **metrics_for_predictions(test.loc[mask, "risk_label"].to_numpy(), baseline_test_probabilities[mask]),
            }
        )
    baseline_per_cutoff = pd.DataFrame(baseline_per_cutoff_rows)
    baseline_per_cutoff.to_csv(output_dir / "recent60_rule_per_cutoff.csv", index=False)
    paired_comparison = {
        metric: paired_cutoff_bootstrap(per_cutoff, baseline_per_cutoff, metric)
        for metric in ("macro_f1", "balanced_accuracy", "high_risk_recall", "high_risk_pr_auc", "precision_at_5pct")
    }
    write_json(output_dir / "selected_vs_recent60_paired_cutoff_bootstrap.json", paired_comparison)
    ci = {
        "macro_f1": bootstrap_cutoff_ci(per_cutoff, "macro_f1"),
        "balanced_accuracy": bootstrap_cutoff_ci(per_cutoff, "balanced_accuracy"),
    }

    validation_probability = align_proba(selected_train_model, validation[feature_columns])[:, 0] + align_proba(selected_train_model, validation[feature_columns])[:, 1]
    validation_high_risk = np.isin(validation["risk_label"].to_numpy(), [0, 1]).astype(int)
    test_high_risk = np.isin(test["risk_label"].to_numpy(), [0, 1]).astype(int)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(validation_probability, validation_high_risk)
    calibrated_test_probability = calibrator.transform(selected_probabilities[:, 0] + selected_probabilities[:, 1])
    calibration_metrics = {
        "brier": float(brier_score_loss(test_high_risk, calibrated_test_probability)),
        "ece": ece_score(test_high_risk, calibrated_test_probability),
    }
    calibration_table = pd.DataFrame(
        {
            "actual_high_risk": test_high_risk,
            "raw_probability": selected_probabilities[:, 0] + selected_probabilities[:, 1],
            "calibrated_probability": calibrated_test_probability,
        }
    )
    calibration_table.to_csv(output_dir / "selected_model_calibration_test.csv", index=False)

    importance = feature_importance(selected_train_model, feature_columns)
    importance.to_csv(output_dir / "selected_model_feature_importance.csv", index=False)
    source_hash = file_sha256(args.source)
    candidate_model_path = output_dir / "selected_candidate_model.pkl"
    calibrator_path = output_dir / "selected_high_risk_isotonic_calibrator.pkl"
    with candidate_model_path.open("wb") as handle:
        pickle.dump(selected_train_model, handle)
    with calibrator_path.open("wb") as handle:
        pickle.dump(calibrator, handle)
    contract_hash = file_sha256(args.feature_contract.resolve())
    ground_truth_contract_hash = file_sha256(args.ground_truth_contract.resolve())
    operating_mode_policy_hash = file_sha256(args.operating_mode_policy.resolve())
    manifest = {
        "artifact_status": "EVALUATION_CANDIDATE_ONLY",
        "feature_contract": {
            "schema_version": contract["schema_version"],
            "path": str(args.feature_contract.resolve()),
            "sha256": contract_hash,
            "feature_columns": feature_columns,
            "class_order": list(RISK_CLASSES),
        },
        "artifacts": {
            "model": {"path": candidate_model_path.name, "sha256": file_sha256(candidate_model_path)},
            "high_risk_calibrator": {"path": calibrator_path.name, "sha256": file_sha256(calibrator_path)},
        },
        "source": {
            "path": str(args.source.resolve()),
            "sha256": source_hash,
            "size_bytes": args.source.stat().st_size,
            "dataset_scope": "orders_full operational source; not Online Retail",
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": selected_name,
        "classes": list(RISK_CLASSES),
        "feature_columns": feature_columns,
        "label_definition": {
            "horizon_days": HORIZON_DAYS,
            "thresholds": ground_truth_contract["selected_strategy"]["thresholds"],
            "CRITICAL": "future net fulfilled quantity = 0 and historical quantity > 5",
            "HIGH_RISK": "future net fulfilled quantity 1 to 5",
            "MEDIUM_RISK": "future net fulfilled quantity 6 to 25",
            "LOW_RISK": "future net fulfilled quantity > 25",
        },
        "ground_truth": {
            "contract": {
                "schema_version": ground_truth_contract["schema_version"],
                "status": ground_truth_contract["status"],
                "path": str(args.ground_truth_contract.resolve()),
                "sha256": ground_truth_contract_hash,
                "selected_strategy": ground_truth_contract["selected_strategy"]["id"],
            },
            "validation": ground_truth_summary,
            "artifacts": {
                "strategy_comparison": "ground_truth_strategy_comparison.csv",
                "threshold_sensitivity": "ground_truth_threshold_sensitivity.csv",
                "horizon_sensitivity": "ground_truth_horizon_sensitivity.csv",
                "per_cutoff_stability": "ground_truth_per_cutoff_stability.csv",
                "temporal_transitions": "ground_truth_temporal_transitions.csv",
                "discriminability": "ground_truth_discriminability.csv",
                "report": "ground_truth_validation_report.md",
            },
        },
        "operating_mode": {
            "contract": {
                "schema_version": operating_mode_policy["schema_version"],
                "path": str(args.operating_mode_policy.resolve()),
                "sha256": operating_mode_policy_hash,
            },
            "selection": operating_mode_selection,
        },
        "split": split_audit,
        "profile": asdict(profile),
        "validation_metrics": validation_benchmark.to_dict(orient="records"),
        "test_metrics": test_benchmark.to_dict(orient="records"),
        "selected_test_metrics": selected_test_metrics,
        "calibration_metrics": calibration_metrics,
        "bootstrap_cutoff_ci": {metric: {"lower": values[0], "upper": values[1]} for metric, values in ci.items()},
        "recent60_rule": {
            "definition": "Classify from prior 60-day fulfilled quantity using the same 0/1-5/6-25/>25 thresholds.",
            "validation_metrics": validation_benchmark.loc[validation_benchmark["model"] == "Recent60Rule"].iloc[0].to_dict(),
            "test_metrics": test_benchmark.loc[test_benchmark["model"] == "Recent60Rule"].iloc[0].to_dict(),
            "paired_cutoff_comparison": paired_comparison,
        },
        "promotion_blockers": [
            "The current runtime feature contract is not identical to this benchmark feature schema.",
            "The dashboard must load this exact model and calibrator through a versioned manifest before promotion.",
            "No physical inventory/capital claim is valid without as-of-cutoff stock and cost snapshots.",
        ],
    }
    write_json(output_dir / "model_manifest.json", manifest)
    write_summary(
        output_dir / "rerun_summary.md",
        profile,
        split_audit,
        selected_name,
        operating_mode_selection,
        validation_benchmark,
        test_benchmark,
        selected_test_metrics,
        calibration_metrics,
        ci,
        paired_comparison,
        contract,
        ground_truth_summary,
    )
    log(f"Completed. Results: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"Rerun failed: {type(error).__name__}: {error}")
        raise
