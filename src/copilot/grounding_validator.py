"""
Grounding Validator for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Calculates grounding scores and evaluates response acceptability.
"""

from typing import Dict, Any
from src.copilot.numerical_validator import NumericalValidator
from src.copilot.claim_validator import ClaimValidator


class GroundingValidator:
    """Evaluates evidence coverage, numerical consistency, and unsupported claim rates."""

    @classmethod
    def evaluate_grounding(
        cls,
        generated_text: str,
        evidence_package: Dict[str, Any]
    ) -> Dict[str, Any]:

        num_res = NumericalValidator.validate_numerical_consistency(generated_text, evidence_package)
        claim_res = ClaimValidator.validate_claims(generated_text, evidence_package)

        evidence_items = evidence_package.get("evidence_items", [])
        evidence_count = len(evidence_items)

        numeric_conflicts = num_res["numeric_conflicts"]
        unsupported_claims = claim_res["unsupported_claims_count"]

        # Base score 1.0, penalties for conflicts and unsupported claims
        score = 1.0
        if numeric_conflicts > 0:
            score -= (numeric_conflicts * 0.35)
        if unsupported_claims > 0:
            score -= (unsupported_claims * 0.40)

        grounding_score = max(0.0, min(1.0, round(score, 2)))

        if grounding_score >= 0.85:
            status = "GROUNDED"
        elif grounding_score >= 0.60:
            status = "GROUNDED_WITH_WARNING"
        else:
            status = "VALIDATION_FAILED"

        return {
            "grounding_score": grounding_score,
            "status": status,
            "evidence_count": evidence_count,
            "numeric_conflicts": numeric_conflicts,
            "unsupported_claims": unsupported_claims,
            "num_details": num_res,
            "claim_details": claim_res
        }
