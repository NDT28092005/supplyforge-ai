"""
Numerical Validator for Task M7-05 Grounded Response Engine.
Module 07: AI Copilot & Merchant Workspace

Verifies numerical integrity and detects conflicting numbers in generated responses.
"""

import re
import logging
from typing import Dict, Any, List, Set

logger = logging.getLogger(__name__)


class NumericalValidator:
    """Extracts and verifies numerical values between generated text and input evidence."""

    SKU_STRIP_PATTERN = re.compile(r'SKU[-_][A-Za-z0-9_-]+', re.IGNORECASE)
    NUMBER_PATTERN = re.compile(r'(\d+[\d\.,]*)')

    @classmethod
    def validate_numerical_consistency(
        cls,
        generated_text: str,
        evidence_package: Dict[str, Any]
    ) -> Dict[str, Any]:

        if not generated_text:
            return {"is_consistent": True, "numeric_conflicts": 0, "conflicting_numbers": []}

        # Strip SKU identifiers like SKU-001 from text so '001' is not treated as a financial metric
        clean_text = cls.SKU_STRIP_PATTERN.sub('', generated_text)

        # Extract all numbers from evidence package recursively
        evidence_numbers: Set[str] = set()
        cls._extract_numbers_from_dict(evidence_package, evidence_numbers)

        # Extract numbers from cleaned generated text
        generated_matches = cls.NUMBER_PATTERN.findall(clean_text)
        conflicting = []

        for num_str in generated_matches:
            num_digits = num_str.replace(',', '').replace('.', '').lstrip('0') or '0'
            if len(num_digits) > 1 and num_digits not in evidence_numbers:
                if not (len(num_digits) == 4 and num_digits.startswith("202")): # e.g. year 2026
                    conflicting.append(num_str)

        return {
            "is_consistent": len(conflicting) == 0,
            "numeric_conflicts": len(conflicting),
            "conflicting_numbers": conflicting
        }

    @classmethod
    def _extract_numbers_from_dict(cls, val: Any, target_set: Set[str]):
        if isinstance(val, dict):
            for v in val.values():
                cls._extract_numbers_from_dict(v, target_set)
        elif isinstance(val, list):
            for item in val:
                cls._extract_numbers_from_dict(item, target_set)
        elif isinstance(val, (int, float)):
            if isinstance(val, float) and val.is_integer():
                int_val = int(val)
                num_str = str(int_val)
                target_set.add(num_str)
                millions = str(int(int_val / 1000000))
                if millions != '0':
                    target_set.add(millions)
            elif isinstance(val, float):
                num_str = str(val)
                digits = num_str.replace('.', '').lstrip('0') or '0'
                target_set.add(digits)
                pct = str(int(val * 100))
                target_set.add(pct)
            else:
                num_str = str(val)
                target_set.add(num_str)
                millions = str(int(val / 1000000))
                if millions != '0':
                    target_set.add(millions)
        elif isinstance(val, str):
            clean_val = cls.SKU_STRIP_PATTERN.sub('', val)
            for match in cls.NUMBER_PATTERN.findall(clean_val):
                digits = match.replace(',', '').replace('.', '').lstrip('0') or '0'
                if len(digits) > 0:
                    target_set.add(digits)



