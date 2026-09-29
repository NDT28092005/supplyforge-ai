import os
import sys
from datetime import datetime, timedelta
import pandas as pd
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models import IngestionSession, Workspace
from supplyforge.services.demand_service import DemandService
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer


class DemandPatternAndVelocityTestCase(TestCase):
    """Test suite for DEM-001 (Demand Pattern Classification) & DEM-002 (Velocity)."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Demand Test WS", slug="demand-test-ws")
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename="shopee_demand_test.csv",
            status="MAPPED",
            dataset_version="v1.0"
        )

        # Generate 90 days of transactions for 4 SKUs matching the 4 Syntetos-Boylan patterns
        base_date = datetime(2026, 9, 25)
        records = []

        # SKU 1: Smooth (high frequency sales, constant qty = 10) -> ADI ~ 1.0, CV2 = 0
        for d in range(90):
            dt = (base_date - timedelta(days=d)).strftime('%Y-%m-%d')
            records.append({'date': dt, 'sku': 'SKU_SMOOTH', 'canonical_sku_id': 'CSKU_SMOOTH', 'product_name': 'Smooth Product', 'quantity': 10})

        # SKU 2: Erratic (high frequency sales, highly variable qty = 1 or 100) -> ADI ~ 1.0, CV2 > 0.49
        for d in range(90):
            dt = (base_date - timedelta(days=d)).strftime('%Y-%m-%d')
            qty = 100 if d % 2 == 0 else 1
            records.append({'date': dt, 'sku': 'SKU_ERRATIC', 'canonical_sku_id': 'CSKU_ERRATIC', 'product_name': 'Erratic Product', 'quantity': qty})

        # SKU 3: Intermittent (low frequency sales e.g. every 5 days, constant qty = 10) -> ADI > 1.32, CV2 = 0
        for d in range(90):
            if d % 5 == 0:
                dt = (base_date - timedelta(days=d)).strftime('%Y-%m-%d')
                records.append({'date': dt, 'sku': 'SKU_INTERMITTENT', 'canonical_sku_id': 'CSKU_INTERMITTENT', 'product_name': 'Intermittent Product', 'quantity': 10})

        # SKU 4: Lumpy (low frequency sales e.g. every 10 days, highly variable qty = 5 or 200) -> ADI > 1.32, CV2 > 0.49
        for d in range(90):
            if d % 10 == 0:
                dt = (base_date - timedelta(days=d)).strftime('%Y-%m-%d')
                qty = 200 if d % 20 == 0 else 5
                records.append({'date': dt, 'sku': 'SKU_LUMPY', 'canonical_sku_id': 'CSKU_LUMPY', 'product_name': 'Lumpy Product', 'quantity': qty})

        self.transactions_df = pd.DataFrame(records)

    def test_dem_001_demand_pattern_classification(self):
        """DEM-001: Verify SKU classification into Smooth, Erratic, Intermittent, Lumpy with ADI, CV2, zero-rate."""
        res = DemandService.classify_demand_patterns(df=self.transactions_df, decision_date="2026-09-25")
        
        self.assertEqual(res["totalSkus"], 4)
        records = res["records"]
        sku_map = {r["sku"]: r for r in records}

        # Verify pattern assignments
        self.assertIn(sku_map["SKU_SMOOTH"]["demand_pattern"].title(), ["Smooth"])
        self.assertIn(sku_map["SKU_ERRATIC"]["demand_pattern"].title(), ["Erratic"])
        self.assertIn(sku_map["SKU_INTERMITTENT"]["demand_pattern"].title(), ["Intermittent"])
        self.assertIn(sku_map["SKU_LUMPY"]["demand_pattern"].title(), ["Lumpy"])

        # Verify ADI, CV2, and zero-rate presence
        for sku_key, r in sku_map.items():
            self.assertIn("adi", r)
            self.assertIn("cv2", r)
            self.assertIn("zero_rate_30d", r)
            self.assertIn("zero_rate_90d", r)

        # Critical Guardrail Assertion (DEM-001)
        self.assertIn("không phải ground truth slow-moving risk", res["academicNotice"])
        for r in records:
            self.assertEqual(r["classification_type"], "DEMAND_PATTERN_CLASSIFICATION")
            self.assertFalse(r["is_ground_truth_slow_moving_risk"])

    def test_dem_002_velocity_calculation(self):
        """DEM-002: Verify sales_velocity_7d, sales_velocity_30d, and sales_velocity_90d calculation."""
        velocities = DemandService.calculate_velocity(df=self.transactions_df, decision_date="2026-09-25")
        
        self.assertEqual(len(velocities), 4)
        v_map = {v["sku"]: v for v in velocities}

        # SKU_SMOOTH: sold 10 units every day for 90 days
        # 7d velocity = (7 * 10) / 7.0 = 10.0
        # 30d velocity = (30 * 10) / 30.0 = 10.0
        # 90d velocity = (90 * 10) / 90.0 = 10.0
        smooth_v = v_map["SKU_SMOOTH"]
        self.assertAlmostEqual(smooth_v["sales_velocity_7d"], 10.0, places=2)
        self.assertAlmostEqual(smooth_v["sales_velocity_30d"], 10.0, places=2)
        self.assertAlmostEqual(smooth_v["sales_velocity_90d"], 10.0, places=2)

        # Verify velocity keys present for all SKUs
        for v in velocities:
            self.assertIn("sales_velocity_7d", v)
            self.assertIn("sales_velocity_30d", v)
            self.assertIn("sales_velocity_90d", v)
            self.assertGreaterEqual(v["sales_velocity_7d"], 0.0)
            self.assertGreaterEqual(v["sales_velocity_30d"], 0.0)
            self.assertGreaterEqual(v["sales_velocity_90d"], 0.0)
