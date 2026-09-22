"""
Test suite for Task M7-05 Grounded Response Engine (Module 07).
Verifies AC-01 through AC-15 requirements:
- Grounded Prompt Construction & Evidence Assembly
- Response Generation & Numerical Consistency Validation
- Unsupported Claim Detection & Grounding Score Evaluation
- Deterministic Fallback Handling for Invalid Generation
- Source Attribution & Auditability Metadata Compliance
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.copilot.response_engine import GroundedResponseEngine
from src.copilot.prompt_builder import GroundedPromptBuilder
from src.copilot.numerical_validator import NumericalValidator
from src.copilot.claim_validator import ClaimValidator
from src.copilot.grounding_validator import GroundingValidator
from src.copilot.fallback_response import FallbackResponseGenerator


class TestGroundedResponseEngine(TestCase):

    def setUp(self):
        self.engine = GroundedResponseEngine()
        self.evidence_package = {
            "context_id": "CTX-1001",
            "merchant_id": "m01",
            "dataset_version": "v1.0",
            "subject": {"type": "SKU", "id": "SKU-001"},
            "risk": {"risk_class": "CRITICAL", "risk_score": 0.95},
            "capital": {"capital_exposure": 15000000.0, "aging_days": 375},
            "decision": {"recommended_action": "DISCOUNT", "discount_rate": 0.20, "expected_recovery": 12000000.0},
            "evidence_items": [
                {"metric": "Risk Class", "value": "CRITICAL (0.95)", "source_module": "M3_RISK", "interpretation": "Mức rủi ro nghiêm trọng."},
                {"metric": "Capital Exposure", "value": "15,000,000 VND", "source_module": "M5_CAPITAL", "interpretation": "Vốn bị đóng băng."},
                {"metric": "Recommended Action", "value": "DISCOUNT (20%)", "source_module": "M6_DECISION", "interpretation": "Phương án giảm giá."}
            ]
        }

    def test_prompt_builder(self):
        """AC-01, AC-02: Verifies prompt construction with grounding rules and evidence lines."""
        prompt = GroundedPromptBuilder.build_prompt("Tôi nên làm gì?", "DECISION_QUERY", self.evidence_package)
        self.assertIn("TRUSTED EVIDENCE", prompt)
        self.assertIn("SKU-001", prompt)
        self.assertIn("15,000,000 VND", prompt)
        self.assertIn("Cấm tự tạo số liệu", prompt)

    def test_numerical_validation(self):
        """AC-05: Verifies numerical consistency detection."""
        # 1. Consistent text
        res_valid = NumericalValidator.validate_numerical_consistency(
            "SKU-001 có vốn phơi nhiễm 15000000 VNĐ.", self.evidence_package
        )
        self.assertTrue(res_valid["is_consistent"])

        # 2. Conflicting number (18,000,000 is NOT in evidence)
        res_invalid = NumericalValidator.validate_numerical_consistency(
            "SKU-001 có vốn phơi nhiễm 18000000 VNĐ.", self.evidence_package
        )
        self.assertFalse(res_invalid["is_consistent"])
        self.assertEqual(res_invalid["numeric_conflicts"], 1)

    def test_unsupported_claim_detection(self):
        """AC-07: Verifies detection of unsupported claims."""
        res = ClaimValidator.validate_claims("Sản phẩm cam kết không bán được và chắc chắn 100% hỏng.", self.evidence_package)
        self.assertGreater(res["unsupported_claims_count"], 0)

    def test_grounding_evaluator(self):
        """AC-08: Verifies grounding score calculation."""
        eval_res = GroundingValidator.evaluate_grounding("Sản phẩm SKU-001 có vốn 15000000 VNĐ", self.evidence_package)
        self.assertGreaterEqual(eval_res["grounding_score"], 0.85)
        self.assertEqual(eval_res["status"], "GROUNDED")

    def test_fallback_response_generator(self):
        """AC-10: Verifies deterministic template fallback generation."""
        fallback = FallbackResponseGenerator.generate_fallback(self.evidence_package)
        self.assertIn("SKU-001", fallback)
        self.assertIn("CRITICAL", fallback)
        self.assertIn("15,000,000 VNĐ", fallback)

    def test_end_to_end_response_engine(self):
        """AC-03, AC-04, AC-11, AC-13, AC-14: Verifies full response engine generation & API contract compliance."""
        response = self.engine.generate_response(
            query="Tôi nên xử lý SKU-001 thế nào?",
            intent_code="DECISION_QUERY",
            evidence_package=self.evidence_package,
            orchestration_id="ORCH-TEST"
        )

        self.assertIn("response_id", response)
        self.assertEqual(response["status"], "GROUNDED")
        self.assertGreaterEqual(response["grounding"]["grounding_score"], 0.85)
        self.assertIn("M3_RISK", response["sources"])
        self.assertIn("M5_CAPITAL", response["sources"])
        self.assertEqual(response["audit"]["orchestration_id"], "ORCH-TEST")
