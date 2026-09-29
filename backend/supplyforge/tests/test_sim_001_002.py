"""
Test suite for SIM-001 and SIM-002 Simulation Engine capabilities.

SIM-001 Requirements:
Merchant inputs:
- Discount = 15%
- Duration = 14 days

Backend calculates:
- expected_units_sold
- expected_revenue
- estimated_recovery
- discount_cost
- remaining_exposure

SIM-002 Requirements (Scenario Comparison):
Compares scenarios side by side (e.g. 10%, 15%, 20%):
- Expected sales
- Recovery
- Remaining capital
- Margin impact
"""

import os
import sys
from django.test import TestCase

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import DecisionContextBuilder
from src.analytics.discount_simulation_engine import DiscountSimulationEngine


class TestSimulationEngineSIM001SIM002(TestCase):

    def setUp(self):
        self.builder = DecisionContextBuilder()
        self.sim_engine = DiscountSimulationEngine()

        self.ctx = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SIM_TEST_SKU",
                "slow_moving_risk_class": "CRITICAL",
                "unit_price": 100000.0,
                "unit_cost": 70000.0,
                "stock_on_hand": 100
            },
            capital_record={
                "capital_exposure": 7000000.0,  # 100 * 70,000 = 7,000,000 VNĐ
                "inventory_age_days": 180
            }
        )

        # Attach explicit demand_context with sales_velocity_30d = 30.0 (1 unit/day)
        self.ctx["demand_context"] = {
            "sales_velocity_30d": 30.0,
            "sales_velocity_7d": 7.0
        }

    def test_sim_001_single_scenario_calculation(self):
        """SIM-001: Verifies interactive simulation for Discount=15% and Duration=14 days."""
        sim = self.sim_engine.simulate_single_scenario(
            decision_context=self.ctx,
            discount_rate=0.15,
            duration_days=14
        )

        self.assertEqual(sim["sku"], "SIM_TEST_SKU")
        self.assertEqual(sim["discount_rate"], 0.15)
        self.assertEqual(sim["duration_days"], 14)

        # Verified Outputs Required by SIM-001:
        self.assertIn("expected_units_sold", sim)
        self.assertIn("expected_revenue", sim)
        self.assertIn("estimated_recovery", sim)
        self.assertIn("discount_cost", sim)
        self.assertIn("remaining_exposure", sim)

        # Math check:
        # baseline daily vel = 30 / 30 = 1.0 unit/day
        # policy elasticity for 15% discount = 1.18
        # expected daily sales = 1.18
        # expected units sold for 14 days = 1.18 * 14 = 16.52 units
        self.assertEqual(sim["expected_units_sold"], 16.52)

        # simulated price = 100k * 0.85 = 85,000 VNĐ
        # expected revenue = 85,000 * 16.52 = 1,404,200 VNĐ
        self.assertEqual(sim["expected_revenue"], 1404200.0)

        # estimated recovery = min(1,404,200, 7,000,000) = 1,404,200 VNĐ
        self.assertEqual(sim["estimated_recovery"], 1404200.0)

        # discount cost = (100k - 85k) * 16.52 = 15,000 * 16.52 = 247,800 VNĐ
        self.assertEqual(sim["discount_cost"], 247800.0)

        # remaining exposure = 7,000,000 - 1,404,200 = 5,595,800 VNĐ
        self.assertEqual(sim["remaining_exposure"], 5595800.0)

    def test_sim_002_scenario_comparison(self):
        """SIM-002: Verifies side-by-side comparison across 10%, 15%, 20% discount scenarios."""
        cmp_result = self.sim_engine.compare_scenarios(
            decision_context=self.ctx,
            discount_rates=[0.10, 0.15, 0.20],
            duration_days=14
        )

        self.assertEqual(cmp_result["sku"], "SIM_TEST_SKU")
        self.assertEqual(cmp_result["duration_days"], 14)
        self.assertEqual(len(cmp_result["scenarios"]), 3)

        table = cmp_result["comparison_table"]
        self.assertEqual(table["headers"], ["10%", "15%", "20%"])

        metrics = table["metrics"]
        self.assertEqual(len(metrics["expected_sales"]), 3)
        self.assertEqual(len(metrics["recovery"]), 3)
        self.assertEqual(len(metrics["remaining_capital"]), 3)
        self.assertEqual(len(metrics["margin_impact"]), 3)

        # Expected sales should increase with higher discount rate
        self.assertLess(metrics["expected_sales"][0], metrics["expected_sales"][1])
        self.assertLess(metrics["expected_sales"][1], metrics["expected_sales"][2])
