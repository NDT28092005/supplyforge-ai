"""
Test suite for ACT-001 Create Action Plan & ACT-002 Action Status lifecycle management.

ACT-001 Requirements:
Merchant creates Action Plan with fields:
- Campaign: "Clearance CRIT-024"
- Duration: "14 days"
- Strategy: "15% discount"
- Owner: "Merchant"
- Start: "2026-09-28"

ACT-002 Requirements:
Supports status lifecycle transitions:
- DRAFT
- CONFIRMED
- IN_PROGRESS
- COMPLETED
- CANCELLED
"""

import datetime
from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models.action_plan import ActionPlanRecord


class TestActionPlanACT001ACT002(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_act_001_create_action_plan(self):
        """ACT-001: Verifies creation of an Action Plan with campaign, duration, strategy, owner, start date."""
        payload = {
            "campaign": "Clearance CRIT-024",
            "sku": "CRIT-024",
            "duration": 14,
            "strategy": "15% discount",
            "owner": "Merchant",
            "start": "2026-09-28",
            "status": "DRAFT"
        }

        res = self.client.post("/api/v1/action-plans/", payload, format="json")
        self.assertEqual(res.status_code, 201)

        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["campaign"], "Clearance CRIT-024")
        self.assertEqual(data["sku"], "CRIT-024")
        self.assertEqual(data["duration_days"], 14)
        self.assertEqual(data["strategy"], "15% discount")
        self.assertEqual(data["owner"], "Merchant")
        self.assertEqual(data["start_date"], "2026-09-28")
        self.assertEqual(data["status"], "DRAFT")

    def test_act_002_action_status_transitions(self):
        """ACT-002: The plan must follow approval, execution, then outcome recording."""
        plan = ActionPlanRecord.objects.create(
            campaign_name="Clearance CRIT-024",
            sku="CRIT-024",
            duration_days=14,
            strategy="15% discount",
            owner="Merchant",
            start_date=datetime.date(2026, 9, 28),
            status="DRAFT"
        )

        for next_status in ["CONFIRMED", "IN_PROGRESS"]:
            res = self.client.patch(
                f"/api/v1/action-plans/{plan.plan_id}/status/",
                {"status": next_status},
                format="json"
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], next_status)

            plan.refresh_from_db()
            self.assertEqual(plan.status, next_status)

        # Completion is not a selectable state; observed outcome closes a plan.
        completed_res = self.client.patch(
            f"/api/v1/action-plans/{plan.plan_id}/status/",
            {"status": "COMPLETED"},
            format="json"
        )
        self.assertEqual(completed_res.status_code, 400)
        self.assertEqual(completed_res.json()["error"]["code"], "OUTCOME_REQUIRED")

        outcome_res = self.client.patch(
            f"/api/v1/action-plans/{plan.plan_id}/outcome/",
            {"actual_recovery_value": 1000000, "actual_units_sold": 10},
            format="json"
        )
        self.assertEqual(outcome_res.status_code, 200)
        self.assertEqual(outcome_res.json()["status"], "COMPLETED")

    def test_act_002_invalid_status_blocking(self):
        """ACT-002: Verifies invalid status transition is rejected with 400 Bad Request."""
        plan = ActionPlanRecord.objects.create(
            campaign_name="Clearance TEST",
            sku="TEST-SKU",
            duration_days=7,
            strategy="20% discount",
            owner="Merchant",
            start_date=datetime.date(2026, 9, 28),
            status="DRAFT"
        )

        res = self.client.patch(
            f"/api/v1/action-plans/{plan.plan_id}/status/",
            {"status": "INVALID_STATUS_NAME"},
            format="json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()["success"])
