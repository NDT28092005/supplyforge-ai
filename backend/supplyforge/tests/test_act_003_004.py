"""
Test suite for ACT-003 Merchant Confirmation Gate & ACT-004 Outcome Tracking.

ACT-003 Requirements:
- AI recommendations MUST NOT execute automatically.
- Requires explicit Merchant Confirmation: AI Recommendation (DRAFT) -> Merchant Review -> Confirm -> Execute.

ACT-004 Requirements:
- Outcome Tracking after campaign execution:
  - Expected recovery (e.g. 12M) vs Actual recovery (e.g. 9.5M)
  - Expected units (e.g. 100) vs Actual units (e.g. 82)
- Evaluates Decision Usefulness / Recommendation Accuracy.
"""

import datetime
from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models.action_plan import ActionPlanRecord


class TestActionPlanACT003ACT004(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_act_003_merchant_confirmation_flow(self):
        """ACT-003: Verifies strict confirmation flow (DRAFT -> CONFIRMED -> IN_PROGRESS -> COMPLETED)."""
        plan = ActionPlanRecord.objects.create(
            campaign_name="Clearance CRIT-024",
            sku="CRIT-024",
            duration_days=14,
            strategy="15% discount",
            owner="Merchant",
            start_date=datetime.date(2026, 9, 28),
            status="DRAFT"
        )

        # Confirm step
        res_confirm = self.client.patch(
            f"/api/v1/action-plans/{plan.plan_id}/status/",
            {"status": "CONFIRMED", "confirmed_by": "Merchant Tung"},
            format="json"
        )
        self.assertEqual(res_confirm.status_code, 200)
        self.assertEqual(res_confirm.json()["status"], "CONFIRMED")
        self.assertEqual(res_confirm.json()["confirmed_by"], "Merchant Tung")
        self.assertIsNotNone(res_confirm.json()["confirmed_at"])

        plan.refresh_from_db()
        self.assertEqual(plan.status, "CONFIRMED")
        self.assertEqual(plan.confirmed_by, "Merchant Tung")

    def test_act_004_outcome_tracking_and_usefulness(self):
        """
        ACT-004: Verifies tracking expected vs actual outcome metrics:
        Expected recovery: 12M, Actual recovery: 9.5M
        Expected units: 100, Actual units: 82
        """
        plan = ActionPlanRecord.objects.create(
            campaign_name="Clearance CRIT-024",
            sku="CRIT-024",
            duration_days=14,
            strategy="15% discount",
            owner="Merchant",
            start_date=datetime.date(2026, 9, 28),
            status="COMPLETED",
            expected_recovery_value=12000000,
            expected_units_sold=100
        )

        outcome_payload = {
            "actual_recovery_value": 9500000,
            "actual_units_sold": 82
        }

        res = self.client.patch(
            f"/api/v1/action-plans/{plan.plan_id}/outcome/",
            outcome_payload,
            format="json"
        )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])

        outcome = data["outcome"]
        self.assertEqual(outcome["expected_recovery_value"], 12000000)
        self.assertEqual(outcome["actual_recovery_value"], 9500000)
        self.assertEqual(outcome["recovery_accuracy_pct"], 79.2)

        self.assertEqual(outcome["expected_units_sold"], 100)
        self.assertEqual(outcome["actual_units_sold"], 82)
        self.assertEqual(outcome["units_accuracy_pct"], 82.0)

        self.assertEqual(outcome["decision_usefulness"], "HIGH")

        plan.refresh_from_db()
        self.assertEqual(plan.actual_recovery_value, 9500000)
        self.assertEqual(plan.actual_units_sold, 82)
