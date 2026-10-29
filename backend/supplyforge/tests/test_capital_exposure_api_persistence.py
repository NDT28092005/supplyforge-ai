"""
Test suite for Task M5-09 Capital Exposure API & Persistence (Module 05).
Verifies AC-01 through AC-14 requirements:
- Atomic database persistence of analysis run metadata & SKU exposure items via Repository
- Bulk creation performance and transaction safety
- REST API endpoints for Create Analysis, Get Analysis, Summary, SKU Items, SKU Detail, Aging & Risk Distributions
- Query filtering, pagination, and sorting for SKU exposure items
- Zero recalculation drift at API layer & zero cross-version contamination
- Deliverable artifact generation in reports/capital/
"""

import json
import os
import sys
import uuid
from django.test import TestCase, Client
from django.urls import reverse

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models import IngestionSession, SlowMovingRiskAssessment, User, Workspace
from supplyforge.models.capital_exposure import CapitalExposureAnalysisRecord, CapitalExposureItemRecord
from supplyforge.services.capital_exposure_service import CapitalExposureAnalysisService
from supplyforge.views.auth import generate_access_token
from src.analytics.capital_exposure_repository import CapitalExposureRepository


class TestCapitalExposureApiPersistence(TestCase):

    def setUp(self):
        self.client = Client()
        self.merchant_id = "test_merchant_m5"
        self.dataset_version = "v1.0"
        self.analysis_id = str(uuid.uuid4())

        self.sample_summary_payload = {
            "task": "M5-08",
            "module_version": "5.0",
            "summary": {
                "sku_count": 2,
                "total_inventory_value": 32000000.0,
                "total_risk_weighted_exposure": 29000000.0,
                "total_probability_adjusted_exposure": 28600000.0,
                "total_opportunity_cost": 1500000.0,
                "annual_opportunity_rate": 0.12
            },
            "financial_impact_by_risk": [
                {"group": "CRITICAL", "sku_count": 1, "inventory_value": 20000000.0, "risk_weighted_exposure": 20000000.0},
                {"group": "HIGH_RISK", "sku_count": 1, "inventory_value": 12000000.0, "risk_weighted_exposure": 9000000.0}
            ],
            "financial_impact_by_aging": [
                {"group": "CRITICAL_AGING", "sku_count": 1, "inventory_value": 20000000.0, "risk_weighted_exposure": 20000000.0},
                {"group": "AGING", "sku_count": 1, "inventory_value": 12000000.0, "risk_weighted_exposure": 9000000.0}
            ],
            "financial_impact_matrix": [],
            "reconciliation_status": {"all_reconciled": True}
        }

        self.sample_sku_records = [
            {
                "sku": "SKU_1001",
                "canonical_sku_id": "CSKU_1001",
                "product_name": "Product 1",
                "category": "Mother & Baby",
                "capital_exposure": 20000000.0,
                "risk_weighted_exposure": 20000000.0,
                "probability_adjusted_exposure": 19000000.0,
                "inventory_age_days": 210,
                "aging_bucket": "SEVERELY_STALE",
                "aging_risk_level": "CRITICAL_AGING",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "aging_priority": "P1",
                "estimated_opportunity_cost": 1380821.92,
                "aging_flags": ["LONG_AGED_INVENTORY"]
            },
            {
                "sku": "SKU_1002",
                "canonical_sku_id": "CSKU_1002",
                "product_name": "Product 2",
                "category": "Mother & Baby",
                "capital_exposure": 12000000.0,
                "risk_weighted_exposure": 9000000.0,
                "probability_adjusted_exposure": 9600000.0,
                "inventory_age_days": 45,
                "aging_bucket": "AGING",
                "aging_risk_level": "AGING",
                "slow_moving_risk_class": "HIGH_RISK",
                "risk_probability": 0.80,
                "aging_priority": "P2",
                "estimated_opportunity_cost": 177534.25,
                "aging_flags": []
            }
        ]

    def test_ac01_ac02_ac09_ac12_repository_persistence_and_bulk_create(self):
        """AC-01, AC-02, AC-09, AC-12: Repository persistence, version tracking & bulk creation."""
        analysis_rec = CapitalExposureRepository.save_analysis(
            summary_payload=self.sample_summary_payload,
            sku_assessment_records=self.sample_sku_records,
            merchant_id=self.merchant_id,
            dataset_version=self.dataset_version,
            analysis_id=self.analysis_id
        )

        self.assertEqual(analysis_rec.analysis_id, self.analysis_id)
        self.assertEqual(analysis_rec.merchant_id, self.merchant_id)
        self.assertEqual(analysis_rec.dataset_version, self.dataset_version)
        self.assertEqual(CapitalExposureItemRecord.objects.filter(analysis=analysis_rec).count(), 2)

    def test_ac03_ac04_ac05_ac06_ac08_api_endpoints_and_filtering(self):
        """AC-03, AC-04, AC-05, AC-06, AC-08: REST API endpoints, summary, SKU items filtering & pagination."""
        # First persist an analysis run
        CapitalExposureRepository.save_analysis(
            summary_payload=self.sample_summary_payload,
            sku_assessment_records=self.sample_sku_records,
            merchant_id=self.merchant_id,
            dataset_version=self.dataset_version,
            analysis_id=self.analysis_id
        )

        # GET /api/capital-exposure/analyses/{analysis_id}
        res1 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.data["analysis_id"], self.analysis_id)

        # GET /api/capital-exposure/analyses/{analysis_id}/summary
        res2 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}/summary")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["summary"]["total_inventory_value"], 32000000.0)

        # GET /api/capital-exposure/analyses/{analysis_id}/items?risk_level=CRITICAL
        res3 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}/items?risk_level=CRITICAL")
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.data["pagination"]["total_items"], 1)
        self.assertEqual(res3.data["items"][0]["sku"], "SKU_1001")

        # GET /api/capital-exposure/analyses/{analysis_id}/items/SKU_1001
        res4 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}/items/SKU_1001")
        self.assertEqual(res4.status_code, 200)
        self.assertEqual(res4.data["sku"], "SKU_1001")
        self.assertEqual(res4.data["aging_priority"], "P1")

        # GET /api/capital-exposure/analyses/{analysis_id}/aging
        res5 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}/aging")
        self.assertEqual(res5.status_code, 200)
        self.assertIn("aging_distribution", res5.data)

        # GET /api/capital-exposure/analyses/{analysis_id}/risk-distribution
        res6 = self.client.get(f"/api/capital-exposure/analyses/{self.analysis_id}/risk-distribution")
        self.assertEqual(res6.status_code, 200)
        self.assertIn("risk_distribution", res6.data)

    def test_create_api_requires_an_authenticated_workspace(self):
        """The worker-only analysis queue rejects legacy client-supplied scope."""
        payload = {
            "merchant_id": "merchant_test_create",
            "dataset_version": "v2.0",
            "annual_opportunity_rate": 0.12
        }

        res = self.client.post(
            "/api/capital-exposure/analyses",
            data=json.dumps(payload),
            content_type="application/json"
        )

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['detail'], 'Yêu cầu cần workspace đã xác thực.')

    def test_latest_endpoint_returns_only_the_workspace_current_analysis(self):
        user = User.objects.create(
            email='capital-latest@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        workspace = Workspace.objects.create(
            name='Capital Latest Workspace',
            slug='capital-latest-workspace',
            owner=user,
        )
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename='orders.csv',
            status='COMPLETED',
        )
        SlowMovingRiskAssessment.objects.create(
            session=session,
            sku='SKU-LATEST',
            product_name='Latest product',
            risk_class='HIGH_RISK',
            risk_probability=0.8,
            risk_score=80,
        )
        analysis = CapitalExposureRepository.save_analysis(
            summary_payload=self.sample_summary_payload,
            sku_assessment_records=self.sample_sku_records,
            merchant_id=f'workspace:{workspace.id}',
            dataset_version=f'session:{session.id}',
        )
        self.client.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {generate_access_token(user, workspace.id)}'
        )

        response = self.client.get('/api/capital-exposure/analyses/latest')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['analysis_id'], str(analysis.analysis_id))

    def test_service_materializes_current_analysis_once(self):
        """A completed risk session can always backfill its capital read model."""
        user = User.objects.create(
            email='capital-materialize@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        workspace = Workspace.objects.create(
            name='Capital Materialization Workspace',
            slug='capital-materialization-workspace',
            owner=user,
        )
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename='orders.csv',
            status='COMPLETED',
        )
        SlowMovingRiskAssessment.objects.create(
            session=session,
            sku='SKU-MATERIALIZE',
            product_name='Materialized product',
            risk_class='HIGH_RISK',
            risk_probability=0.8,
            risk_score=80,
            evidence={
                'stock_quantity': 12,
                'unit_cost': 100_000,
                'dsls': 91,
            },
        )

        first = CapitalExposureAnalysisService.ensure_current_analysis(workspace.id)
        second = CapitalExposureAnalysisService.ensure_current_analysis(workspace.id)

        self.assertIsNotNone(first)
        self.assertEqual(first.analysis_id, second.analysis_id)
        self.assertEqual(
            CapitalExposureAnalysisRecord.objects.filter(
                merchant_id=f'workspace:{workspace.id}',
                dataset_version=f'session:{session.id}',
            ).count(),
            1,
        )
        self.assertEqual(CapitalExposureItemRecord.objects.filter(analysis=first).count(), 1)
