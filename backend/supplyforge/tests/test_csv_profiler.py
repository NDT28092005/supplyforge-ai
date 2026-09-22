import os
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.models import IngestionSession, Workspace


class StreamingCSVProfilerTestCase(TestCase):
    """Test suite for Module 01 Data Ingestion — Streaming CSV Profiler."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Workspace", slug="test-ws")
        self.test_csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "test-data", "large_shopee_orders_50k.csv"
        )

    def test_streaming_csv_profiling(self):
        """Verify streaming profiling on a 50,000 row CSV file."""
        self.assertTrue(os.path.exists(self.test_csv_path), "Test CSV file should exist")

        profile = StreamingCSVProfiler.profile_csv(self.test_csv_path)

        # 1. Total rows
        self.assertEqual(profile.total_rows, 50000)

        # 2. Total columns
        self.assertEqual(profile.total_columns, 12)
        self.assertIn("order_id", profile.headers)
        self.assertIn("item_sku", profile.headers)
        self.assertIn("order_date", profile.headers)

        # 3. Preview rows
        self.assertEqual(len(profile.preview_rows), 10)

        # 4. Date range
        self.assertIsNotNone(profile.date_range_start)
        self.assertIsNotNone(profile.date_range_end)
        self.assertEqual(profile.date_column_detected, "order_date")

        # 5. SKU count
        self.assertGreater(profile.unique_sku_count, 0)
        self.assertEqual(profile.sku_column_detected, "item_sku")

        # 6. Missing values detection (warehouse column had 5% missing)
        self.assertIn("warehouse", profile.missing_values)
        self.assertGreater(profile.missing_values["warehouse"]["count"], 0)

        print("\n[SUCCESS] Streaming CSV Profiler test passed!")
        print(f"  Rows: {profile.total_rows:,}")
        print(f"  Cols: {profile.total_columns}")
        print(f"  SKUs: {profile.unique_sku_count}")
        print(f"  Date Range: {profile.date_range_start} -> {profile.date_range_end}")
        print(f"  Missing Warehouse: {profile.missing_values.get('warehouse', {})}")
