"""
Test suite for Task M4-02 SHAP Engine Integration (Module 04).
Verifies AC-01 through AC-14 requirements:
- Model integration & feature schema consistency
- Single-SKU and Batch SHAP explanations
- Class-specific SHAP values across 4 risk classes
- Absolute contribution & direction determination
- Temporal safety guardrails & error handling
- Reproducibility
"""

import json
import os
import sys
import numpy as np
import pandas as pd
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.shap_explanation_engine import (
    SHAPExplanationEngine,
    SHAPExplanationEngineError
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestSHAPExplanationEngine(TestCase):

    def setUp(self):
        self.engine = SHAPExplanationEngine()
        self.sample_features = {
            'sales_velocity_30d': 0.05,
            'sales_velocity_90d': 0.02,
            'sales_velocity_full': 0.03,
            'sales_last_30d': 1,
            'past_total_sold': 45,
            'zero_rate_90d': 0.85,
            'zero_rate_full': 0.80,
            'adi': 1.6,
            'cv2': 0.55,
            'dsls': 140,
            'forecast_7d': 0.08,
            'forecast_14d': 0.15,
            'forecast_30d': 0.30,
            'forecast_trend': -0.10,
            'demand_probability': 0.12,
            'expected_demand_daily': 0.02
        }

    def test_ac01_ac02_ac03_model_integration_and_single_sku(self):
        """AC-01, AC-02, AC-03: Model integration, feature schema consistency & local explanation."""
        payload = self.engine.explain_sku(
            sku="SKU_MERRIES_L_40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.96,
            risk_score=96.0,
            product_name="Tã bỉm dán Merries First Premium L40"
        )

        self.assertEqual(payload["sku"], "SKU_MERRIES_L_40")
        self.assertEqual(payload["risk_class"], "CRITICAL")
        self.assertEqual(payload["risk_probability"], 0.96)
        self.assertEqual(payload["explanation"]["method"], "SHAP")
        self.assertEqual(payload["explanation"]["model"], "XGBoost")
        self.assertTrue(len(payload["explanation"]["features"]) > 0)

    def test_ac04_ac05_class_specific_explanations(self):
        """AC-04, AC-05: Supports all 4 risk classes with class-specific SHAP values."""
        for r_class in ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]:
            payload = self.engine.explain_sku(
                sku=f"SKU_{r_class}",
                feature_dict=self.sample_features,
                risk_class=r_class,
                risk_probability=0.50,
                risk_score=50.0
            )
            self.assertEqual(payload["risk_class"], r_class)
            self.assertIn("features", payload["explanation"])

    def test_ac06_ac07_ac08_contribution_direction_and_ranking(self):
        """AC-06, AC-07, AC-08: Absolute contribution, direction, and ranking descending."""
        payload = self.engine.explain_sku(
            sku="SKU_RANK_TEST",
            feature_dict=self.sample_features,
            risk_class="HIGH_RISK",
            risk_probability=0.82,
            risk_score=82.0
        )

        features = payload["explanation"]["features"]
        self.assertTrue(len(features) >= 16)

        # Check ranking order
        for idx in range(len(features) - 1):
            curr_abs = abs(features[idx]["shap_value"])
            next_abs = abs(features[idx + 1]["shap_value"])
            self.assertGreaterEqual(curr_abs, next_abs)
            self.assertEqual(features[idx]["rank"], idx + 1)
            self.assertIn(features[idx]["direction"], ["INCREASES_RISK", "DECREASES_RISK", "NEUTRAL"])

    def test_ac09_ac10_canonical_payload_and_no_future_leakage(self):
        """AC-09, AC-10: Canonical payload emission and blocking of future leakage features."""
        payload = self.engine.explain_sku(
            sku="SKU_SCHEMA_TEST",
            feature_dict=self.sample_features,
            risk_class="MEDIUM_RISK",
            risk_probability=0.45,
            risk_score=45.0
        )

        self.assertEqual(payload["explanation_version"], "1.0")
        
        # Verify no future features exist in payload
        forbidden = ["fut_qty_60d", "future_sales", "DRR", "ground_truth_label"]
        for feat in payload["explanation"]["features"]:
            self.assertNotIn(feat["feature_name"], forbidden)

        # Passing future feature vector must raise ExplainabilityGuardrailError
        leak_df = pd.DataFrame([self.sample_features])
        leak_df["fut_qty_60d"] = 10
        with self.assertRaises(ExplainabilityGuardrailError):
            self.engine.validate_feature_vector(leak_df)

    def test_ac12_batch_explanation(self):
        """AC-12: Efficient batch explanation across multiple SKUs."""
        features_df = pd.DataFrame([self.sample_features, self.sample_features, self.sample_features])
        assessments_list = [
            {"sku": "SKU_BATCH_1", "risk_class": "CRITICAL", "risk_probability": 0.95, "risk_score": 95.0},
            {"sku": "SKU_BATCH_2", "risk_class": "HIGH_RISK", "risk_probability": 0.75, "risk_score": 75.0},
            {"sku": "SKU_BATCH_3", "risk_class": "LOW_RISK", "risk_probability": 0.15, "risk_score": 15.0}
        ]

        payloads = self.engine.explain_batch(features_df, assessments_list)
        self.assertEqual(len(payloads), 3)
        self.assertEqual(payloads[0]["sku"], "SKU_BATCH_1")
        self.assertEqual(payloads[1]["sku"], "SKU_BATCH_2")
        self.assertEqual(payloads[2]["sku"], "SKU_BATCH_3")

        # Save artifacts verification
        artifacts = self.engine.save_explanation_artifacts(payloads)
        self.assertTrue(os.path.exists(artifacts["summary_path"]))
        self.assertTrue(os.path.exists(artifacts["sample_path"]))

    def test_ac13_validation_and_error_handling(self):
        """AC-13: Validation and error handling for missing features and invalid risk classes."""
        invalid_class_features = self.sample_features.copy()
        with self.assertRaises(SHAPExplanationEngineError):
            self.engine.explain_sku(
                sku="SKU_ERR",
                feature_dict=invalid_class_features,
                risk_class="INVALID_CLASS",
                risk_probability=0.5,
                risk_score=50.0
            )

        incomplete_features = self.sample_features.copy()
        del incomplete_features["sales_velocity_90d"]
        with self.assertRaises(SHAPExplanationEngineError):
            self.engine.explain_sku(
                sku="SKU_ERR2",
                feature_dict=incomplete_features,
                risk_class="CRITICAL",
                risk_probability=0.9,
                risk_score=90.0
            )

    def test_ac14_reproducibility(self):
        """AC-14: Explanations are reproducible across identical runs."""
        payload1 = self.engine.explain_sku(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.96,
            risk_score=96.0
        )
        payload2 = self.engine.explain_sku(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.96,
            risk_score=96.0
        )

        f1 = payload1["explanation"]["features"]
        f2 = payload2["explanation"]["features"]
        self.assertEqual(len(f1), len(f2))
        for i in range(len(f1)):
            self.assertEqual(f1[i]["feature_name"], f2[i]["feature_name"])
            self.assertEqual(f1[i]["shap_value"], f2[i]["shap_value"])
            self.assertEqual(f1[i]["rank"], f2[i]["rank"])
