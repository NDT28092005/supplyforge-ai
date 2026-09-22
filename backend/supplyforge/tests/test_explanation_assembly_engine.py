"""
Test suite for Task M4-07 Explanation Assembly (Module 04).
Verifies AC-01 through AC-10 requirements:
- Definition & structure of Canonical Risk Explanation Object
- Integration of M4-02 -> M4-06 outputs
- Clean separation between SHAP model evidence & diagnostic signals
- Proper positive/negative contribution direction retention
- Non-causal text guardrail enforcement & zero recalculation of ML metrics
- Evidence status handling (AVAILABLE, PARTIAL, UNAVAILABLE)
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

from src.analytics.explanation_assembly_engine import (
    ExplanationAssemblyEngine,
    ExplanationValidator,
    ExplanationAssemblyError
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestExplanationAssemblyEngine(TestCase):

    def setUp(self):
        self.assembly_engine = ExplanationAssemblyEngine()
        self.sample_features = {
            'sales_velocity_30d': 0.04,
            'sales_velocity_90d': 0.04,
            'sales_velocity_full': 0.03,
            'sales_last_30d': 1,
            'past_total_sold': 45,
            'zero_rate_90d': 0.82,
            'zero_rate_full': 0.80,
            'adi': 5.93,
            'cv2': 0.82,
            'dsls': 375,
            'forecast_7d': 0.08,
            'forecast_14d': 0.15,
            'forecast_30d': 0.30,
            'forecast_trend': -0.10,
            'demand_probability': 0.12,
            'expected_demand_daily': 0.02,
            'promotion_rate': 0.25
        }

    def test_ac01_ac02_ac03_ac04_canonical_object_structure(self):
        """AC-01, AC-02, AC-03, AC-04: Structural definition, M4-02->M4-06 integration & separation of SHAP vs Signals."""
        canonical_obj = self.assembly_engine.assemble_sku_explanation(
            sku="10012591570",
            canonical_sku_id="CSKU_10012591570",
            product_name="Tã bỉm dán Merries First Premium L40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            promotion_rate=0.25
        )

        self.assertTrue(ExplanationValidator.validate(canonical_obj))
        self.assertEqual(canonical_obj["sku"], "10012591570")
        self.assertEqual(canonical_obj["risk_assessment"]["risk_class"], "CRITICAL")
        self.assertEqual(canonical_obj["risk_assessment"]["risk_probability"], 0.99)
        self.assertEqual(canonical_obj["evidence_status"], "AVAILABLE")

        # Check model_evidence vs diagnostic_signals separation
        me = canonical_obj["model_evidence"]
        self.assertIn("top_positive_contributors", me)
        self.assertIn("top_negative_contributors", me)

        ds = canonical_obj["diagnostic_signals"]
        self.assertTrue(len(ds) > 0)
        self.assertIn("code", ds[0])

    def test_ac05_ac06_non_causal_guardrails_and_no_recalculation(self):
        """AC-05, AC-06: Non-causal text guardrail and immutability of upstream metrics."""
        canonical_obj = self.assembly_engine.assemble_sku_explanation(
            sku="SKU_NO_RECALC",
            feature_dict=self.sample_features,
            risk_class="HIGH_RISK",
            risk_probability=0.85,
            risk_score=85.0
        )

        self.assertEqual(canonical_obj["risk_assessment"]["risk_class"], "HIGH_RISK")
        self.assertEqual(canonical_obj["risk_assessment"]["risk_probability"], 0.85)

        # Non-causal phrase check
        prohibited = ["nguyên nhân khiến", "chắc chắn bị lỗi thời", "kho chắc chắn hết hàng"]
        for driver in canonical_obj["explanation_summary"]["risk_drivers"]:
            for phrase in prohibited:
                self.assertNotIn(phrase, driver.lower())

    def test_ac07_evidence_status_handling(self):
        """AC-07: Missing or partial evidence handling (AVAILABLE, PARTIAL)."""
        partial_features = {"sales_velocity_90d": 0.04, "adi": 5.93}
        canonical_obj = self.assembly_engine.assemble_sku_explanation(
            sku="SKU_PARTIAL",
            feature_dict=partial_features,
            risk_class="MEDIUM_RISK",
            risk_probability=0.50,
            risk_score=50.0
        )

        self.assertEqual(canonical_obj["evidence_status"], "PARTIAL")

    def test_ac08_ac09_ac10_reproducibility_and_artifacts(self):
        """AC-08, AC-09, AC-10: Reproducibility & artifact output generation for Dashboard/LLM."""
        obj1 = self.assembly_engine.assemble_sku_explanation(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0
        )
        obj2 = self.assembly_engine.assemble_sku_explanation(
            sku="SKU_REPRODUCIBLE",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0
        )

        # Reproducibility check
        self.assertEqual(obj1["risk_assessment"], obj2["risk_assessment"])
        self.assertEqual(obj1["model_evidence"], obj2["model_evidence"])
        self.assertEqual(obj1["diagnostic_signals"], obj2["diagnostic_signals"])

        # Save deliverables
        art_paths = self.assembly_engine.save_assembled_artifacts([obj1])
        self.assertTrue(os.path.exists(art_paths["risk_explanations"]))
        self.assertTrue(os.path.exists(art_paths["global_explanation"]))
        self.assertTrue(os.path.exists(art_paths["explanation_validation_report"]))
        self.assertTrue(os.path.exists(art_paths["sku_explanations_parquet"]))
