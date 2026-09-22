"""
Auto Decision Generator Service — Module 06 Decision Support
===========================================================
Automatically generates and persists M6 Decision Recommendations
for all at-risk SKUs after CSV data ingestion.
"""

import logging
from typing import List, Dict, Any

from supplyforge.models import Product, SlowMovingRiskAssessment
from supplyforge.services.decision_service import DecisionPersistenceService

logger = logging.getLogger(__name__)


class AutoDecisionGeneratorService:
    """Service to automatically construct and persist M6 Decision Recommendations."""

    @staticmethod
    def generate_decisions_from_assessments(user_id: str = "user_default_001") -> List[Any]:
        """
        Iterates over all SlowMovingRiskAssessment records and creates corresponding
        DecisionRecords in M6 DB table if not already existing.
        """
        assessments = SlowMovingRiskAssessment.objects.all()
        if not assessments.exists():
            from supplyforge.views.risk_assessment_api import _auto_populate_assessments_from_products
            _auto_populate_assessments_from_products()
            assessments = SlowMovingRiskAssessment.objects.all()

        products = {p.item_sku or p.third_party_id or f"SKU_{p.id}": p for p in Product.objects.all()}

        created_decisions = []
        action_map = {
            'CRITICAL': ('DISCOUNT_CLEARANCE', 0.35, 'P1', 'CRITICAL', 'HIGH'),
            'HIGH_RISK': ('BUNDLE_PROMOTION', 0.20, 'P2', 'HIGH', 'HIGH'),
            'MEDIUM_RISK': ('FLASH_SALE', 0.15, 'P3', 'MEDIUM', 'MEDIUM'),
            'LOW_RISK': ('MONITOR_INVENTORY', 0.0, 'P4', 'LOW', 'LOW'),
        }

        for idx, r in enumerate(assessments):
            p = products.get(r.sku)
            cost = float(p.cost or p.price or 50000) if p else 50000.0
            stock = int(p.stock or 100) if p else 100
            total_val = cost * stock

            act_type, discount, tier, urgency, confidence = action_map.get(
                r.risk_class, ('DISCOUNT_CLEARANCE', 0.25, 'P2', 'HIGH', 'MEDIUM')
            )

            # Recovery math
            recovery_rate = max(0.2, 1.0 - discount) if discount > 0 else 1.0
            expected_recovery = round(total_val * recovery_rate, 2)
            residual = round(total_val - expected_recovery, 2)

            recommendation_payload = {
                "recommendation_id": f"DEC-{r.sku}",
                "sku": r.sku,
                "risk_context": {
                    "risk_class": r.risk_class,
                    "risk_score": float(r.risk_score) / 100.0 if r.risk_score > 1.0 else float(r.risk_score)
                },
                "action": {
                    "type": act_type,
                    "discount_rate": discount if discount > 0 else None,
                    "parameters": {
                        "target_channels": ["Shopee Flash Sale", "Lazada Promo"],
                        "duration_days": 14 if tier == "P1" else 30
                    }
                },
                "priority": {
                    "tier": tier,
                    "score": round(float(r.risk_score) * (total_val / 10000000.0), 2),
                    "rank": idx + 1
                },
                "urgency": urgency,
                "confidence": confidence,
                "expected_impact": {
                    "capital_exposure": total_val,
                    "expected_recovery_value": expected_recovery,
                    "recovery_rate": round(recovery_rate, 2),
                    "residual_exposure": residual
                },
                "decision_status": "RECOMMENDED",
                "policy_version": "v1.0",
                "engine_version": "m6-v1.0"
            }

            explanation_payload = {
                "explanation_id": f"EXP-{r.sku}",
                "decision_summary": {
                    "sku": r.sku,
                    "product_name": r.product_name,
                    "recommendation": f"Áp dụng chiến dịch {act_type} (Giảm giá {int(discount*100)}%) cho {r.product_name}.",
                },
                "risk_explanation": {
                    "risk_class": r.risk_class,
                    "signals": r.primary_signals or ["LOW_SALES_VELOCITY"]
                },
                "capital_explanation": {
                    "capital_exposure": total_val,
                    "expected_recovery": expected_recovery
                },
                "reason_codes": r.primary_signals or ["LOW_SALES_VELOCITY", "HIGH_CAPITAL_EXPOSURE"],
                "confidence": confidence
            }

            try:
                dec = DecisionPersistenceService.persist_decision(
                    recommendation=recommendation_payload,
                    explanation=explanation_payload,
                    dataset_version="v1.3"
                )
                created_decisions.append(dec)
            except Exception as e:
                logger.error("Error auto-generating decision for SKU %s: %s", r.sku, e)

        return created_decisions
