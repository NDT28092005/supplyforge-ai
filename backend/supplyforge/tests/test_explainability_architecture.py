"""
Test suite for Task M4-01 Explainability Architecture (Module 04).
Verifies AC-01 through AC-10 requirements:
- Schema validation
- Temporal safety guardrails (rejects future features)
- Non-causal text validation
- Feature registry mapping
- Payload assembly & versioning
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.explainability_architecture import (
    ExplainabilityOrchestrator,
    ExplainabilityGuardrailError
)


class TestExplainabilityArchitecture(TestCase):

    def setUp(self):
        self.orchestrator = ExplainabilityOrchestrator()

    def test_ac01_ac02_ac03_architecture_orchestrator(self):
        """AC-01, AC-02, AC-03: Independent architecture receiving M3 inputs and specifying SHAP."""
        raw_contributions = [
            {"feature_name": "sales_velocity_90d", "feature_value": 0.02, "shap_value": 0.45},
            {"feature_name": "zero_rate_90d", "feature_value": 0.85, "shap_value": 0.35},
            {"feature_name": "dsls", "feature_value": 140, "shap_value": 0.20}
        ]

        payload = self.orchestrator.assemble_payload(
            sku="SKU_TEST_01",
            risk_class="CRITICAL",
            risk_probability=0.96,
            risk_score=96.0,
            shap_contributions=raw_contributions,
            base_value=0.35,
            diagnostics=["LOW_SALES_VELOCITY", "POSSIBLE_OBSOLESCENCE"]
        )

        self.assertEqual(payload["sku"], "SKU_TEST_01")
        self.assertEqual(payload["risk_class"], "CRITICAL")
        self.assertEqual(payload["risk_probability"], 0.96)
        self.assertEqual(payload["explanation"]["method"], "SHAP")
        self.assertEqual(payload["explanation_version"], "1.0")

    def test_ac04_ac05_temporal_safety_guardrails(self):
        """AC-04, AC-05: Rejects future features and Ground Truth labels (t > t0)."""
        # Valid features strictly at t <= t0
        valid_features = ["sales_velocity_90d", "zero_rate_90d", "dsls", "adi", "cv2"]
        self.assertTrue(self.orchestrator.validate_temporal_safety(valid_features))

        # Invalid future features (e.g. fut_qty_60d, ground_truth_label) must raise GuardrailError
        invalid_features = ["sales_velocity_90d", "fut_qty_60d"]
        with self.assertRaises(ExplainabilityGuardrailError):
            self.orchestrator.validate_temporal_safety(invalid_features)

        gt_features = ["sales_velocity_90d", "ground_truth_label"]
        with self.assertRaises(ExplainabilityGuardrailError):
            self.orchestrator.validate_temporal_safety(gt_features)

    def test_ac06_ac10_canonical_schema_payload_versioning(self):
        """AC-06, AC-10: Validates canonical schema contract and versioning ("1.0")."""
        contributions = [
            {"feature_name": "forecast_7d", "feature_value": 0.08, "shap_value": 0.42}
        ]
        payload = self.orchestrator.assemble_payload(
            sku="SKU_TEST_02",
            risk_class="HIGH_RISK",
            risk_probability=0.78,
            risk_score=78.0,
            shap_contributions=contributions
        )

        self.assertIn("explanation", payload)
        self.assertEqual(payload["explanation_version"], "1.0")
        self.assertEqual(payload["explanation"]["features"][0]["display_name"], "Dự báo nhu cầu 7 ngày tới")
        self.assertEqual(payload["explanation"]["features"][0]["direction"], "INCREASES_RISK")
        self.assertEqual(payload["explanation"]["features"][0]["rank"], 1)

    def test_ac07_ac08_non_causal_language_guardrail(self):
        """AC-07, AC-08: Ensures non-causal language and terminology guardrails."""
        valid_text = "Tốc độ bán 90 ngày ở mức thấp làm gia tăng xác suất dự báo rủi ro."
        self.assertTrue(self.orchestrator.validate_non_causal_text(valid_text))

        causal_text = "Đây là nguyên nhân khiến sản phẩm bị ế hàng và chắc chắn bị lỗi thời."
        with self.assertRaises(ExplainabilityGuardrailError):
            self.orchestrator.validate_non_causal_text(causal_text)

    def test_ac09_feature_registry_config_exists(self):
        """AC-09: Architecture ready for SHAP implementation in M4-02."""
        self.assertIn("sales_velocity_90d", self.orchestrator.registry["features"])
        self.assertIn("zero_rate_90d", self.orchestrator.registry["features"])
        self.assertIn("dsls", self.orchestrator.registry["features"])
        self.assertIn("adi", self.orchestrator.registry["features"])
        self.assertIn("cv2", self.orchestrator.registry["features"])
