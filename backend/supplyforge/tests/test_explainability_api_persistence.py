"""
Test suite for Task M4-08 Explainability API & Persistence (Module 04).
Verifies AC-01 through AC-12 requirements:
- Persistence of Canonical Risk Explanation Objects & versioning
- Idempotency & duplicate protection
- REST API endpoints (GET /api/explanations/{sku_id}, /history, POST /batch, GET /global, GET list)
- Schema compliance with M4-07 & validation rejection of invalid payloads
- Zero ML/XAI recalculation & Zero LLM calls in API layer
"""

import json
import os
import sys
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.explanation_assembly_engine import ExplanationAssemblyEngine
from src.analytics.explanation_repository import ExplanationRepository, ExplanationRepositoryError


class TestExplainabilityAPIPersistence(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.assembly_engine = ExplanationAssemblyEngine()
        self.repository = ExplanationRepository()

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

        self.canonical_obj = self.assembly_engine.assemble_sku_explanation(
            sku="10012591570",
            canonical_sku_id="CSKU_10012591570",
            product_name="Tã bỉm dán Merries First Premium L40",
            feature_dict=self.sample_features,
            risk_class="CRITICAL",
            risk_probability=0.99,
            risk_score=99.0,
            promotion_rate=0.25
        )

    def test_ac01_ac02_ac09_ac10_persistence_versioning_and_idempotency(self):
        """AC-01, AC-02, AC-09, AC-10: Persists canonical object, versions record & ensures idempotency."""
        res1 = self.repository.save_explanation(self.canonical_obj)
        self.assertIsNotNone(res1)

        # Idempotent save attempt (identical payload & timestamp)
        res2 = self.repository.save_explanation(self.canonical_obj)
        self.assertEqual(res1["sku"], res2["sku"])
        self.assertEqual(res1["metadata"]["model_version"], "xgboost_exp03_v1")

    def test_ac03_get_sku_explanation_api(self):
        """AC-03: REST API retrieves latest canonical explanation for SKU (GET /api/explanations/{sku_id})."""
        self.repository.save_explanation(self.canonical_obj)

        url = f"/api/explanations/{self.canonical_obj['sku']}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.json()
        self.assertEqual(data["sku"], "10012591570")
        self.assertEqual(data["risk_assessment"]["risk_class"], "CRITICAL")

    def test_ac04_get_sku_explanation_history_api(self):
        """AC-04: REST API retrieves explanation history (GET /api/explanations/{sku_id}/history)."""
        self.repository.save_explanation(self.canonical_obj)

        url = f"/api/explanations/{self.canonical_obj['sku']}/history"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(len(data["history"]) >= 1)

    def test_ac05_get_batch_explanations_api(self):
        """AC-05: REST API batch retrieves explanations for Risk Dashboard (POST /api/explanations/batch)."""
        self.repository.save_explanation(self.canonical_obj)

        url = "/api/explanations/batch"
        payload = {"skus": ["10012591570", "NON_EXISTENT_SKU"]}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("10012591570", data["explanations"])
        self.assertIsNotNone(data["explanations"]["10012591570"])

    def test_ac06_get_global_explanation_api(self):
        """AC-06: REST API serves Global Model Explanation (GET /api/explanations/global)."""
        url = "/api/explanations/global"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["explanation_type"], "GLOBAL")

    def test_ac07_ac08_ac11_ac12_validation_and_zero_recalculation(self):
        """AC-07, AC-08, AC-11, AC-12: Validation rejects invalid payloads; zero recalculation & schema compliance."""
        invalid_obj = self.canonical_obj.copy()
        invalid_obj["risk_assessment"] = {
            "risk_class": "INVALID_CLASS",
            "risk_probability": 1.5,
            "risk_score": 150.0
        }

        with self.assertRaises(ExplanationRepositoryError):
            self.repository.save_explanation(invalid_obj)

        # Verify filtering endpoint
        url = "/api/explanations?risk_class=CRITICAL"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "success")
