import os
import json
import pandas as pd
from datetime import datetime, timedelta
from django.test import TestCase, Client
from supplyforge.models import User, IngestionSession, Workspace
from supplyforge.views.auth import get_or_create_user_tenant
from src.ingestion.data_freshness_tracker import DataFreshnessTracker
from src.ingestion.data_quality_validator import DataQualityValidator
from supplyforge.services.data_quality_service import DataQualityService


class Dataset004AndDQ001TestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="merchant_dq@shop.com",
            display_name="Merchant DQ",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant = get_or_create_user_tenant(self.user)
        self.session = IngestionSession.objects.create(
            workspace=self.tenant,
            original_filename="sales_history.csv",
            total_rows=100,
            status='COMPLETED'
        )

    def test_dataset_004_freshness_tracking_and_stale_guard(self):
        """DATASET-004: Evaluates Last updated, Data through, STALE DATA flag, and Decision Guard."""
        df = pd.DataFrame({
            'sku': ['SKU-001', 'SKU-002', 'SKU-003'],
            'date': ['2026-08-01', '2026-08-05', '2026-08-10'],  # Data is old relative to 2026-09-27
            'quantity': [10, 5, 2],
            'price': [100000, 200000, 150000]
        })

        tracker = DataFreshnessTracker(session_id=str(self.session.id))
        result = tracker.evaluate_freshness(
            df=df,
            current_date=datetime(2026, 9, 27),
            last_upload_at=datetime(2026, 9, 26, 18, 30)
        )

        self.assertEqual(result["lastUpdated"], "2026-09-26 18:30")
        self.assertEqual(result["dataThrough"], "2026-08-10")
        self.assertTrue(result["isStaleData"])
        self.assertEqual(result["staleLabel"], "STALE DATA")
        self.assertFalse(result["decisionGuard"]["canRunCurrentAnalysis"])
        self.assertTrue(result["decisionGuard"]["preventStalePrediction"])

    def test_dq_001_data_health_score_6_dimensions(self):
        """DQ-001: Calculates 6-dimension Data Health Score (e.g. 92/100)."""
        df = pd.DataFrame({
            'sku': ['SKU-001', 'SKU-002', 'SKU-003', 'SKU-004', 'SKU-005'],
            'date': ['2026-09-25', '2026-09-25', '2026-09-26', '2026-09-26', '2026-09-27'],
            'quantity': [10, 20, 15, 5, 30],
            'price': [100000, 150000, 200000, 120000, 250000],
            'cost': [70000, 100000, 140000, 80000, 170000]
        })

        validator = DataQualityValidator(session_id=str(self.session.id))
        report = validator.validate_quality(df)

        self.assertIn("datasetQualityScore", report)
        self.assertGreaterEqual(report["datasetQualityScore"], 80)
        
        breakdown = report["scoreBreakdown"]
        self.assertIn("dataHealthScoreDisplay", breakdown)
        self.assertIn("dq001_dimensions", breakdown)
        
        dimensions = breakdown["dq001_dimensions"]
        self.assertIn("completeness", dimensions)
        self.assertIn("validity", dimensions)
        self.assertIn("consistency", dimensions)
        self.assertIn("uniqueness", dimensions)
        self.assertIn("freshness", dimensions)
        self.assertIn("schema_compatibility", dimensions)

    def test_dq_001_service_pipeline_propagation(self):
        """DQ-001: Propagates Data Health Score to pipeline stages."""
        result = DataQualityService.propagate_health_score_to_pipeline(self.session)
        self.assertEqual(result["sessionId"], str(self.session.id))
        self.assertIn("data_health_score", result)
        self.assertIn("pipeline_stages", result)
        self.assertEqual(result["pipeline_stages"]["1_Import"]["status"], "COMPLETED")
