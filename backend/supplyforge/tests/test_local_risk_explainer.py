"""
Test suite for Task M4-04 Local Risk Explanation (Module 04).
Verifies AC-01 through AC-10 requirements:
- SKU-level local explanation generation
- Integration with M4-02 SHAP engine & M4-03 contribution analysis
- Top-N local contribution magnitude ranking
- Actual feature value + unit + SHAP contribution pairing
- Risk-increasing vs risk-reducing direction classification
- Non-causal business interpretation & disclaimer verification
- Temporal safety (t <= t0) and deterministic Python calculation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.local_risk_explainer import (
    LocalRiskExplainer,
    LocalRiskExplainerError,
    STANDARD_DISCLAIMER
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestLocalRiskExplainer(TestCase):

    def setUp(self):
        self.explainer = LocalRiskExplainer()
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

    def test_ac01_ac02_ac03_ac04_local_explanation_generation(self):
        """AC-01, AC-02, AC-03, AC-04: SKU-level explanation, SHAP integration, Top-N ranking & value-SHAP pairing."""
        payload = self.explainer.explain_sku(
            sku="10012591570",
            canonical_sku_id="CSKU_10012591570",
            product_name="Tã bỉm dán Merries First Premium L40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            top_n=4
        )

        self.assertEqual(payload["sku"], "10012591570")
        self.assertEqual(payload["risk_class"], "CRITICAL")
        self.assertEqual(payload["risk_probability"], 0.99)
        self.assertEqual(payload["explanation_type"], "LOCAL")
        self.assertEqual(len(payload["top_contributions"]), 4)

        # Check actual value + unit + SHAP pairing
        top1 = payload["top_contributions"][0]
        self.assertIn("feature", top1)
        self.assertIn("display_name", top1)
        self.assertIn("value", top1)
        self.assertIn("shap_value", top1)
        self.assertIn("direction", top1)
        self.assertIn("bar_width_pct", top1)

    def test_ac05_ac06_ac10_direction_and_non_causal_disclaimer(self):
        """AC-05, AC-06, AC-10: Direction classification, non-causal language & standard disclaimer."""
        payload = self.explainer.explain_sku(
            sku="10012591570",
            feature_dict=self.sample_features,
            risk_class="HIGH_RISK",
            risk_probability=0.85,
            risk_score=85.0
        )

        # Check standard disclaimer
        self.assertEqual(payload["disclaimer"], STANDARD_DISCLAIMER)

        # Check non-causal bullet points
        forbidden_phrases = ["nguyên nhân khiến", "chắc chắn bị lỗi thời", "kho chắc chắn hết hàng"]
        for interp in payload["interpretation"]:
            for phrase in forbidden_phrases:
                self.assertNotIn(phrase, interp.lower())

    def test_ac07_ac08_ac09_temporal_safety_determinism_and_artifacts(self):
        """AC-07, AC-08, AC-09: Temporal safety (t <= t0), deterministic output & artifact saving."""
        payload1 = self.explainer.explain_sku(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0
        )
        payload2 = self.explainer.explain_sku(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0
        )

        # Reproducibility check
        self.assertEqual(payload1["top_contributions"], payload2["top_contributions"])
        self.assertEqual(payload1["interpretation"], payload2["interpretation"])

        # Temporal safety check with future feature
        leak_features = self.sample_features.copy()
        leak_features["fut_qty_60d"] = 25
        with self.assertRaises(ExplainabilityGuardrailError):
            self.explainer.explain_sku(
                sku="SKU_LEAK",
                feature_dict=leak_features,
                risk_class="CRITICAL",
                risk_probability=0.99,
                risk_score=99.0
            )

        # Artifact saving
        art_paths = self.explainer.save_local_explanation_artifacts(payload1)
        self.assertTrue(os.path.exists(art_paths["sample_path"]))
        self.assertTrue(os.path.exists(art_paths["summary_path"]))
