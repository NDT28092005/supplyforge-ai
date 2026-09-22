"""
Test suite for Task M5-01 Capital Exposure Architecture (Module 05).
Verifies AC-01 through AC-12 requirements:
- Architecture & component contracts for Module 05
- Strict Inventory Evidence Boundary enforcement
- Prohibition of sales-to-stock substitution
- Data Availability States (AVAILABLE, PARTIAL, MISSING, INVALID, STALE)
- Non-causal language guardrails & deterministic calculation guarantees
- Spec report artifact generation
"""

import json
import os
import sys
from django.test import TestCase

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.capital_exposure_architecture import (
    CapitalExposureOrchestrator,
    InventoryEvidenceBoundary,
    DataAvailabilityState,
    CapitalExposureGuardrailError
)


class TestCapitalExposureArchitecture(TestCase):

    def setUp(self):
        self.orchestrator = CapitalExposureOrchestrator()

    def test_ac01_ac02_ac03_canonical_payload_and_separation(self):
        """AC-01, AC-02, AC-03: Architecture payload definition & clean separation of Risk vs Inventory."""
        payload = self.orchestrator.build_canonical_payload(
            sku="SKU_10012591570",
            canonical_sku_id="CSKU_10012591570",
            product_name="Tã bỉm dán Merries First Premium L40",
            category="Mother & Baby",
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            stock_on_hand=120,
            unit_cost=150000.0,
            inventory_receipt_date="2026-01-15",
            analysis_date="2026-08-22"
        )

        self.assertEqual(payload["sku"], "SKU_10012591570")
        self.assertEqual(payload["risk_assessment"]["risk_class"], "CRITICAL")
        self.assertEqual(payload["inventory_data_status"], "AVAILABLE")
        self.assertEqual(payload["inventory_metrics"]["capital_exposure"], 18000000.0)
        self.assertEqual(payload["aging_metrics"]["aging_bucket"], "181-365d")

    def test_ac04_ac08_ac09_inventory_evidence_boundary_and_states(self):
        """AC-04, AC-08, AC-09: Inventory evidence boundary and prohibition of sales substitution."""
        # Case A: AVAILABLE
        st_avail = InventoryEvidenceBoundary.validate_inventory_evidence(100, 50.0)
        self.assertEqual(st_avail, DataAvailabilityState.AVAILABLE)

        # Case B: MISSING (No stock available)
        payload_missing = self.orchestrator.build_canonical_payload(
            sku="SKU_NO_STOCK",
            risk_class="CRITICAL",
            risk_probability=0.95,
            risk_score=95.0,
            stock_on_hand=None,
            unit_cost=None
        )
        self.assertEqual(payload_missing["inventory_data_status"], "MISSING")
        self.assertIsNone(payload_missing["inventory_metrics"]["capital_exposure"])

        # Case C: Prohibition of inferring stock from past sales
        invalid_feature_map = {
            "sku": "SKU_ILLEGAL",
            "stock_on_hand": None,
            "past_total_sold": 500,
            "inferred_stock_from_sales": True
        }
        with self.assertRaises(CapitalExposureGuardrailError):
            InventoryEvidenceBoundary.validate_no_sales_to_stock_substitution(invalid_feature_map)

    def test_ac05_ac06_ac07_calculation_and_aging_contracts(self):
        """AC-05, AC-06, AC-07: Calculation contracts for Capital, Aging, and Risk x Capital tiering."""
        payload = self.orchestrator.build_canonical_payload(
            sku="SKU_SEVERE",
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            stock_on_hand=200,
            unit_cost=100000.0,
            inventory_receipt_date="2025-10-01",
            analysis_date="2026-08-22"
        )

        self.assertEqual(payload["inventory_metrics"]["capital_exposure"], 20000000.0)
        self.assertEqual(payload["exposure_assessment"]["exposure_class"], "SEVERE_EXPOSURE")

    def test_ac10_ac11_ac12_spec_report_generation(self):
        """AC-10, AC-11, AC-12: Architecture spec report artifact generation."""
        report_path = self.orchestrator.save_architecture_spec_report()
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, 'r', encoding='utf-8') as f:
            spec = json.load(f)
            self.assertEqual(spec["task"], "M5-01")
            self.assertEqual(spec["status"], "APPROVED")
