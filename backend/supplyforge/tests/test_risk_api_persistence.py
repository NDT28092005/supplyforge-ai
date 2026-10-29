import os
import sys
from django.test import TestCase
from rest_framework.test import APIClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace, SlowMovingRiskAssessment


class RiskApiPersistenceTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-07 Risk API & Persistence."""

    def setUp(self):
        self.client = APIClient()
        self.workspace = Workspace.objects.create(name="Test Risk API WS", slug="test-ws-ra-api")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0",
            m3_probability_calibration_json={
                'calibratedPredictions': [
                    {
                        'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g', 'category': 'Milk',
                        'risk_class': 'CRITICAL', 'calibrated_probability': 0.960, 'risk_score': 96.0,
                        'sales_velocity_90d': 0.029, 'zero_rate_90d': 0.989, 'dsls': 375, 'adi': 5.92, 'cv2': 0.65
                    }
                ]
            }
        )

    def test_run_and_persist_assessments_api(self):
        """Test POST /api/v1/risk/assessments executes assembly and persists records to Django DB."""
        response = self.client.post('/api/v1/risk/assessments', {'session_id': str(self.session.id)}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "SUCCESS")
        self.assertEqual(response.data["persisted_count"], 1)

        db_records = SlowMovingRiskAssessment.objects.filter(session=self.session)
        self.assertEqual(db_records.count(), 1)
        rec = db_records.first()
        self.assertEqual(rec.sku, "SKU_101")
        self.assertEqual(rec.risk_class, "CRITICAL")
        self.assertEqual(rec.risk_score, 96.0)

    def test_dat11_readiness_gate_blocking(self):
        """Test DAT-11 readiness gate check blocks NOT_READY sessions."""
        not_ready_session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_not_ready.csv",
            status="NOT_READY",
            dataset_version="v1.0"
        )
        response = self.client.post('/api/v1/risk/assessments', {'session_id': str(not_ready_session.id)}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn("DAT-11 Data Readiness Gate", response.data["error"])

    def test_list_and_summary_apis(self):
        """Test GET /api/v1/risk/assessments/list and GET /api/v1/risk/summary endpoints."""
        SlowMovingRiskAssessment.objects.create(
            session=self.session,
            sku="SKU_101", canonical_sku_id="CSKU_101", product_name="Milk 900g",
            risk_class="CRITICAL", risk_probability=0.96, risk_score=96.0
        )

        res_list = self.client.get('/api/v1/risk/assessments/list', {'risk_class': 'CRITICAL'})
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(res_list.data["total_count"], 1)

        res_sum = self.client.get('/api/v1/risk/summary')
        self.assertEqual(res_sum.status_code, 200)
        self.assertEqual(res_sum.data["critical"], 1)

    def test_list_does_not_create_assessments_on_a_get_request(self):
        """A read request must not start the risk pipeline or write records."""
        response = self.client.get('/api/v1/risk/assessments/list', {'limit': 500})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['limit'], 100)
        self.assertEqual(response.data['total_count'], 0)
        self.assertEqual(SlowMovingRiskAssessment.objects.count(), 0)
