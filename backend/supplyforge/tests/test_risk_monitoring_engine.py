import os
import sys
from django.test import TestCase
from rest_framework.test import APIClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from supplyforge.models import IngestionSession, Workspace, SlowMovingRiskAssessment, RiskMonitoringRun
from src.analytics.risk_monitoring_engine import RiskMonitoringEngine


class RiskMonitoringEngineTestCase(TestCase):
    """Test suite for Module 03 Analytics — M3-08 Risk Monitoring & Validation."""

    def setUp(self):
        self.client = APIClient()
        self.workspace = Workspace.objects.create(name="Test Monitoring WS", slug="test-ws-rm-eng")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_mother_baby.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )
        SlowMovingRiskAssessment.objects.create(
            session=self.session,
            sku="SKU_101", canonical_sku_id="CSKU_101", product_name="Milk 900g", category="Milk",
            risk_class="CRITICAL", risk_probability=0.960, risk_score=96.0,
            primary_signals=["POSSIBLE_OBSOLESCENCE", "LOW_SALES_VELOCITY"],
            supporting_signals=["LUMPY_DEMAND"],
            diagnostics=["POSSIBLE_OBSOLESCENCE", "LOW_SALES_VELOCITY", "LUMPY_DEMAND"],
            evidence={"sales_velocity_90d": 0.029},
            model_version="xgboost_exp03_v1", dataset_version="v1.0", assessment_status="COMPLETE"
        )

    def test_evaluate_risk_assessments_engine(self):
        """Test RiskMonitoringEngine output validation, distribution statistics, and report generation."""
        assessments = [
            {
                'sku': 'SKU_101', 'canonical_sku_id': 'CSKU_101', 'product_name': 'Milk 900g',
                'assessment': {'risk_class': 'CRITICAL', 'risk_probability': 0.960, 'risk_score': 96.0},
                'metadata': {'model_version': 'xgboost_exp03_v1', 'data_version': 'v1.0'}
            }
        ]
        engine = RiskMonitoringEngine(session_id=str(self.session.id))
        res = engine.evaluate_risk_assessments(assessments=assessments, session_id=str(self.session.id))

        self.assertIn(res["status"], ["HEALTHY", "WARNING", "CRITICAL", "INVALID"])
        self.assertEqual(res["total_skus"], 1)
        self.assertIn("report", res)
        self.assertIn("alerts", res)

    def test_execute_risk_monitoring_api(self):
        """Test POST /api/v1/risk/monitoring/run executes monitoring engine and persists run snapshot to Django DB."""
        response = self.client.post('/api/v1/risk/monitoring/run', {'session_id': str(self.session.id)}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn("run_id", response.data)

        db_runs = RiskMonitoringRun.objects.filter(session=self.session)
        self.assertEqual(db_runs.count(), 1)
        run_obj = db_runs.first()
        self.assertEqual(run_obj.total_skus_evaluated, 1)

    def test_list_and_alerts_apis(self):
        """Test GET /api/v1/risk/monitoring and GET /api/v1/risk/monitoring/alerts endpoints."""
        RiskMonitoringRun.objects.create(
            session=self.session,
            status="HEALTHY",
            total_skus_evaluated=1,
            risk_distribution={'CRITICAL': 1.0},
            probability_stats={'mean': 0.96},
            validation_summary={'probability_validation': 'PASSED'},
            alerts=[]
        )

        res_runs = self.client.get('/api/v1/risk/monitoring')
        self.assertEqual(res_runs.status_code, 200)
        self.assertEqual(res_runs.data["total_runs"], 1)

        res_alerts = self.client.get('/api/v1/risk/monitoring/alerts')
        self.assertEqual(res_alerts.status_code, 200)
        self.assertIn("total_alerts", res_alerts.data)
