"""
Test suite for Task M4-05 Global Risk Explanation (Module 04).
Verifies AC-01 through AC-12 requirements:
- Global SHAP importance & ranking by mean(|SHAP|)
- Contribution direction & positive/negative rates
- Risk-class-specific breakdowns (CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK)
- Visualization data structure (Bar chart, Comparison matrix)
- Non-causal academic interpretation & temporal safety (t <= t0)
- Reproducibility & artifact output verification
"""

import json
import os
import sys
import pandas as pd
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.global_risk_explainer import (
    GlobalRiskExplainer,
    GlobalRiskExplainerError,
    GLOBAL_DISCLAIMER
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestGlobalRiskExplainer(TestCase):

    def setUp(self):
        self.explainer = GlobalRiskExplainer()
        self.sample_features = {
            'sales_velocity_30d': 0.05,
            'sales_velocity_90d': 0.02,
            'sales_velocity_full': 0.03,
            'sales_last_30d': 1,
            'past_total_sold': 45,
            'zero_rate_90d': 0.85,
            'zero_rate_full': 0.80,
            'adi': 5.93,
            'cv2': 0.82,
            'dsls': 140,
            'forecast_7d': 0.08,
            'forecast_14d': 0.15,
            'forecast_30d': 0.30,
            'forecast_trend': -0.10,
            'demand_probability': 0.12,
            'expected_demand_daily': 0.02
        }

        self.features_df = pd.DataFrame([self.sample_features, self.sample_features, self.sample_features, self.sample_features])
        self.assessments_list = [
            {"sku": "SKU_01", "risk_class": "CRITICAL", "risk_probability": 0.95, "risk_score": 95.0},
            {"sku": "SKU_02", "risk_class": "HIGH_RISK", "risk_probability": 0.75, "risk_score": 75.0},
            {"sku": "SKU_03", "risk_class": "MEDIUM_RISK", "risk_probability": 0.45, "risk_score": 45.0},
            {"sku": "SKU_04", "risk_class": "LOW_RISK", "risk_probability": 0.15, "risk_score": 15.0}
        ]

    def test_ac01_ac02_ac03_ac04_global_statistics_and_ranking(self):
        """AC-01, AC-02, AC-03, AC-04: Global SHAP importance ranking by mean(|SHAP|), direction & rates."""
        payload = self.explainer.explain_global_population(self.features_df, self.assessments_list)

        self.assertEqual(payload["explanation_type"], "GLOBAL")
        self.assertEqual(payload["population"]["total_skus"], 4)
        self.assertTrue(len(payload["top_features"]) >= 16)

        # Check ranking descending by mean_abs_shap
        top_feats = payload["top_features"]
        for i in range(len(top_feats) - 1):
            self.assertGreaterEqual(top_feats[i]["mean_abs_shap"], top_feats[i+1]["mean_abs_shap"])
            self.assertEqual(top_feats[i]["rank"], i + 1)
            self.assertIn("positive_contribution_rate", top_feats[i])
            self.assertIn("negative_contribution_rate", top_feats[i])

    def test_ac05_risk_class_breakdowns(self):
        """AC-05: Global feature importance breakdowns per risk class."""
        payload = self.explainer.explain_global_population(self.features_df, self.assessments_list)
        rc_explanations = payload["risk_class_explanations"]

        for rc in ["CRITICAL", "HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]:
            self.assertIn(rc, rc_explanations)
            self.assertTrue(len(rc_explanations[rc]) > 0)

    def test_ac06_ac07_ac08_temporal_safety_and_non_causal_disclaimer(self):
        """AC-06, AC-07, AC-08: Temporal safety, no GT leakage & non-causal disclaimer."""
        payload = self.explainer.explain_global_population(self.features_df, self.assessments_list)

        self.assertEqual(payload["disclaimer"], GLOBAL_DISCLAIMER)
        self.assertFalse(payload["causal_claim"])

        # Verify no future leakage
        forbidden = ["fut_qty_60d", "future_sales", "DRR", "ground_truth_label"]
        for feat in payload["top_features"]:
            self.assertNotIn(feat["feature"], forbidden)

        # Test guardrail rejection on leaked dataframe
        leak_df = self.features_df.copy()
        leak_df["fut_qty_60d"] = 100
        with self.assertRaises(ExplainabilityGuardrailError):
            self.explainer.explain_global_population(leak_df, self.assessments_list)

    def test_ac09_ac10_visualization_data_and_schema(self):
        """AC-09, AC-10: Visualization data structure and machine-readable schema."""
        payload = self.explainer.explain_global_population(self.features_df, self.assessments_list)
        vis_data = payload["visualization_data"]

        self.assertIn("global_importance_bar_chart", vis_data)
        self.assertIn("risk_class_comparison_matrix", vis_data)
        self.assertTrue(len(vis_data["global_importance_bar_chart"]) > 0)
        self.assertTrue(len(vis_data["risk_class_comparison_matrix"]) > 0)

    def test_ac11_reproducibility_and_artifacts(self):
        """AC-11: Global explanation reproducibility & artifact saving."""
        p1 = self.explainer.explain_global_population(self.features_df, self.assessments_list)
        p2 = self.explainer.explain_global_population(self.features_df, self.assessments_list)

        self.assertEqual(p1["top_features"], p2["top_features"])
        self.assertEqual(p1["risk_class_explanations"], p2["risk_class_explanations"])

        # Save artifacts
        art_paths = self.explainer.save_global_artifacts(p1)
        self.assertTrue(os.path.exists(art_paths["global_risk_explanation"]))
        self.assertTrue(os.path.exists(art_paths["global_feature_importance"]))
        self.assertTrue(os.path.exists(art_paths["risk_class_feature_importance"]))
        self.assertTrue(os.path.exists(art_paths["global_explanation_validation"]))
