import os
import sys
from unittest.mock import patch
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from supplyforge.models import Workspace, IngestionSession, SlowMovingRiskAssessment
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.services.query_service import DashboardQueryService


class QueryServiceTestCase(TestCase):
    """Test suite for DashboardQueryService and Redis Cache Policy layer."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.workspace1 = Workspace.objects.create(name="WS 1", slug="ws-1")
        self.workspace2 = Workspace.objects.create(name="WS 2", slug="ws-2")

        self.session1 = IngestionSession.objects.create(
            workspace=self.workspace1,
            original_filename="orders1.csv",
            status="SUCCESS"
        )
        self.session2 = IngestionSession.objects.create(
            workspace=self.workspace2,
            original_filename="orders2.csv",
            status="SUCCESS"
        )

        # Populate 10 assessments for WS 1
        for i in range(1, 11):
            SlowMovingRiskAssessment.objects.create(
                session=self.session1,
                sku=f"SKU_{i:02d}",
                canonical_sku_id=f"CSKU_{i:02d}",
                product_name=f"Product {i}",
                risk_class="CRITICAL" if i <= 3 else ("HIGH_RISK" if i <= 6 else "LOW_RISK"),
                risk_probability=0.9 if i <= 3 else 0.7,
                risk_score=90.0 - i,
                evidence={
                    'capital_exposure_vnd': 100000.0 * i,
                    'dsls': 100 if i <= 5 else 30
                }
            )

    def test_executive_summary_cache_miss_then_hit(self):
        """Verify first call results in MISS and second call results in HIT."""
        summary1, status1 = DashboardQueryService.get_executive_summary(self.workspace1.id)
        self.assertIn(status1, ['MISS', 'HIT', 'REFRESHED'])
        self.assertTrue(summary1['hasData'])
        self.assertEqual(summary1['totalSkus'], 10)

        summary2, status2 = DashboardQueryService.get_executive_summary(self.workspace1.id)
        self.assertEqual(status2, 'HIT')
        self.assertEqual(summary2['totalSkus'], 10)

    def test_total_capital_aggregated_across_all_skus(self):
        """Verify total capital is aggregated across ALL 10 SKUs, not limited to top 5."""
        summary, _ = DashboardQueryService.get_executive_summary(self.workspace1.id)
        # Sum of 100,000 * i for i=1..10 is 100,000 * 55 = 5,500,000
        expected_total = sum(100000.0 * i for i in range(1, 11))
        self.assertEqual(summary['totalCapitalExposureVnd'], expected_total)
        self.assertEqual(len(summary['topRiskSkus']), 5)

    def test_workspace_cache_versioning_and_invalidation(self):
        """Verify bumping workspace cache version invalidates existing cache."""
        summary1, _ = DashboardQueryService.get_executive_summary(self.workspace1.id)
        v1 = summary1['cacheVersion']

        # Bump workspace version
        new_version = CachePolicy.bump_workspace_version(self.workspace1.id)
        self.assertNotEqual(str(v1), str(new_version))

        # Query again, should be cache MISS (or lock fetch) under new key version
        summary2, status2 = DashboardQueryService.get_executive_summary(self.workspace1.id)
        self.assertEqual(summary2['cacheVersion'], str(new_version))

    def test_workspace_isolation(self):
        """Verify queries for WS 1 and WS 2 maintain isolated cache entries."""
        # Create 1 assessment for WS 2
        SlowMovingRiskAssessment.objects.create(
            session=self.session2,
            sku="WS2_SKU_1",
            product_name="WS2 Product",
            risk_class="LOW_RISK",
            risk_probability=0.1,
            risk_score=10.0,
            evidence={'capital_exposure_vnd': 50000.0}
        )

        sum1, _ = DashboardQueryService.get_executive_summary(self.workspace1.id)
        sum2, _ = DashboardQueryService.get_executive_summary(self.workspace2.id)

        self.assertEqual(sum1['totalSkus'], 10)
        self.assertEqual(sum2['totalSkus'], 1)

    def test_failopen_on_redis_error(self):
        """Verify failopen behavior direct to MySQL when cache.get raises Exception."""
        with patch.object(cache, 'get', side_effect=RuntimeError("Redis connection dropped")):
            summary, status = DashboardQueryService.get_executive_summary(self.workspace1.id)
            self.assertEqual(status, 'FAILOVER_MYSQL')
            self.assertTrue(summary['hasData'])
            self.assertEqual(summary['totalSkus'], 10)

    def test_query_dashboard_summary_api(self):
        """Test GET /api/v2/query/dashboard-summary endpoint and custom response headers."""
        response = self.client.get(f'/api/v2/query/dashboard-summary?workspace_id={self.workspace1.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['hasData'])
        self.assertEqual(response.data['totalSkus'], 10)

        self.assertIn('X-Cache-Status', response.headers)
        self.assertIn('X-Cache-Version', response.headers)
        self.assertIn('X-Response-Time-ms', response.headers)

    def test_cache_refresh_api(self):
        """Test POST /api/v2/query/cache-refresh endpoint."""
        response = self.client.post('/api/v2/query/cache-refresh', {'workspace_id': self.workspace1.id}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'SUCCESS')
        self.assertEqual(response.headers.get('X-Cache-Status'), 'REFRESHED')

