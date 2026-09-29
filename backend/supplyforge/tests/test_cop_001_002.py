"""
Test suite for COP-001 Context Awareness & COP-002 Grounded Answers.

COP-001:
- Binds strictly to active context_sku (e.g. CRIT-024).

COP-002:
- Grounded answers strictly derived from 5 pillars:
  1. Risk
  2. Explanation
  3. Capital
  4. Decision
  5. Simulation
"""

from django.test import TestCase
from rest_framework.test import APIClient
from supplyforge.models.decision import DecisionRecord, DecisionExplanationRecord


class TestCopilotCOP001COP002(TestCase):

    def setUp(self):
        self.client = APIClient()

        # Create sample decision record
        self.decision = DecisionRecord.objects.create(
            decision_id="DEC-CRIT-024",
            sku="CRIT-024",
            risk_class="HIGH_RISK",
            risk_score=0.984,
            action_type="CLEARANCE",
            discount_rate=0.40,
            priority_tier="P1",
            priority_score=98,
            capital_exposure=93800000,
            expected_recovery_value=56280000
        )

    def test_cop_001_context_awareness(self):
        """COP-001: Verifies context binding to active SKU CRIT-024."""
        payload = {
            "query": "Tại sao AI đề xuất xả kho cho sản phẩm này?",
            "context_sku": "CRIT-024"
        }

        res = self.client.post("/api/v1/copilot/chat/", payload, format="json")
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["context_sku"], "CRIT-024")
        self.assertIn("CRIT-024", data["answer"])

    def test_cop_002_grounded_answers(self):
        """COP-002: Verifies response is strictly grounded in Risk, Explanation, Capital, Decision, Simulation."""
        payload = {
            "query": "Vốn tồn đọng và số tiền thu hồi dự kiến là bao nhiêu?",
            "context_sku": "CRIT-024"
        }

        res = self.client.post("/api/v1/copilot/chat/", payload, format="json")
        self.assertEqual(res.status_code, 200)

        data = res.json()
        self.assertTrue(data["success"])

        # Check evidence grounding pillars
        self.assertIn("RISK", data["grounded_pillars"])
        self.assertIn("CAPITAL", data["grounded_pillars"])
        self.assertIn("DECISION", data["grounded_pillars"])

        answer = data["answer"]
        self.assertIn("93.8M", answer)
        self.assertIn("56.3M", answer)
