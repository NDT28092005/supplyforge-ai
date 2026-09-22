"""
Test suite for Task M6-01 Decision Support Architecture (Module 06).
Verifies AC-01 through AC-14 requirements:
- DecisionContext assembly unifying M3 (Risk), M4 (XAI), and M5 (Capital & Aging)
- Status state machine transitions (READY, NOT_READY, READY_WITH_WARNING)
- Decision constraints enforcement and strategy interface registration
- Audit metadata lineage & versioning tracking
- Deliverable artifact generation in reports/decision/
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import (
    DecisionContextBuilder,
    DecisionStatus,
    StrategyType,
    DecisionConstraints,
    DecisionSupportArchitectureError
)


class TestDecisionSupportArchitecture(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()

        self.sample_risk = {
            "sku": "SKU_1001",
            "canonical_sku_id": "CSKU_1001",
            "product_name": "Product 1",
            "category": "Mother & Baby",
            "slow_moving_risk_class": "CRITICAL",
            "risk_probability": 0.95,
            "risk_score": 95.0,
            "risk_signals": ["ZERO_SALES_30D"],
            "model_version": "3.0"
        }

        self.sample_explainability = {
            "top_shap_features": [
                {"feature_name": "dsls", "shap_value": 0.45, "feature_value": 210}
            ],
            "diagnostic_signals": ["POSSIBLE_OBSOLESCENCE"],
            "summary_text": "Zero sales in last 30 days.",
            "explanation_version": "4.0"
        }

        self.sample_capital = {
            "capital_exposure": 20000000.0,
            "inventory_value": 20000000.0,
            "risk_weighted_exposure": 20000000.0,
            "probability_adjusted_exposure": 19000000.0,
            "estimated_opportunity_cost": 1380821.92,
            "inventory_age_days": 210,
            "aging_bucket": "SEVERELY_STALE",
            "aging_risk_level": "CRITICAL_AGING",
            "aging_priority": "P1",
            "calculation_version": "5.0"
        }

    def test_ac01_ac02_ac03_ac04_ac05_ac06_context_assembly(self):
        """AC-01 to AC-06: Assembles unified DecisionContext from M3, M4, M5."""
        ctx = self.builder.build_sku_decision_context(
            risk_record=self.sample_risk,
            explainability_record=self.sample_explainability,
            capital_record=self.sample_capital,
            dataset_version="v1.0"
        )

        self.assertEqual(ctx["sku"], "SKU_1001")
        self.assertEqual(ctx["risk_context"]["risk_class"], "CRITICAL")
        self.assertEqual(ctx["explainability_context"]["diagnostic_signals"], ["POSSIBLE_OBSOLESCENCE"])
        self.assertEqual(ctx["capital_context"]["capital_exposure"], 20000000.0)
        self.assertEqual(ctx["aging_context"]["aging_bucket"], "SEVERELY_STALE")
        self.assertEqual(ctx["decision_status"], DecisionStatus.READY.value)

    def test_ac07_status_state_machine(self):
        """AC-07: Tests status transitions (READY, NOT_READY, READY_WITH_WARNING)."""
        # 1. NOT_READY test (Missing mandatory capital record)
        ctx_not_ready = self.builder.build_sku_decision_context(
            risk_record=self.sample_risk,
            capital_record=None
        )
        self.assertEqual(ctx_not_ready["decision_status"], DecisionStatus.NOT_READY.value)
        self.assertEqual(ctx_not_ready["eligible_strategies"], [])

        # 2. READY_WITH_WARNING test (Physical stock unobserved)
        cap_warn = dict(self.sample_capital)
        cap_warn["physical_stock_unobserved"] = True
        ctx_warn = self.builder.build_sku_decision_context(
            risk_record=self.sample_risk,
            capital_record=cap_warn
        )
        self.assertEqual(ctx_warn["decision_status"], DecisionStatus.READY_WITH_WARNING.value)

    def test_ac08_ac09_ac10_constraints_strategies_and_audit(self):
        """AC-08, AC-09, AC-10: Configurable constraints, 7 strategy interfaces & audit metadata."""
        custom_constraints = DecisionConstraints(
            max_discount_rate=0.25,
            min_recovery_rate=0.60,
            allowed_strategies=["DISCOUNT", "CLEARANCE"]
        )

        ctx = self.builder.build_sku_decision_context(
            risk_record=self.sample_risk,
            explainability_record=self.sample_explainability,
            capital_record=self.sample_capital,
            constraints=custom_constraints,
            dataset_version="v2.0"
        )

        self.assertEqual(ctx["constraints"]["max_discount_rate"], 0.25)
        self.assertEqual(ctx["eligible_strategies"], ["DISCOUNT", "CLEARANCE"])
        self.assertEqual(ctx["audit_metadata"]["dataset_version"], "v2.0")
        self.assertEqual(ctx["audit_metadata"]["decision_engine_version"], "6.0")

    def test_portfolio_assembly_and_artifacts(self):
        """Tests batch portfolio Context Builder & deliverable artifact generation."""
        summary_payload = self.builder.build_portfolio_decision_contexts(
            risk_records=[self.sample_risk],
            explainability_map={"SKU_1001": self.sample_explainability},
            capital_map={"SKU_1001": self.sample_capital}
        )

        self.assertEqual(summary_payload["summary"]["total_skus"], 1)
        self.assertEqual(summary_payload["summary"]["ready_skus"], 1)

        art_paths = self.builder.save_architecture_artifacts(summary_payload)
        self.assertTrue(os.path.exists(art_paths["decision_architecture_report"]))
        self.assertTrue(os.path.exists(art_paths["decision_context_validation"]))
