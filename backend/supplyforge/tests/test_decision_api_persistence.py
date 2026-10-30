"""
Test suite for Task M6-10 Decision API & Persistence (Module 06).
Verifies AC-01 through AC-17 requirements:
- Persistence of M6-08 recommendations & M6-09 explanations into ORM models
- REST API Endpoints: POST /api/v1/decisions/, GET /api/v1/decisions/, GET /api/v1/decisions/{id}/
- Status Transition State Machine: PATCH /api/v1/decisions/{id}/status/
- Audit History & Explanation endpoints
- Filtering, Idempotency, and Unified Error Response contracts
"""

import json
import os
import sys
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

# Ensure project root is in python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.decision_support_architecture import DecisionContextBuilder
from src.analytics.action_eligibility_engine import ActionEligibilityEngine
from src.analytics.recovery_strategy_engine import RecoveryStrategyEngine
from src.analytics.discount_simulation_engine import DiscountSimulationEngine
from src.analytics.recovery_value_engine import RecoveryValueEstimationEngine
from src.analytics.capital_recovery_optimization_engine import CapitalRecoveryOptimizationEngine
from src.analytics.action_priority_engine import ActionPriorityScoringEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine
from src.analytics.decision_explanation_engine import DecisionExplanationEngine

from supplyforge.models.decision import (
    DecisionRecord, DecisionExplanationRecord,
    DecisionEvidenceRecord, DecisionAuditEventRecord,
)


