"""
SF-OPS-07 Unit Tests — Telemetry Instrumentation for Decision Service and Query Service
"""
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.core.cache import cache

from supplyforge.metrics import (
    DECISION_GENERATED_TOTAL,
    DECISION_APPROVED_TOTAL,
    DECISION_REJECTED_TOTAL,
    SIMULATION_TOTAL,
    CACHE_HIT_TOTAL,
    CACHE_MISS_TOTAL,
    CACHE_ERROR_TOTAL,
    CACHE_REFRESH_TOTAL,
    CACHE_WARM_TOTAL,
)
from supplyforge.models.decision import DecisionRecord
from supplyforge.services.decision_service import DecisionPersistenceService, DecisionStatusService
from supplyforge.services.query_service import DashboardQueryService
from supplyforge.services.cache_warming_service import CacheWarmingService
from src.analytics.discount_simulation_engine import DiscountSimulationEngine


class DecisionTelemetryTest(TestCase):
    def test_ac01_decision_generated_telemetry(self):
        """AC-01: Verify successful decision generation increments supplyforge_decision_generated_total."""
        before_count = DECISION_GENERATED_TOTAL.labels(
            decision_type="DISCOUNT_CLEARANCE", status="success"
        )._value.get()

        recommendation_payload = {
            "recommendation_id": "DEC-TEST-001",
            "sku": "SKU-TEST-001",
            "action": {"type": "DISCOUNT_CLEARANCE", "discount_rate": 0.25},
            "risk_context": {"risk_class": "CRITICAL", "risk_score": 0.9},
            "priority": {"tier": "P1", "score": 90.0, "rank": 1},
            "expected_impact": {"capital_exposure": 100000.0, "expected_recovery_value": 75000.0}
        }

        dec = DecisionPersistenceService.persist_decision(recommendation_payload)
        self.assertIsNotNone(dec)

        after_count = DECISION_GENERATED_TOTAL.labels(
            decision_type="DISCOUNT_CLEARANCE", status="success"
        )._value.get()
        self.assertEqual(after_count, before_count + 1)

    def test_ac02_ac03_decision_approved_rejected_telemetry(self):
        """AC-02 & AC-03: Verify approval/rejection status transition increments approved/rejected metric."""
        recommendation_payload = {
            "recommendation_id": "DEC-TEST-002",
            "sku": "SKU-TEST-002",
            "action": {"type": "PO_REORDER", "discount_rate": 0.0},
            "risk_context": {"risk_class": "MEDIUM_RISK", "risk_score": 0.5},
            "decision_status": "GENERATED"
        }
        dec = DecisionPersistenceService.persist_decision(recommendation_payload)

        before_approved = DECISION_APPROVED_TOTAL.labels(decision_type="PO_REORDER")._value.get()
        DecisionStatusService.update_status(dec.decision_id, new_status="REVIEWED")
        after_approved = DECISION_APPROVED_TOTAL.labels(decision_type="PO_REORDER")._value.get()
        self.assertEqual(after_approved, before_approved + 1)

        before_rejected = DECISION_REJECTED_TOTAL.labels(decision_type="PO_REORDER")._value.get()
        DecisionStatusService.update_status(dec.decision_id, new_status="REJECTED")
        after_rejected = DECISION_REJECTED_TOTAL.labels(decision_type="PO_REORDER")._value.get()
        self.assertEqual(after_rejected, before_rejected + 1)

    def test_ac04_simulation_telemetry(self):
        """AC-04: Verify simulation execution increments supplyforge_simulation_total."""
        before_sim = SIMULATION_TOTAL.labels(
            simulation_type="DISCOUNT_SIMULATION", status="success"
        )._value.get()

        sim_engine = DiscountSimulationEngine()
        decision_ctx = {
            "sku": "SKU-SIM-001",
            "unit_price": 100000.0,
            "unit_cost": 70000.0,
            "stock_on_hand": 50,
            "capital_context": {"capital_exposure": 3500000.0},
            "risk_context": {"risk_class": "CRITICAL"}
        }
        strat_res = {"recommended_strategy": "DISCOUNT"}

        sim_engine.simulate_sku_discount(decision_ctx, strat_res)

        after_sim = SIMULATION_TOTAL.labels(
            simulation_type="DISCOUNT_SIMULATION", status="success"
        )._value.get()
        self.assertEqual(after_sim, before_sim + 1)


class QueryCacheTelemetryTest(TestCase):
    def setUp(self):
        cache.clear()

    @patch("supplyforge.services.query_service.DashboardQueryService._active_gold_dashboard_summary")
    def test_ac05_ac06_cache_hit_miss_telemetry(self, mock_gold):
        """AC-05 & AC-06: Verify Cache MISS and Cache HIT record metrics accurately."""
        mock_gold.return_value = {"hasData": False, "totalSkus": 0}

        before_miss = CACHE_MISS_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()
        res1, status1 = DashboardQueryService.get_executive_summary(workspace_id=999)
        self.assertEqual(status1, "MISS_GOLD")

        after_miss = CACHE_MISS_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()
        self.assertEqual(after_miss, before_miss + 1)

        before_hit = CACHE_HIT_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()
        res2, status2 = DashboardQueryService.get_executive_summary(workspace_id=999)
        # A cached negative response is safely repaired if a read model becomes
        # available between calls. Both values are cache hits and must count as
        # one in telemetry.
        self.assertIn(status2, {"HIT", "HIT_REPAIRED"})

        after_hit = CACHE_HIT_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()
        self.assertEqual(after_hit, before_hit + 1)

    @patch("supplyforge.services.query_service.DashboardQueryService._calculate_executive_summary")
    def test_ac08_cache_refresh_and_warm_telemetry(self, mock_calc):
        """AC-08: Verify force refresh and proactive warm record refresh/warm metrics."""
        mock_calc.return_value = {"hasData": False, "totalSkus": 0}

        before_refresh = CACHE_REFRESH_TOTAL.labels(cache_area="dashboard")._value.get()
        DashboardQueryService.get_executive_summary(workspace_id=999, force_refresh=True)
        after_refresh = CACHE_REFRESH_TOTAL.labels(cache_area="dashboard")._value.get()
        self.assertEqual(after_refresh, before_refresh + 1)

        before_warm = CACHE_WARM_TOTAL.labels(cache_area="dashboard")._value.get()
        CacheWarmingService.warm_workspace_cache(workspace_id=999)
        after_warm = CACHE_WARM_TOTAL.labels(cache_area="dashboard")._value.get()
        self.assertEqual(after_warm, before_warm + 1)

    @patch("django.core.cache.cache.get")
    @patch("supplyforge.services.query_service.DashboardQueryService._active_gold_dashboard_summary")
    def test_ac07_cache_error_telemetry(self, mock_gold, mock_cache_get):
        """AC-07: Redis error serves gold data without an HTTP SKU scan."""
        mock_cache_get.side_effect = Exception("Redis Connection Refused")
        mock_gold.return_value = {"hasData": False, "totalSkus": 0}

        before_err = CACHE_ERROR_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()
        res, status = DashboardQueryService.get_executive_summary(workspace_id=999)
        after_err = CACHE_ERROR_TOTAL.labels(cache_area="dashboard", operation="get")._value.get()

        self.assertEqual(status, "STALE_GOLD")
        self.assertEqual(after_err, before_err + 1)
