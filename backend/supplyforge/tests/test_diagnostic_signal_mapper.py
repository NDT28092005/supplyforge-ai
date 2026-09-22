"""
Test suite for Task M4-06 Diagnostic Signal Mapping (Module 04).
Verifies AC-01 through AC-12 requirements:
- Implementation of all 5 in-scope diagnostic rules
- Deterministic Python execution & traceable evidence pairing
- Risk prediction immutability (does not modify risk_class/score)
- Terminology guardrails (POSSIBLE_OBSOLESCENCE, POSSIBLE_STOCKOUT_EFFECT)
- Non-causal business interpretation & artifact generation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.diagnostic_signal_mapper import (
    DiagnosticSignalMapper,
    DiagnosticSignalMapperError,
    TERMINOLOGY_DISCLAIMER
)
from src.analytics.explainability_architecture import ExplainabilityGuardrailError


class TestDiagnosticSignalMapper(TestCase):

    def setUp(self):
        self.mapper = DiagnosticSignalMapper()
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

    def test_ac01_ac02_ac03_ac04_individual_diagnostic_rules(self):
        """AC-01, AC-02, AC-03, AC-04: Verifies all 5 rules evaluate deterministically with traceable evidence."""
        payload = self.mapper.evaluate_sku_signals(
            sku="10012591570",
            canonical_sku_id="CSKU_10012591570",
            product_name="Tã bỉm dán Merries First Premium L40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            promotion_rate=0.25,
            active_30d=True
        )

        active = payload["active_diagnostic_signals"]
        active_codes = [s["code"] for s in active]

        self.assertIn("LOW_SALES_VELOCITY", active_codes)
        self.assertIn("LUMPY_DEMAND", active_codes)
        self.assertIn("POSSIBLE_OBSOLESCENCE", active_codes)
        self.assertIn("PROMO_ASSOCIATED_LOW_VELOCITY", active_codes)
        self.assertIn("POSSIBLE_STOCKOUT_EFFECT", active_codes)

        # Check evidence structure
        for sig in active:
            self.assertTrue(len(sig["evidence"]) > 0)
            for ev in sig["evidence"]:
                self.assertIn("feature", ev)
                self.assertIn("value", ev)
                self.assertIn("threshold", ev)

    def test_ac05_risk_prediction_immutability(self):
        """AC-05: Diagnostic signals do not alter risk class, risk probability or risk score."""
        payload = self.mapper.evaluate_sku_signals(
            sku="SKU_IMMUTABLE",
            feature_dict=self.sample_features,
            risk_class="HIGH_RISK",
            risk_probability=0.88,
            risk_score=88.0
        )

        self.assertEqual(payload["risk_class"], "HIGH_RISK")
        self.assertEqual(payload["risk_probability"], 0.88)
        self.assertEqual(payload["risk_score"], 88.0)

    def test_ac08_ac09_ac10_terminology_guardrails(self):
        """AC-08, AC-09, AC-10: Terminology guardrails for POSSIBLE_STOCKOUT_EFFECT and POSSIBLE_OBSOLESCENCE."""
        payload = self.mapper.evaluate_sku_signals(
            sku="SKU_GUARDRAIL",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0
        )

        active_codes = [s["code"] for s in payload["active_diagnostic_signals"]]
        self.assertIn("POSSIBLE_STOCKOUT_EFFECT", active_codes)
        self.assertNotIn("STOCKOUT_CONFIRMED", active_codes)
        self.assertNotIn("STOCKOUT", active_codes)

        self.assertIn("POSSIBLE_OBSOLESCENCE", active_codes)
        self.assertNotIn("OBSOLETE", active_codes)
        self.assertNotIn("CONFIRMED_OBSOLETE", active_codes)

        # Verify business interpretation contains no prohibited causal terms
        prohibited = ["nguyên nhân khiến", "chắc chắn bị lỗi thời", "kho chắc chắn hết hàng"]
        for b in payload["business_interpretation"]:
            for p in prohibited:
                self.assertNotIn(p, b.lower())

    def test_ac07_ac11_ac12_temporal_safety_and_artifacts(self):
        """AC-07, AC-11, AC-12: Temporal safety (t <= t0), canonical schema & artifact saving."""
        payload = self.mapper.evaluate_sku_signals(
            sku="SKU_ARTIFACT",
            feature_dict=self.sample_features,
            risk_class="MEDIUM_RISK",
            risk_probability=0.50,
            risk_score=50.0
        )

        self.assertEqual(payload["explanation_version"], "1.0")
        self.assertEqual(payload["disclaimer"], TERMINOLOGY_DISCLAIMER)

        # Check temporal safety guardrail violation with future feature
        leak_dict = self.sample_features.copy()
        leak_dict["fut_qty_60d"] = 10
        with self.assertRaises(ExplainabilityGuardrailError):
            self.mapper.evaluate_sku_signals(sku="SKU_LEAK", feature_dict=leak_dict)

        # Save artifacts
        art_paths = self.mapper.save_diagnostic_artifacts(payload)
        self.assertTrue(os.path.exists(art_paths["sample_path"]))
        self.assertTrue(os.path.exists(art_paths["summary_path"]))