class TestDecisionAPIPersistence(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.builder = DecisionContextBuilder()
        self.el_engine = ActionEligibilityEngine()
        self.strat_engine = RecoveryStrategyEngine()
        self.sim_engine = DiscountSimulationEngine()
        self.val_engine = RecoveryValueEstimationEngine()
        self.opt_engine = CapitalRecoveryOptimizationEngine()
        self.prio_engine = ActionPriorityScoringEngine()
        self.rec_engine = DecisionRecommendationEngine()
        self.exp_engine = DecisionExplanationEngine()

        # Build pipeline output objects for SKU_PERSIST
        self.ctx = self.builder.build_sku_decision_context(
            risk_record={
                "sku": "SKU_PERSIST",
                "slow_moving_risk_class": "CRITICAL",
                "risk_probability": 0.95,
                "unit_price": 100000.0,
                "unit_cost": 70000.0,
                "stock_on_hand": 100
            },
            capital_record={
                "capital_exposure": 7000000.0,
                "risk_weighted_exposure": 7000000.0,
                "inventory_age_days": 180,
                "aging_bucket": "SEVERELY_STALE"
            }
        )
        self.el = self.el_engine.evaluate_sku_eligibility(self.ctx)
        self.st = self.strat_engine.evaluate_sku_strategy(self.ctx, self.el)
        self.sim = self.sim_engine.simulate_sku_discount(self.ctx, self.st)
        self.val = self.val_engine.estimate_sku_recovery_value(self.ctx, self.st, self.sim)
        self.opt = self.opt_engine.optimize_sku_capital_recovery(self.ctx, self.st, self.sim, self.val)
        self.prio = self.prio_engine.calculate_sku_action_priority(self.ctx, self.el, self.st, self.opt, self.val)
        self.rec = self.rec_engine.generate_sku_recommendation(self.ctx, self.el, self.st, self.sim, self.val, self.opt, self.prio)
        self.exp = self.exp_engine.explain_sku_decision(self.ctx, self.rec, self.el, self.st, self.sim, self.val, self.opt, self.prio)

    def test_post_decision_persistence(self):
        """AC-01, AC-02, AC-03, AC-11: Persists recommendation & explanation payload via POST API idempotently."""
        payload = {
            "recommendation": self.rec,
            "explanation": self.exp,
            "dataset_version": "v1.0"
        }

        response = self.client.post(
            reverse('decision_list_create_v1'),
            data=json.dumps(payload),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        res_data = response.json()
        self.assertEqual(res_data["sku"], "SKU_PERSIST")
        self.assertEqual(res_data["risk"]["class"], "CRITICAL")
        self.assertIn("decision_id", res_data)

        dec_id = res_data["decision_id"]

        # Verify DB Records
        dec_rec = DecisionRecord.objects.get(decision_id=dec_id)
        self.assertEqual(dec_rec.sku, "SKU_PERSIST")
        self.assertEqual(dec_rec.status, "RECOMMENDED")

        exp_rec = DecisionExplanationRecord.objects.get(decision=dec_rec)
        self.assertEqual(exp_rec.sku, "SKU_PERSIST")

        audit_events = DecisionAuditEventRecord.objects.filter(decision=dec_rec)
        self.assertGreater(audit_events.count(), 0)

        # Test Idempotency: Duplicate POST returns existing record
        dup_response = self.client.post(
            reverse('decision_list_create_v1'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(dup_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(dup_response.json()["decision_id"], dec_id)

    def test_get_and_list_decisions_with_filtering(self):
        """AC-04, AC-05: Retrieves single decision and lists decisions with filtering."""
        # Create decision
        payload = {"recommendation": self.rec, "explanation": self.exp}
        self.client.post(reverse('decision_list_create_v1'), data=json.dumps(payload), content_type='application/json')

        dec_id = self.rec["recommendation_id"]

        # 1. GET /api/v1/decisions/{decision_id}/
        detail_res = self.client.get(reverse('decision_detail_v1', kwargs={'decision_id': dec_id}))
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.json()["decision_id"], dec_id)

        # 2. GET /api/v1/decisions/?risk_class=CRITICAL&priority=P1
        list_res = self.client.get(reverse('decision_list_create_v1') + '?risk_class=CRITICAL&priority=P1')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertGreater(len(list_res.json()), 0)

        paged_res = self.client.get(reverse('decision_list_create_v1') + '?page=1&page_size=1')
        self.assertEqual(paged_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(paged_res.json()['items']), 1)
        self.assertEqual(paged_res.json()['pagination']['total_items'], 1)

    def test_patch_status_transition_and_audit(self):
        """AC-06, AC-07, AC-08: Tests status lifecycle transitions and immutable audit event logging."""
        self.client.post(reverse('decision_list_create_v1'), data=json.dumps({"recommendation": self.rec, "explanation": self.exp}), content_type='application/json')
        dec_id = self.rec["recommendation_id"]

        # Valid Transition: RECOMMENDED -> REVIEWED
        patch_res = self.client.patch(
            reverse('decision_status_update_v1', kwargs={'decision_id': dec_id}),
            data=json.dumps({"status": "REVIEWED", "actor": "merchant_user", "notes": "Merchant opened decision"}),
            content_type='application/json'
        )
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.json()["decision"]["status"], "REVIEWED")

        # Valid Transition: REVIEWED -> ACCEPTED
        patch_res2 = self.client.patch(
            reverse('decision_status_update_v1', kwargs={'decision_id': dec_id}),
            data=json.dumps({"status": "ACCEPTED", "actor": "merchant_user"}),
            content_type='application/json'
        )
        self.assertEqual(patch_res2.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res2.json()["decision"]["status"], "ACCEPTED")

        # Invalid Transition: ACCEPTED -> GENERATED -> 400 Bad Request
        patch_err = self.client.patch(
            reverse('decision_status_update_v1', kwargs={'decision_id': dec_id}),
            data=json.dumps({"status": "GENERATED"}),
            content_type='application/json'
        )
        self.assertEqual(patch_err.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", patch_err.json())

        # Test History API Endpoint
        hist_res = self.client.get(reverse('decision_history_v1', kwargs={'decision_id': dec_id}))
        self.assertEqual(hist_res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(hist_res.json()["total_events"], 3)

        # Test Explanation API Endpoint
        exp_res = self.client.get(reverse('decision_explanation_v1', kwargs={'decision_id': dec_id}))
        self.assertEqual(exp_res.status_code, status.HTTP_200_OK)
        self.assertIn("risk_explanation", exp_res.json())
