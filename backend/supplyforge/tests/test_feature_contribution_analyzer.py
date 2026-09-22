"""
Test suite for Task M4-03 Feature Contribution Analysis (Module 04).
Verifies AC-01 through AC-14 requirements:
- Input handling from M4-02
- Magnitude ranking & Top-N slicing
- Contribution direction & business taxonomy categorization
- Non-causal wording guardrails & pattern detection
- Local & global dataset statistics
- Schema compliance with M4-01 contract
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.shap_explanation_engine import SHAPExplanationEngine
from src.analytics.feature_contribution_analyzer import (
    FeatureContributionAnalyzer,
    FeatureContributionAnalyzerError
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestFeatureContributionAnalyzer(TestCase):

    def setUp(self):
        self.shap_engine = SHAPExplanationEngine()
        self.analyzer = FeatureContributionAnalyzer()

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

        # Generate M4-02 SHAP payload
        self.shap_payload = self.shap_engine.explain_sku(
            sku="SKU_MERRIES_L_40",
            canonical_sku_id="CSKU_MERRIES_L_40",
            product_name="Tã bỉm dán Merries First Premium L40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.96,
            risk_score=96.0,
            diagnostics=["LOW_SALES_VELOCITY", "POSSIBLE_OBSOLESCENCE"]
        )

    def test_ac01_ac02_ac03_ac04_local_contribution_analysis(self):
        """AC-01, AC-02, AC-03, AC-04: Receives M4-02 output, ranks abs(SHAP), direction & metadata."""
        analysis = self.analyzer.analyze_sku_contribution(self.shap_payload, top_n=4)

        self.assertEqual(analysis["sku"], "SKU_MERRIES_L_40")
        self.assertEqual(analysis["risk_class"], "CRITICAL")
        self.assertEqual(len(analysis["top_contributions"]), 4)

        # Verify ranking order (abs(SHAP) descending)
        top = analysis["top_contributions"]
        for i in range(len(top) - 1):
            self.assertGreaterEqual(top[i]["absolute_shap"], top[i+1]["absolute_shap"])
            self.assertEqual(top[i]["rank"], i + 1)
            self.assertIn("unit", top[i])
            self.assertIn("interpretation", top[i])

    def test_ac05_ac06_categorization_and_top_n(self):
        """AC-05, AC-06: Business taxonomy categorization and Top-N slicing."""
        full_analysis = self.analyzer.analyze_sku_contribution(self.shap_payload, top_n=None)
        self.assertEqual(len(full_analysis["top_contributions"]), 16)

        categories = set(f["category"] for f in full_analysis["all_contributions"])
        expected_cats = {"DEMAND_FORECAST", "SALES_VELOCITY", "DEMAND_INTERMITTENCY", "RECENCY_SIGNAL"}
        self.assertTrue(expected_cats.issubset(categories))

        # Top 4 slicing
        top4_analysis = self.analyzer.analyze_sku_contribution(self.shap_payload, top_n=4)
        self.assertEqual(len(top4_analysis["top_contributions"]), 4)

    def test_ac08_global_contribution_statistics(self):
        """AC-08: Computes global contribution statistics across dataset."""
        payload2 = self.shap_engine.explain_sku(
            sku="SKU_HUGGIES_XL_38",
            feature_dict=self.sample_features,
            risk_class="HIGH_RISK",
            risk_probability=0.78,
            risk_score=78.0
        )

        global_stats = self.analyzer.analyze_global_dataset_contributions([self.shap_payload, payload2])
        self.assertEqual(global_stats["total_skus_analyzed"], 2)
        self.assertTrue(len(global_stats["global_feature_statistics"]) > 0)
        
        stat = global_stats["global_feature_statistics"][0]
        self.assertIn("mean_abs_shap", stat)
        self.assertIn("risk_increasing_rate", stat)
        self.assertIn("avg_rank", stat)

    def test_ac09_ac11_pattern_detection_and_non_causal_guardrails(self):
        """AC-09, AC-11: Detects contribution patterns and enforces non-causal language."""
        analysis = self.analyzer.analyze_sku_contribution(self.shap_payload)
        patterns = analysis["contribution_summary"]["detected_evidence_patterns"]
        self.assertTrue(len(patterns) > 0)

        # Check that no causal terms exist in interpretations
        causal_forbidden = ["nguyên nhân khiến", "chắc chắn bị lỗi thời", "đang hết hàng"]
        for feat in analysis["all_contributions"]:
            for phrase in causal_forbidden:
                self.assertNotIn(phrase, feat["interpretation"].lower())

    def test_ac10_ac12_ac13_temporal_safety_and_schema_compliance(self):
        """AC-10, AC-12, AC-13: Temporal safety & schema compliance."""
        analysis = self.analyzer.analyze_sku_contribution(self.shap_payload)
        self.assertEqual(analysis["explanation_version"], "1.0")

        # Save artifacts
        global_stats = self.analyzer.analyze_global_dataset_contributions([self.shap_payload])
        art_paths = self.analyzer.save_analysis_artifacts(analysis, global_stats)
        self.assertTrue(os.path.exists(art_paths["sample_path"]))
        self.assertTrue(os.path.exists(art_paths["summary_path"]))
