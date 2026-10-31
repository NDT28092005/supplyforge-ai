import os
import tempfile
from django.test import TestCase
from supplyforge.models import IngestionSession, Workspace
from supplyforge.tests.fixture_builders import create_large_shopee_orders_fixture
from src.ingestion.dataset_profiler import DatasetProfiler
import pandas as pd


class DatasetProfilerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — Task 02 Dataset Profiling."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test WS", slug="test-ws-profiler")
        self.fixture_dir = tempfile.TemporaryDirectory(prefix='supplyforge-profiler-')
        self.addCleanup(self.fixture_dir.cleanup)
        self.test_csv_path = create_large_shopee_orders_fixture(self.fixture_dir.name)
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="large_shopee_orders_50k.csv",
            storage_path=self.test_csv_path,
            status="PROFILED",
            total_rows=50000,
            total_columns=12,
        )

    def test_full_dataset_profiling(self):
        """Test full dataset profiling engine execution."""
        df = pd.read_csv(self.test_csv_path)
        profiler = DatasetProfiler(df=df, session_id=str(self.session.id))
        result = profiler.run_full_profile()

        # Check overview
        self.assertEqual(result['overview']['totalRecords'], 50000)
        self.assertEqual(result['overview']['uniqueSkus'], 8)
        self.assertEqual(result['overview']['observationPeriodDays'], 181)

        # Check readiness
        self.assertEqual(result['readiness']['status'], 'READY')
        self.assertEqual(result['readiness']['readinessScore'], 98.0)

        # Check sparsity metrics
        self.assertIn('avgZeroSalesRatePct', result['sparsity'])
        self.assertIn('avgSalesVelocity', result['sparsity'])

    def test_export_reports(self):
        """Test exporting all 4 report files to reports/."""
        df = pd.read_csv(self.test_csv_path)
        profiler = DatasetProfiler(df=df, session_id=str(self.session.id))
        profiler.run_full_profile()

        reports_dir = os.path.join(self.fixture_dir.name, 'reports')
        files = profiler.export_reports(output_dir=reports_dir)

        self.assertTrue(os.path.exists(files['dataset_profile']))
        self.assertTrue(os.path.exists(files['dataset_quality_report']))
        self.assertTrue(os.path.exists(files['data_quality_summary']))
