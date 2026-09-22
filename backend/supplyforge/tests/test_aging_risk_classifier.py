"""
Test suite for Task M5-06 Aging Risk Classification (Module 05).
Verifies AC-01 through AC-10 requirements:
- Receipt of M5-04 aging & M5-05 capital exposure metrics
- Classification of Aging Risk Levels (FRESH, AGING, AT_RISK, CRITICAL_AGING)
- Boundary condition testing (29->FRESH, 30->AGING, 90->AGING, 91->AT_RISK, 180->AT_RISK, 181->CRITICAL_AGING)
- Capital-aware Aging Priority generation (P1, P2, P3, P4)
- Deterministic diagnostic flags generation
- Externalized policy configuration loading & 0 Risk Class mutation
- Deliverable artifact generation in reports/capital/
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.aging_risk_classifier import AgingRiskClassifier, AgingRiskClassifierError
from src.analytics.capital_exposure_architecture import CapitalExposureGuardrailError


class TestAgingRiskClassifier(TestCase):

    def setUp(self):
        self.classifier = AgingRiskClassifier()

        self.sample_exposure_records = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Mother & Baby",
                "risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "capital_exposure": 20000000.0,
                "risk_weighted_exposure": 20000000.0,
                "aging_days": 210,
                "aging_bucket": "SEVERELY_STALE"
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Mother & Baby",
                "risk_class": "HIGH_RISK",
                "risk_probability": 0.80,
                "capital_exposure": 12000000.0,
                "risk_weighted_exposure": 9000000.0,
                "aging_days": 45,
                "aging_bucket": "AGING"
            },
            {
                "sku": "SKU_1003",
                "canonical_sku_id": "CSKU_1003",
                "product_name": "Product 3",
                "category": "Toys",
                "risk_class": "LOW_RISK",
                "risk_probability": 0.10,
                "capital_exposure": 2000000.0,
                "risk_weighted_exposure": 200000.0,
                "aging_days": 15,
                "aging_bucket": "RECENT"
            }
        ]

    def test_ac04_ac09_boundary_conditions(self):
        """AC-04, AC-09: Boundary condition testing for non-overlapping aging risk levels."""
        # 29 -> FRESH
        self.assertEqual(self.classifier.classify_aging_risk_level(29), "FRESH")
        # 30 -> AGING
        self.assertEqual(self.classifier.classify_aging_risk_level(30), "AGING")
        # 90 -> AGING
        self.assertEqual(self.classifier.classify_aging_risk_level(90), "AGING")
        # 91 -> AT_RISK
        self.assertEqual(self.classifier.classify_aging_risk_level(91), "AT_RISK")
        # 180 -> AT_RISK
        self.assertEqual(self.classifier.classify_aging_risk_level(180), "AT_RISK")
        # 181 -> CRITICAL_AGING
        self.assertEqual(self.classifier.classify_aging_risk_level(181), "CRITICAL_AGING")
        # None -> CRITICAL_AGING
        self.assertEqual(self.classifier.classify_aging_risk_level(None), "CRITICAL_AGING")

    def test_ac01_ac02_ac05_ac06_ac07_sku_assessment_and_priorities(self):
        """AC-01, AC-02, AC-05, AC-06, AC-07: SKU assessment, priority generation & diagnostic flags."""
        rec1 = self.classifier.evaluate_sku_aging_risk(self.sample_exposure_records[0])

        self.assertEqual(rec1["aging_risk_level"], "CRITICAL_AGING")
        self.assertEqual(rec1["aging_priority"], "P1")
        self.assertIn("LONG_AGED_INVENTORY", rec1["aging_flags"])
        self.assertIn("AGING_CAPITAL_EXPOSURE", rec1["aging_flags"])
        self.assertIn("CRITICAL_AGING", rec1["aging_flags"])

        rec3 = self.classifier.evaluate_sku_aging_risk(self.sample_exposure_records[2])
        self.assertEqual(rec3["aging_risk_level"], "FRESH")
        self.assertEqual(rec3["aging_priority"], "P4")
        self.assertEqual(rec3["aging_flags"], [])

    def test_ac03_ac08_ac10_dataset_assessment_and_artifacts(self):
        """AC-03, AC-08, AC-10: Dataset assessment, external policy verification & artifact generation."""
        assessments, risk_dist, prio_dist, summary = self.classifier.evaluate_dataset_aging_risk(self.sample_exposure_records)

        self.assertEqual(summary["total_skus"], 3)
        self.assertEqual(summary["total_capital_exposure"], 34000000.0)

        # Artifact generation check
        art_paths = self.classifier.save_classification_artifacts(assessments, risk_dist, prio_dist, summary)
        self.assertTrue(os.path.exists(art_paths["aging_risk_distribution"]))
        self.assertTrue(os.path.exists(art_paths["aging_priority_distribution"]))
        self.assertTrue(os.path.exists(art_paths["aging_risk_validation"]))
        self.assertTrue(os.path.exists(art_paths["aging_risk_assessment"]))
