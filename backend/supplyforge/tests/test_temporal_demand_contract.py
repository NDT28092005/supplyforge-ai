from __future__ import annotations

import hashlib
import json
import os
import pickle
import tempfile
from datetime import timedelta
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import TestCase
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression

from supplyforge.ml.temporal_benchmark import (
    RISK_TO_CODE,
    ground_truth_validation,
    label_absolute_future_demand,
    label_demand_retention_ratio,
    load_ground_truth_contract,
    recent_60d_rule,
)
from supplyforge.ml.temporal_operating_mode import (
    OPERATING_MODE_POLICY_PATH,
    load_operating_mode_policy,
    select_operating_mode_candidate,
)
from supplyforge.models import (
    ActionPlanRecord, ActionPlanOutcomeObservation, IntegrationConnection, IntegrationSkuDailyMetric,
    IntegrationSkuMapping, InventoryRecord, Order, OrderItem, Product, Sku, TemporalCandidatePromotionApproval,
    TemporalDemandSourceImport,
    TemporalShadowPrediction, User, Workspace,
)
from supplyforge.services.inventory_readiness import InventoryReadinessGate, InventoryReadinessReportService
from supplyforge.services.action_outcome_reporting import ActionOutcomeEvidenceService
from supplyforge.services.action_outcome_reconciliation import ActionOutcomeReconciliationService
from supplyforge.services.erp_inventory_snapshot import ErpInventorySnapshotProjectionService
from supplyforge.services.temporal_candidate_model import (
    TemporalCandidateModelService, TemporalCandidateUnavailable,
)
from supplyforge.services.temporal_feature_service import CONTRACT_PATH, TemporalFeatureService
from supplyforge.services.temporal_feature_parity import (
    ParityConfiguration, TemporalFeatureParityService,
)
from supplyforge.services.temporal_promotion_governance import (
    PROMOTION_POLICY_PATH, TemporalPromotionGovernanceService, file_sha256 as promotion_policy_sha256,
    load_promotion_policy,
)
from supplyforge.services.temporal_shadow_monitoring import TemporalShadowMonitoringService
from supplyforge.services.temporal_source_ingestion import TemporalSourceIngestionService


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TemporalDemandContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="temporal-contract@example.test",
            password_hash="not-used",
            status=User.STATUS_ACTIVE,
        )
        self.workspace = Workspace.objects.create(name="Temporal contract", owner=self.user)
        self.user_id = str(self.user.id)
        self.reference = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)

    def _order(
        self,
        suffix,
        *,
        days_ago,
        quantity=1,
        status="COMPLETED",
        returned=None,
        accounting=True,
        verified=True,
        sku="SKU-A",
        workspace=None,
    ):
        timestamp = self.reference - timedelta(days=days_ago)
        workspace = workspace or self.workspace
        order = Order.objects.create(
            id=f"temporal-{suffix}",
            user_id=self.user_id,
            workspace=workspace,
            order_id=f"TEMP-{suffix}",
            status=status,
            return_identifier=returned,
            is_accounting=accounting,
            demand_eligibility_verified=verified,
            source_event_at=timestamp,
            created_at=timestamp,
        )
        OrderItem.objects.create(
            order=order,
            sku="RAW-SKU-A",
            canonical_sku=sku,
            quantity=quantity,
        )

    def test_runtime_features_exclude_returned_non_accounting_and_future_events(self):
        for day in range(10):
            self._order(f"valid-{day}", days_ago=day)
        self._order("returned", days_ago=1, quantity=100, returned="RETURN-1")
        self._order("non-accounting", days_ago=1, quantity=100, accounting=False)
        self._order("not-completed", days_ago=1, quantity=100, status="PENDING")
        self._order("unverified", days_ago=1, quantity=100, verified=False)
        self._order("future", days_ago=-1, quantity=100)

        snapshot = TemporalFeatureService().extract("SKU-A", user_id=self.user_id, as_of=self.reference)

        self.assertEqual(snapshot.historical_total_qty, 10.0)
        self.assertEqual(snapshot.values["sales_qty_7d"], 7.0)
        self.assertEqual(snapshot.values["sales_qty_30d"], 10.0)
        self.assertEqual(snapshot.values["sales_qty_60d"], 10.0)
        self.assertEqual(snapshot.values["dsls"], 0.0)
        self.assertEqual(set(snapshot.values), set(TemporalFeatureService().feature_columns))

        # A post-cutoff event cannot change the vector at this decision date.
        before = dict(snapshot.values)
        self._order("future-2", days_ago=-2, quantity=999)
        after = TemporalFeatureService().extract("SKU-A", user_id=self.user_id, as_of=self.reference)
        self.assertEqual(before, after.values)

    def test_workspace_runtime_features_exclude_another_workspace_of_same_owner(self):
        other_workspace = Workspace.objects.create(
            name="Temporal contract other workspace",
            owner=self.user,
        )
        for day in range(6):
            self._order(
                f"workspace-a-{day}",
                days_ago=day,
                quantity=1,
                sku="SKU-WORKSPACE",
                workspace=self.workspace,
            )
            self._order(
                f"workspace-b-{day}",
                days_ago=day,
                quantity=100,
                sku="SKU-WORKSPACE",
                workspace=other_workspace,
            )

        snapshot = TemporalFeatureService().extract_for_workspace(
            "SKU-WORKSPACE",
            self.workspace.id,
            as_of=self.reference,
        )

        self.assertEqual(snapshot.historical_total_qty, 6.0)
        self.assertEqual(snapshot.values["sales_qty_7d"], 6.0)

    def test_contract_has_no_pii_feature(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        prohibited = set(contract["source_policy"]["pii_columns_prohibited"])
        self.assertFalse(prohibited.intersection(contract["feature_columns"]))

    def test_recent_60d_rule_uses_documented_thresholds(self):
        import pandas as pd

        snapshots = pd.DataFrame({"sales_qty_60d": [0, 2, 10, 26]})
        predicted, probabilities = recent_60d_rule(snapshots)
        self.assertEqual(predicted.tolist(), [
            RISK_TO_CODE["CRITICAL"],
            RISK_TO_CODE["HIGH_RISK"],
            RISK_TO_CODE["MEDIUM_RISK"],
            RISK_TO_CODE["LOW_RISK"],
        ])
        self.assertTrue(np.allclose(probabilities.sum(axis=1), 1.0))

    def test_ground_truth_contract_preserves_absolute_boundaries_and_drr_as_a_comparator(self):
        contract = load_ground_truth_contract()
        absolute = label_absolute_future_demand(
            np.array([0, 1, 5, 6, 25, 26], dtype=float),
            np.array([6, 6, 6, 6, 6, 6], dtype=float),
        )
        self.assertEqual(absolute.tolist(), [0, 1, 1, 2, 2, 3])

        drr_labels, drr = label_demand_retention_ratio(
            np.array([0, 2, 30, 60], dtype=float),
            np.array([60, 60, 60, 60], dtype=float),
            np.array([60, 60, 60, 60], dtype=float),
            denominator_floor=float(contract["alternative_strategy"]["denominator_floor"]),
            high_risk_drr_max=float(contract["alternative_strategy"]["high_risk_drr_max"]),
            medium_risk_drr_max=float(contract["alternative_strategy"]["medium_risk_drr_max"]),
        )
        self.assertEqual(drr_labels.tolist(), [0, 1, 2, 3])
        self.assertTrue(np.allclose(drr, [0.0, 2 / 60, 0.5, 1.0]))

    def test_operating_mode_selects_only_validation_metrics(self):
        policy = load_operating_mode_policy()
        validation = pd.DataFrame([
            {
                "model": "BalancedWinner",
                "model_family": "ML_CANDIDATE",
                "macro_f1": 0.71,
                "balanced_accuracy": 0.70,
                "high_risk_recall": 0.88,
                "high_risk_precision": 0.91,
                "high_risk_pr_auc": 0.89,
            },
            {
                "model": "RiskAverseWinner",
                "model_family": "ML_CANDIDATE",
                "macro_f1": 0.68,
                "balanced_accuracy": 0.69,
                "high_risk_recall": 0.94,
                "high_risk_precision": 0.87,
                "high_risk_pr_auc": 0.90,
            },
            {
                "model": "Recent60Rule",
                "model_family": "DETERMINISTIC_BASELINE",
                "macro_f1": 0.99,
                "balanced_accuracy": 0.99,
                "high_risk_recall": 0.99,
                "high_risk_precision": 0.99,
                "high_risk_pr_auc": 0.99,
            },
        ])

        balanced, balanced_audit = select_operating_mode_candidate(validation, policy, "balanced")
        risk_averse, risk_averse_audit = select_operating_mode_candidate(validation, policy, "risk_averse")

        self.assertEqual(balanced, "BalancedWinner")
        self.assertEqual(risk_averse, "RiskAverseWinner")
        self.assertEqual(balanced_audit["selection_split"], "validation_only")
        self.assertTrue(risk_averse_audit["selected_model_constraints_met"])
        self.assertNotIn("Recent60Rule", {row["model"] for row in balanced_audit["validation_candidates"]})

        # Test values are intentionally contradictory, and cannot be passed to
        # the selection function. The validation decision remains unchanged.
        contradictory_test_metrics = {"BalancedWinner": 0.0, "RiskAverseWinner": 1.0}
        self.assertEqual(contradictory_test_metrics[balanced], 0.0)
        self.assertEqual(
            select_operating_mode_candidate(validation, policy, "balanced")[0],
            "BalancedWinner",
        )

    def test_ground_truth_validation_emits_per_cutoff_policy_evidence(self):
        contract = load_ground_truth_contract()
        rows = []
        for cutoff, split in [("2025-01-01", "validation"), ("2025-01-29", "test")]:
            for sku, future_qty in enumerate([0, 3, 10, 30], start=1):
                rows.append({
                    "cutoff": pd.Timestamp(cutoff),
                    "split": split,
                    "sku": f"SKU-{sku}",
                    "future_net_qty_30d": future_qty,
                    "future_net_qty_60d": future_qty,
                    "future_net_qty_90d": future_qty if split == "validation" else np.nan,
                    "historical_total_qty": 60.0,
                    "lifetime_days": 60.0,
                    "risk_label": label_absolute_future_demand(
                        np.array([future_qty], dtype=float), np.array([60.0], dtype=float)
                    )[0],
                    "sales_qty_30d": float(sku),
                    "sales_qty_60d": float(sku * 2),
                    "sales_velocity_90d": float(sku) / 90,
                    "zero_rate_90d": 1 - float(sku) / 10,
                    "dsls": float(10 - sku),
                    "adi_90d": float(sku),
                    "cv2_90d": float(sku) / 10,
                    "lifetime_velocity": 1.0,
                })
        artifacts, summary = ground_truth_validation(pd.DataFrame(rows), contract)
        self.assertEqual(len(artifacts["strategy_comparison"]), 2)
        self.assertEqual(len(artifacts["threshold_sensitivity"]), 10)
        self.assertEqual(len(artifacts["horizon_sensitivity"]), 6)
        baseline = artifacts["threshold_sensitivity"].query("policy_id == 'baseline_0_5_25'")
        self.assertTrue((baseline["label_agreement"] == 1.0).all())
        mature_horizons = artifacts["horizon_sensitivity"].query("mature_snapshot_count > 0")
        self.assertTrue((mature_horizons["mature_coverage"] == 1.0).all())
        incomplete_90d = artifacts["horizon_sensitivity"].query(
            "split == 'test' and comparison_horizon_days == 90"
        ).iloc[0]
        self.assertEqual(incomplete_90d["mature_coverage"], 0.0)
        self.assertEqual(incomplete_90d["evaluated_skus"], 0)
        self.assertEqual(summary["selected_strategy"], "absolute_future_demand")

    def test_inventory_gate_requires_explicit_as_of_snapshot(self):
        sku = Sku.objects.create(
            workspace=self.workspace,
            original_name="SKU-A",
            normalized_name="SKU-A",
        )
        not_ready = InventoryReadinessGate.evaluate(
            workspace_id=self.workspace.id, canonical_sku="SKU-A", as_of=self.reference.date()
        )
        self.assertFalse(not_ready.ready)

        InventoryRecord.objects.create(
            sku=sku,
            canonical_sku="SKU-A",
            record_date=self.reference.date(),
            available_quantity=12,
            cost_price=25,
            lifecycle_status="ACTIVE",
            as_of_verified=True,
            source_snapshot_id="warehouse-snapshot-1",
        )
        ready = InventoryReadinessGate.evaluate(
            workspace_id=self.workspace.id, canonical_sku="SKU-A", as_of=self.reference.date()
        )
        self.assertTrue(ready.ready)
        self.assertEqual(ready.capital_exposure, 300.0)

    def test_inventory_readiness_report_surfaces_missing_source_evidence_by_warehouse(self):
        sku = Sku.objects.create(
            workspace=self.workspace,
            original_name="SKU-A",
            normalized_name="SKU-A",
        )
        InventoryRecord.objects.create(
            sku=sku, canonical_sku="SKU-A", warehouse_code="WH-A",
            record_date=self.reference.date(), available_quantity=12, cost_price=25,
            lifecycle_status="ACTIVE", as_of_verified=True,
            source_snapshot_id="snapshot-wh-a", source_observed_at=self.reference,
            source_checksum="a" * 64, markdown_rate="0.1500",
        )
        InventoryRecord.objects.create(
            sku=sku, canonical_sku="SKU-A", warehouse_code="WH-B",
            record_date=self.reference.date(), available_quantity=None, cost_price=None,
            lifecycle_status="UNKNOWN", as_of_verified=False,
        )
        report = InventoryReadinessReportService.report(
            workspace_id=self.workspace.id, as_of=self.reference.date()
        )
        self.assertEqual(report["portfolio"]["snapshot_pairs"], 2)
        self.assertEqual(report["portfolio"]["ready_for_capital_claims"], 1)
        self.assertEqual(report["portfolio"]["missing_available_quantity"], 1)
        by_warehouse = {row["warehouse_code"]: row for row in report["by_warehouse"]}
        self.assertEqual(by_warehouse["WH-A"]["ready_for_capital_claims"], 1)
        self.assertEqual(by_warehouse["WH-B"]["missing_source_lineage"], 1)

    def test_action_outcome_report_separates_observed_and_missing_values(self):
        observed = ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, campaign_name="Observed", sku="SKU-A",
            strategy="DISCOUNT", owner="merchant", start_date=self.reference.date(),
            status="COMPLETED", expected_recovery_value=100, actual_recovery_value=80,
            expected_sales_value=120, actual_sales_value=90,
            expected_units_sold=10, actual_units_sold=9, outcome_recorded_at=self.reference,
        )
        self.assertEqual(observed.status, "COMPLETED")
        ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, campaign_name="Missing", sku="SKU-B",
            strategy="BUNDLE", owner="merchant", start_date=self.reference.date(), status="COMPLETED",
        )
        report = ActionOutcomeEvidenceService.report(workspace_id=self.workspace.id)
        self.assertEqual(report["status"], "PARTIALLY_OBSERVED")
        self.assertEqual(report["portfolio"]["completed_plans"], 2)
        self.assertEqual(report["portfolio"]["plans_with_recorded_outcome"], 1)
        self.assertEqual(report["portfolio"]["observed_actual_recovery_total"], 80)
        self.assertEqual(report["portfolio"]["missing_recovery_outcome"], 1)

    def test_erp_inventory_projection_and_action_observation_preserve_lineage(self):
        product = Product.objects.create(
            id="erp-product-001", user_id=self.user_id, third_party_id="erp-product-001",
            item_sku="ERP-SKU-A", canonical_sku="SKU-A", product_name="ERP SKU A", active_on_web=True,
        )
        connection = IntegrationConnection.objects.create(
            workspace=self.workspace, provider="ODOO", display_name="Test ERP",
            status="ACTIVE", base_url="http://odoo.test", external_database="test",
        )
        mapping = IntegrationSkuMapping.objects.create(
            connection=connection, external_sku="ERP-SKU-A", canonical_sku="SKU-A",
            canonical_product=product, status="CONFIRMED", mapping_method="MANUAL",
        )
        start = self.reference.date() - timedelta(days=7)
        IntegrationSkuDailyMetric.objects.create(
            connection=connection, external_sku=mapping.external_sku, warehouse_id="WH-A",
            metric_date=start, on_hand_quantity=10, unit_cost=5, unit_price=12,
            sales_quantity=0, returned_quantity=0, receipt_quantity=0, revenue=0,
        )
        # An outcome is reportable only with continuous daily coverage.  Keep
        # explicit zero days rather than treating absent ERP rows as zero.
        for offset in range(1, 7):
            IntegrationSkuDailyMetric.objects.create(
                connection=connection, external_sku=mapping.external_sku, warehouse_id="WH-A",
                metric_date=start + timedelta(days=offset), on_hand_quantity=10, unit_cost=5, unit_price=12,
                sales_quantity=0, returned_quantity=0, receipt_quantity=0, revenue=0,
            )
        IntegrationSkuDailyMetric.objects.create(
            connection=connection, external_sku=mapping.external_sku, warehouse_id="WH-A",
            metric_date=self.reference.date(), on_hand_quantity=4, unit_cost=5, unit_price=12,
            sales_quantity=6, returned_quantity=0, receipt_quantity=0, revenue=72,
        )
        snapshot_summary = ErpInventorySnapshotProjectionService.refresh(connection)
        self.assertEqual(snapshot_summary["projected_inventory_records"], 1)
        inventory = InventoryRecord.objects.get(canonical_sku="SKU-A", warehouse_code="WH-A")
        self.assertTrue(inventory.as_of_verified)
        self.assertTrue(inventory.source_snapshot_id)
        self.assertEqual(inventory.source_lineage_json["provider"], "ODOO")

        plan = ActionPlanRecord.objects.create(
            workspace_id=self.workspace.id, campaign_name="ERP observed", sku="SKU-A", strategy="DISCOUNT",
            owner="merchant", start_date=start, due_date=self.reference.date(), status="COMPLETED",
            completed_at=self.reference,
        )
        reconciliation = ActionOutcomeReconciliationService.reconcile_connection(
            connection=connection, as_of=self.reference.date(),
        )
        self.assertEqual(reconciliation["observed"], 1)
        observation = ActionPlanOutcomeObservation.objects.get(plan=plan)
        self.assertEqual(observation.status, "OBSERVED")
        self.assertEqual(float(observation.observed_net_units_sold), 6.0)
        self.assertEqual(float(observation.observed_inventory_change), -6.0)
        report = ActionOutcomeEvidenceService.report(workspace_id=self.workspace.id)
        self.assertEqual(report["erp_reconciled_observations"]["observed"], 1)
        self.assertEqual(report["erp_reconciled_observations"]["observed_sales_value"], 72.0)

    def test_promotion_policy_requires_mature_shadow_evidence(self):
        policy = load_promotion_policy()
        cohorts = []
        for offset in range(3):
            cohorts.append({
                "workspace_id": self.workspace.id,
                "model_version": "promotion-test-v1",
                "evaluated_skus": 50,
                "actual_high_risk_count": 20,
                "predicted_high_risk_count": 20,
                "high_risk_precision": 0.8,
                "high_risk_recall": 0.8,
                "high_risk_brier": 0.1,
                "high_risk_ece": 0.05,
                "ranking_k": 3,
                "precision_at_5pct": 1.0,
                "high_risk_probability_psi": None if offset == 0 else 0.1,
                "drift_status": "INSUFFICIENT_REFERENCE" if offset == 0 else "HEALTHY",
            })
        report = {"quality": {"cohorts": cohorts}}
        approved = TemporalPromotionGovernanceService.evaluate_shadow_report(
            report=report, workspace_id=self.workspace.id, model_version="promotion-test-v1", policy=policy,
        )
        self.assertTrue(approved["eligible"])
        stricter = {**policy, "minimum_high_risk_recall": 0.9}
        rejected = TemporalPromotionGovernanceService.evaluate_shadow_report(
            report=report, workspace_id=self.workspace.id, model_version="promotion-test-v1", policy=stricter,
        )
        self.assertFalse(rejected["eligible"])

    def test_inventory_and_action_evidence_endpoints_are_available(self):
        inventory_response = self.client.get("/api/v1/inventory/readiness/")
        self.assertEqual(inventory_response.status_code, 200)
        self.assertEqual(inventory_response.json()["workspace_id"], self.workspace.id)
        outcome_response = self.client.get("/api/v1/action-plans/outcome-report/")
        self.assertEqual(outcome_response.status_code, 200)
        self.assertEqual(outcome_response.json()["status"], "NO_COMPLETED_ACTIONS")

    def test_shadow_outcomes_wait_for_a_complete_window_and_report_by_cutoff(self):
        mature_cutoff = self.reference - timedelta(days=90)
        prediction = {
            "serving_state": "SHADOW",
            "risk_class": "HIGH_RISK",
            "risk_probability": 0.8,
            "raw_high_risk_probability": 0.75,
            "class_probabilities": {"CRITICAL": 0.1, "HIGH_RISK": 0.7, "MEDIUM_RISK": 0.1, "LOW_RISK": 0.1},
            "model_version": "temporal-shadow-test-v1",
            "feature_schema_version": "temporal-demand-risk-v1",
            "ground_truth_schema_version": "temporal-demand-ground-truth-v2",
            "ground_truth_thresholds": {
                "critical_future_quantity": 0,
                "high_risk_future_quantity_max": 5,
                "medium_risk_future_quantity_max": 25,
            },
            "operating_mode": "risk_averse",
            "decision_cutoff": mature_cutoff.isoformat(),
            "feature_values": {"sales_qty_60d": 3.0},
            "data_provenance": {"source": "runtime_verified_fulfilled_order_events", "canonical_sku": "SKU-A"},
        }
        first = TemporalShadowMonitoringService.record_prediction(
            workspace_id=self.workspace.id, prediction=prediction
        )
        duplicate = TemporalShadowMonitoringService.record_prediction(
            workspace_id=self.workspace.id, prediction=prediction
        )
        self.assertEqual(first.id, duplicate.id)
        self.assertEqual(TemporalShadowPrediction.objects.count(), 1)

        # Six verified units in the fully future window produce MEDIUM_RISK.
        self._order("shadow-outcome", days_ago=40, quantity=6)
        maturity = TemporalShadowMonitoringService.mature_outcomes(
            workspace_id=self.workspace.id, as_of=self.reference
        )
        self.assertEqual(maturity["matured_now"], 1)
        first.refresh_from_db()
        self.assertEqual(first.actual_future_fulfilled_quantity, 6.0)
        self.assertEqual(first.actual_risk_class, "MEDIUM_RISK")

        prediction["decision_cutoff"] = (self.reference - timedelta(days=10)).isoformat()
        TemporalShadowMonitoringService.record_prediction(workspace_id=self.workspace.id, prediction=prediction)
        maturity = TemporalShadowMonitoringService.mature_outcomes(
            workspace_id=self.workspace.id, as_of=self.reference
        )
        self.assertEqual(maturity["matured_now"], 0)
        self.assertEqual(maturity["immature_pending"], 1)

        report = TemporalShadowMonitoringService.quality_report(workspace_id=self.workspace.id)
        self.assertEqual(report["matured_prediction_count"], 1)
        self.assertEqual(report["immature_prediction_count"], 1)
        self.assertEqual(report["cohorts"][0]["operating_mode"], "risk_averse")
        self.assertEqual(report["cohorts"][0]["ranking_k"], 1)
        self.assertEqual(report["cohorts"][0]["drift_status"], "INSUFFICIENT_REFERENCE")
        self.assertGreater(
            TemporalShadowMonitoringService._population_stability_index(
                [index / 100 for index in range(20)], [0.9] * 20
            ),
            TemporalShadowMonitoringService.DRIFT_ALERT_PSI,
        )

    def test_candidate_manifest_validates_model_and_contract_checksums(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        feature_count = len(contract["feature_columns"])
        X = pd.DataFrame(np.eye(4, feature_count), columns=contract["feature_columns"])
        y = np.array([0, 1, 2, 3])
        model = RandomForestClassifier(n_estimators=4, random_state=42).fit(X, y)
        calibrator = IsotonicRegression(out_of_bounds="clip").fit([0.0, 0.5, 1.0], [0, 0, 1])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "selected_candidate_model.pkl"
            calibrator_path = root / "selected_high_risk_isotonic_calibrator.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)
            with calibrator_path.open("wb") as handle:
                pickle.dump(calibrator, handle)
            operating_policy_path = root / "operating_mode_policy.json"
            operating_policy_path.write_bytes(OPERATING_MODE_POLICY_PATH.read_bytes())
            manifest = {
                "artifact_status": "STAGED_FOR_GOVERNED_SERVING",
                "selected_model": "RandomForest",
                "feature_contract": {
                    "schema_version": contract["schema_version"],
                    "feature_columns": contract["feature_columns"],
                    "class_order": ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"],
                    "sha256": sha256(CONTRACT_PATH),
                },
                "artifacts": {
                    "model": {"path": model_path.name, "sha256": sha256(model_path)},
                    "high_risk_calibrator": {"path": calibrator_path.name, "sha256": sha256(calibrator_path)},
                },
                "ground_truth": {
                    "contract": {
                        "schema_version": "temporal-demand-ground-truth-v2",
                        "status": "FROZEN_APPROVED",
                    },
                },
                "source": {"sha256": "a" * 64},
                "operating_mode": {
                    "contract": {
                        "schema_version": "temporal-demand-operating-mode-v1",
                        "path": operating_policy_path.name,
                        "sha256": sha256(operating_policy_path),
                    },
                    "selection": {
                        "selection_split": "validation_only",
                        "mode": "balanced",
                        "selected_model": "RandomForest",
                    },
                },
            }
            parity_report_path = root / "temporal_feature_parity_report.json"
            parity_report = {
                "schema_version": "temporal-feature-parity-v1",
                "status": "PASSED",
                "benchmark": {"manifest_sha256": "b" * 64, "source_sha256": "a" * 64},
                "workspace_id": self.workspace.id,
                "feature_contract": {
                    "sha256": sha256(CONTRACT_PATH),
                    "feature_columns": contract["feature_columns"],
                },
                "comparison": {
                    "feature_value_comparisons": feature_count,
                    "mismatch_count": 0,
                    "extraction_error_count": 0,
                },
            }
            parity_report_path.write_text(json.dumps(parity_report), encoding="utf-8")
            manifest["serving"] = {
                "state": "ACTIVE",
                "model_version": "temporal-test-v1",
                "runtime_feature_parity_verified": True,
                "runtime_feature_parity": {
                    "schema_version": "temporal-feature-parity-v1",
                    "report_path": parity_report_path.name,
                    "report_sha256": sha256(parity_report_path),
                    "benchmark_manifest_sha256": "b" * 64,
                    "source_sha256": "a" * 64,
                    "feature_contract_sha256": sha256(CONTRACT_PATH),
                    "workspace_id": self.workspace.id,
                },
            }
            approval = TemporalCandidatePromotionApproval.objects.create(
                workspace=self.workspace,
                model_version="temporal-test-v1",
                selected_model="RandomForest",
                benchmark_manifest_sha256="b" * 64,
                source_sha256="a" * 64,
                feature_contract_sha256=sha256(CONTRACT_PATH),
                promotion_policy_sha256=promotion_policy_sha256(PROMOTION_POLICY_PATH),
                shadow_report_sha256="c" * 64,
                shadow_quality_json={"eligible": True},
                approved_by="test-governance",
                approval_reference="TEST-APPROVAL",
            )
            manifest["serving"]["promotion_approval"] = {
                "id": str(approval.id),
                "workspace_id": self.workspace.id,
                "model_version": "temporal-test-v1",
                "benchmark_manifest_sha256": "b" * 64,
                "promotion_policy_sha256": promotion_policy_sha256(PROMOTION_POLICY_PATH),
                "shadow_report_sha256": "c" * 64,
                "approval_reference": "TEST-APPROVAL",
            }
            manifest_path = root / "model_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            candidate = TemporalCandidateModelService(manifest_path)
            self.assertTrue(candidate.status().available)
            for day in range(10):
                self._order(f"candidate-{day}", days_ago=day)
            prediction = candidate.predict(
                "SKU-A", user_id=self.user_id, workspace_id=self.workspace.id, as_of=self.reference,
            )
            self.assertIn(prediction["risk_class"], {"CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"})
            self.assertEqual(prediction["serving_state"], "ACTIVE")
            with self.assertRaises(TemporalCandidateUnavailable):
                candidate.predict("SKU-A", user_id=self.user_id, workspace_id=self.workspace.id + 1, as_of=self.reference)
            approval.status = TemporalCandidatePromotionApproval.STATUS_REVOKED
            approval.save(update_fields=["status"])
            self.assertFalse(TemporalCandidateModelService(manifest_path).status().available)
            approval.status = TemporalCandidatePromotionApproval.STATUS_APPROVED
            approval.save(update_fields=["status"])
            from supplyforge.services.shap_service import ShapExplanationService
            vector = np.array([[prediction["feature_values"][name] for name in contract["feature_columns"]]])
            with patch.dict(os.environ, {"TEMPORAL_DEMAND_MODEL_MANIFEST": str(manifest_path)}):
                contributions, additivity = ShapExplanationService._temporal_tree_shap({
                    "feature_vector": vector,
                    "prediction": {"raw_probability": prediction["raw_high_risk_probability"]},
                })
            self.assertTrue(additivity["passed"])
            self.assertTrue(contributions)

            manifest["ground_truth"]["contract"]["status"] = "CANDIDATE_PENDING_REVALIDATION"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(TemporalCandidateModelService(manifest_path).status().available)

            manifest["ground_truth"]["contract"]["status"] = "FROZEN_APPROVED"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            model_path.write_bytes(b"tampered")
            self.assertFalse(TemporalCandidateModelService(manifest_path).status().available)

            # A staged candidate cannot silently change the decision posture
            # that selected its model.
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)
            manifest["artifacts"]["model"]["sha256"] = sha256(model_path)
            manifest["operating_mode"]["selection"]["selection_split"] = "test"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(TemporalCandidateModelService(manifest_path).status().available)

    def test_orders_full_adapter_persists_only_verified_demand_without_pii(self):
        headers = ["_id", "orderId", "status", "time", "returnId", "notCaculateMoney", "warehouse", "data"]
        fulfilled = {
            "_id": "raw-accepted",
            "orderId": "SOURCE-1",
            "status": "COMPLETED",
            "time": self.reference.strftime("%Y-%m-%d %H:%M:%S"),
            "returnId": "",
            "notCaculateMoney": 0,
            "warehouse": "WH-A",
            "data": json.dumps({"item_list": [{
                "model_sku": "SOURCE-SKU", "model_quantity_purchased": 6,
                "item_name": "Safe product", "model_discounted_price": 100,
            }]}),
        }
        returned = {**fulfilled, "_id": "raw-returned", "orderId": "SOURCE-2", "returnId": "RETURN-2"}
        import csv
        import io

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.zip"
            contents = io.StringIO()
            writer = csv.DictWriter(contents, fieldnames=headers)
            writer.writeheader()
            writer.writerow(fulfilled)
            writer.writerow(returned)
            with ZipFile(source, "w") as archive:
                archive.writestr("orders.csv", contents.getvalue())
            result = TemporalSourceIngestionService.import_zip(
                source=source, workspace_id=self.workspace.id, chunk_size=1
            )

        self.assertEqual(result.retained_orders, 1)
        order = Order.objects.get(order_id="SOURCE-1")
        item = order.items.get()
        self.assertTrue(order.demand_eligibility_verified)
        self.assertEqual(order.status, "COMPLETED")
        self.assertIsNone(order.buyer_user_name)
        self.assertIsNone(order.data)
        self.assertEqual(item.canonical_sku, "SOURCE-SKU")
        source_import = TemporalDemandSourceImport.objects.get(workspace=self.workspace, is_current=True)
        self.assertEqual(source_import.retained_orders, 1)
        self.assertEqual(source_import.feature_contract_sha256, sha256(CONTRACT_PATH))

    def test_feature_parity_compares_runtime_vector_with_benchmark_snapshot(self):
        for day in range(10):
            self._order(f"parity-{day}", days_ago=day, quantity=day + 1)
        snapshot = TemporalFeatureService().extract("SKU-A", user_id=self.user_id, as_of=self.reference)
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "orders_full.zip"
            source.write_bytes(b"synthetic temporal source")
            source_hash = sha256(source)
            TemporalDemandSourceImport.objects.create(
                workspace=self.workspace,
                source_sha256=source_hash,
                source_name=source.name,
                feature_contract_sha256=sha256(CONTRACT_PATH),
                retained_orders=10,
                retained_items=10,
                is_current=True,
            )
            manifest = {
                "artifact_status": "EVALUATION_CANDIDATE_ONLY",
                "feature_contract": {
                    "sha256": sha256(CONTRACT_PATH),
                    "feature_columns": contract["feature_columns"],
                },
                "source": {"sha256": source_hash},
                "selected_model": "RandomForest",
            }
            manifest_path = root / "model_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            row = {
                "split": "train",
                "cutoff": self.reference,
                "sku": "SKU-A",
                **snapshot.values,
            }
            pd.DataFrame([row]).to_parquet(root / "risk_snapshots.parquet", index=False)
            report = TemporalFeatureParityService.verify(
                workspace_id=self.workspace.id,
                benchmark_dir=root,
                source=source,
                configuration=ParityConfiguration(
                    splits=("train",), cutoffs_per_split=1, skus_per_cutoff=1,
                ),
            )
            self.assertEqual(report["status"], "PASSED")
            self.assertEqual(report["comparison"]["feature_value_comparisons"], len(snapshot.values))

            row["sales_qty_30d"] = 999.0
            pd.DataFrame([row]).to_parquet(root / "risk_snapshots.parquet", index=False)
            failed = TemporalFeatureParityService.verify(
                workspace_id=self.workspace.id,
                benchmark_dir=root,
                source=source,
                configuration=ParityConfiguration(
                    splits=("train",), cutoffs_per_split=1, skus_per_cutoff=1,
                ),
            )
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(failed["comparison"]["mismatch_count"], 1)

    def test_stage_requires_and_copies_checksum_bound_parity_evidence(self):
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        feature_count = len(contract["feature_columns"])
        X = pd.DataFrame(np.eye(4, feature_count), columns=contract["feature_columns"])
        model = RandomForestClassifier(n_estimators=4, random_state=42).fit(X, np.array([0, 1, 2, 3]))
        calibrator = IsotonicRegression(out_of_bounds="clip").fit([0.0, 0.5, 1.0], [0, 0, 1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benchmark"
            destination = Path(directory) / "staged"
            root.mkdir()
            model_path = root / "selected_candidate_model.pkl"
            calibrator_path = root / "selected_high_risk_isotonic_calibrator.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)
            with calibrator_path.open("wb") as handle:
                pickle.dump(calibrator, handle)
            manifest = {
                "artifact_status": "EVALUATION_CANDIDATE_ONLY",
                "selected_model": "RandomForest",
                "feature_contract": {
                    "schema_version": contract["schema_version"],
                    "feature_columns": contract["feature_columns"],
                    "class_order": ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"],
                    "sha256": sha256(CONTRACT_PATH),
                },
                "artifacts": {
                    "model": {"path": model_path.name, "sha256": sha256(model_path)},
                    "high_risk_calibrator": {"path": calibrator_path.name, "sha256": sha256(calibrator_path)},
                },
                "source": {"sha256": "c" * 64},
                "operating_mode": {
                    "contract": {
                        "schema_version": "temporal-demand-operating-mode-v1",
                        "path": str(OPERATING_MODE_POLICY_PATH),
                        "sha256": sha256(OPERATING_MODE_POLICY_PATH),
                    },
                    "selection": {
                        "selection_split": "validation_only", "mode": "balanced", "selected_model": "RandomForest",
                    },
                },
            }
            manifest_path = root / "model_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            parity_path = root / "parity.json"
            parity_path.write_text(json.dumps({
                "schema_version": "temporal-feature-parity-v1", "status": "PASSED",
                "benchmark": {"manifest_sha256": sha256(manifest_path), "source_sha256": "c" * 64},
                "workspace_id": self.workspace.id,
                "feature_contract": {"sha256": sha256(CONTRACT_PATH), "feature_columns": contract["feature_columns"]},
                "comparison": {"feature_value_comparisons": feature_count, "mismatch_count": 0, "extraction_error_count": 0},
            }), encoding="utf-8")
            call_command(
                "stage_temporal_demand_candidate", root,
                destination_dir=destination, model_version="temporal-parity-test-v1",
                parity_report=parity_path,
            )
            staged_manifest = json.loads((destination / "model_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue((destination / "temporal_feature_parity_report.json").is_file())
            self.assertEqual(staged_manifest["serving"]["runtime_feature_parity"]["report_sha256"], sha256(destination / "temporal_feature_parity_report.json"))
            self.assertTrue(TemporalCandidateModelService(destination / "model_manifest.json").status().available)
            with self.assertRaises(CommandError):
                call_command(
                    "stage_temporal_demand_candidate", root,
                    destination_dir=Path(directory) / "active-without-approval",
                    model_version="temporal-parity-test-v1",
                    parity_report=parity_path,
                    state="ACTIVE",
                    approve_active=True,
                )
