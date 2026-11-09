"""Generate governed SKU decisions from the persisted risk assessment pipeline.

The previous implementation mapped every risk class to a fixed action. That
made the operations screen look decision-aware while bypassing eligibility,
financial guardrails and the explanation contract. This service is the only
automatic decision writer used after an assessment run, so it deliberately
orchestrates the same deterministic M6 pipeline that is used in validation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List

from supplyforge.models import DecisionRecord, Product, SlowMovingAssessmentRun, SlowMovingRiskAssessment
from supplyforge.services.commercial_fact_snapshot import CommercialFactSnapshotService
from supplyforge.services.decision_evidence_freshness import DecisionEvidenceFreshnessService
from supplyforge.services.decision_option_set import DecisionOptionSetService
from supplyforge.services.decision_service import DecisionPersistenceService

from src.analytics.action_eligibility_engine import ActionEligibilityEngine
from src.analytics.action_priority_engine import ActionPriorityScoringEngine
from src.analytics.capital_recovery_optimization_engine import CapitalRecoveryOptimizationEngine
from src.analytics.decision_explanation_engine import DecisionExplanationEngine
from src.analytics.decision_recommendation_engine import DecisionRecommendationEngine
from src.analytics.decision_support_architecture import DecisionContextBuilder
from src.analytics.discount_simulation_engine import DiscountSimulationEngine
from src.analytics.inventory_aging_engine import InventoryAgingEngine
from src.analytics.recovery_strategy_engine import RecoveryStrategyEngine
from src.analytics.recovery_value_engine import RecoveryValueEstimationEngine


logger = logging.getLogger(__name__)


PRICE_ACTIONS = {"DISCOUNT", "CLEARANCE", "PROMOTION"}
# Decisions already accepted or being executed carry a human commitment.  A
# later assessment run must never erase that commitment or its audit trail.
PROTECTED_DECISION_STATUSES = {"ACCEPTED", "EXECUTED"}
REPLACEABLE_DECISION_STATUSES = {
    "GENERATED", "RECOMMENDED", "NEEDS_REVIEW", "MONITOR", "NOT_APPLICABLE", "REVIEWED",
}
ACTIONABLE_ALERT_STATES = {"OPEN", "ACKNOWLEDGED"}


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class AutoDecisionGeneratorService:
    """Create an explainable, policy-governed recommendation per assessment."""

    @staticmethod
    def _products_for_workspace(
        assessments: Iterable[SlowMovingRiskAssessment], workspace_id: int | None,
    ) -> Dict[str, Product]:
        product_query = Product.objects.all()
        first = next(iter(assessments), None)
        if workspace_id is not None and first:
            owner_id = first.session.workspace.owner_id
            product_query = product_query.filter(user_id=str(owner_id or workspace_id))
        return {
            product.item_sku or product.canonical_sku or product.third_party_id or f"SKU_{product.id}": product
            for product in product_query.only(
                "id", "item_sku", "canonical_sku", "third_party_id", "product_name",
                "platform", "price", "cost", "stock", "data",
            )
        }

    @staticmethod
    def _decision_context(
        assessment: SlowMovingRiskAssessment,
        product: Product | None,
        commercial_facts: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        # Keep this helper usable by read-only callers that build a context for
        # inspection/tests.  The normal generator still captures the snapshot
        # once per assessment and passes it in explicitly before persisting a
        # decision.  Falling back here is deliberately a snapshot read, never
        # a read of mutable Product stock/price/cost fields.
        if commercial_facts is None:
            commercial_facts = CommercialFactSnapshotService.from_assessment(assessment)
        evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
        product_data = product.data if product and isinstance(product.data, dict) else {}

        inventory = commercial_facts.get("inventory") if isinstance(commercial_facts, dict) else {}
        demand = commercial_facts.get("demand") if isinstance(commercial_facts, dict) else {}
        readiness_snapshot = commercial_facts.get("readiness") if isinstance(commercial_facts, dict) else {}
        # Older compact snapshots can explicitly serialise an unavailable
        # section as JSON null.  Treat that exactly like missing evidence;
        # never let it crash a read path or become inferred financial input.
        inventory = inventory if isinstance(inventory, dict) else {}
        demand = demand if isinstance(demand, dict) else {}
        readiness_snapshot = readiness_snapshot if isinstance(readiness_snapshot, dict) else {}
        observed_inventory = bool(readiness_snapshot.get("inventory_observed"))
        # Product.stock is mutable operational metadata.  Only the compact
        # commercial snapshot may feed a financial recommendation.
        stock = _as_float(inventory.get("available_quantity")) if observed_inventory else None
        unit_cost = _as_float(inventory.get("unit_cost")) if observed_inventory else None
        unit_price = _as_float(inventory.get("unit_price")) if observed_inventory else None
        capital_exposure = _as_float(inventory.get("capital_exposure")) if observed_inventory else None

        dsls_raw = evidence.get("dsls")
        try:
            dsls = int(dsls_raw) if dsls_raw is not None else None
        except (TypeError, ValueError):
            dsls = None
        aging_bucket, _ = InventoryAgingEngine().classify_aging_bucket(dsls)
        velocity_30d = _as_float(demand.get("sales_velocity_30d"))
        velocity_7d = _as_float(evidence.get("sales_velocity_7d"))
        velocity_90d = _as_float(demand.get("sales_velocity_90d"))
        demand_context = {
            "sales_velocity_30d": velocity_30d,
            "sales_velocity_7d": velocity_7d,
            "sales_velocity_90d": velocity_90d,
        }
        demand_signal = DiscountSimulationEngine.observed_demand_signal({
            "demand_context": demand_context,
        })
        has_observed_velocity = demand_signal is not None
        has_positive_recent_demand = bool(
            demand_signal and float(demand_signal["daily_velocity"]) > 0
        )
        has_complete_financial_inputs = all(value is not None and value >= 0 for value in (stock, unit_cost, unit_price))
        data_health_score = 100 if observed_inventory and has_observed_velocity else 65 if has_complete_financial_inputs else 25

        calibrated_probability = None
        probability_status = "UNAVAILABLE"
        if (
            assessment.risk_probability is not None
            and str(evidence.get("probability_status") or "").upper() == "CALIBRATED_APPROVED"
        ):
            calibrated_probability = assessment.risk_probability
            probability_status = "CALIBRATED_APPROVED"
        risk_record = {
            "sku": assessment.sku,
            "canonical_sku_id": assessment.canonical_sku_id,
            "product_name": assessment.product_name,
            "category": assessment.category or (product.platform if product else "General"),
            "slow_moving_risk_class": assessment.risk_class,
            "risk_probability": calibrated_probability,
            "probability_status": probability_status,
            "risk_score": assessment.risk_score,
            "risk_signals": assessment.primary_signals,
            "diagnostic_signals": assessment.diagnostics,
            "model_version": assessment.model_version,
            "unit_price": unit_price,
            "unit_cost": unit_cost,
            "stock_on_hand": stock,
        }
        capital_record = {
            "capital_exposure": capital_exposure,
            # A rule priority cannot be multiplied by capital and presented as
            # probability-weighted exposure.
            "risk_weighted_exposure": None,
            "inventory_age_days": dsls,
            "aging_bucket": aging_bucket,
            "stock_on_hand": stock,
            "unit_cost": unit_cost,
            "unit_price": unit_price,
            "physical_stock_unobserved": not observed_inventory,
            "aging_flags": [] if observed_inventory else ["UNOBSERVED_STOCK"],
        }
        explainability_record = {
            "diagnostic_signals": assessment.diagnostics or assessment.primary_signals,
            "summary_text": "Tín hiệu được tạo từ dữ liệu lịch sử tại thời điểm đánh giá.",
        }
        context = DecisionContextBuilder().build_sku_decision_context(
            risk_record=risk_record,
            explainability_record=explainability_record,
            capital_record=capital_record,
            dataset_version=assessment.dataset_version or "v1.0",
        )
        context.update({
            "demand_context": {
                **demand_context,
                "sold_30d": _as_float(demand.get("sold_30d")),
                "sold_90d": _as_float(demand.get("sold_90d")),
                "observed": has_observed_velocity,
            },
            "has_enough_demand": has_positive_recent_demand,
            "has_positive_recent_demand": has_positive_recent_demand,
            "observation_period_days": _as_float(demand.get("sku_observed_days")) or (demand_signal["window_days"] if demand_signal else 0),
            "no_observed_sales_history": not has_positive_recent_demand,
            "active_campaign": bool(product_data.get("active_campaign", False)),
            "data_confidence": "SUFFICIENT" if data_health_score >= 65 else "INSUFFICIENT",
            "data_health_score": data_health_score,
            "bundle_partner_available": product_data.get("bundle_partner_available"),
            "open_purchase_order_quantity": _as_float(product_data.get("open_purchase_order_quantity")),
            "input_readiness": {
                "inventory_observed": observed_inventory,
                "demand_observed": has_observed_velocity,
                "demand_positive": has_positive_recent_demand,
                "demand_window_days": demand_signal["window_days"] if demand_signal else None,
                "financial_inputs_complete": has_complete_financial_inputs,
                "data_health_score": data_health_score,
            },
            "commercial_fact_snapshot": commercial_facts,
        })
        return context

    @staticmethod
    def _projection_is_usable(context: Dict[str, Any], strategy: Dict[str, Any]) -> bool:
        action = str(strategy.get("recommended_strategy") or "").upper()
        readiness = context.get("input_readiness", {})
        return bool(
            action in PRICE_ACTIONS
            and readiness.get("inventory_observed")
            and readiness.get("financial_inputs_complete")
            and readiness.get("demand_observed")
            and readiness.get("demand_positive")
        )

    @classmethod
    def generate_decisions_from_assessments(
        cls,
        user_id: str = "user_default_001",
        workspace_id: int | None = None,
    ) -> List[Any]:
        """Regenerate only replaceable decisions for the workspace's latest assessment set."""
        runs = SlowMovingAssessmentRun.objects.filter(
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
        )
        if workspace_id is not None:
            runs = runs.filter(workspace_id=workspace_id)
        current_runs = list(runs.order_by('source_key', '-completed_at'))
        if not current_runs:
            logger.info("No current completed operational assessment run exists for workspace %s.", workspace_id)
            return []

        assessments_query = SlowMovingRiskAssessment.objects.select_related(
            "session__workspace", "assessment_run",
        ).filter(
            assessment_run__in=current_runs,
            assessment_status='COMPLETE',
        )
        assessments = [
            assessment
            for assessment in assessments_query.order_by("assessment_run__source_key", "-risk_score", "sku")
            if (assessment.evidence or {}).get('alert_lifecycle_status') in ACTIONABLE_ALERT_STATES
        ]

        decisions_query = DecisionRecord.objects.all()
        if workspace_id is not None:
            decisions_query = decisions_query.filter(workspace_id=workspace_id)
        # Only unapproved recommendations can be refreshed.  Rejected and
        # completed records are also retained as audit evidence; accepted or
        # executing decisions block a competing fresh recommendation for the
        # same SKU until that action reaches a final state.
        protected_skus = set(
            decisions_query.filter(status__in=PROTECTED_DECISION_STATUSES)
            .values_list("sku", flat=True)
        )
        if not assessments:
            DecisionPersistenceService.supersede_replaceable_for_sources(
                workspace_id=workspace_id,
                source_keys=[run.source_key for run in current_runs],
                current_run_ids=[run.id for run in current_runs],
            )
            return []

        products = cls._products_for_workspace(assessments, workspace_id)
        evidence_snapshots = (
            DecisionEvidenceFreshnessService.capture_many(
                workspace_id=workspace_id,
                skus=[assessment.sku for assessment in assessments],
            )
            if workspace_id is not None else {}
        )
        eligibility_engine = ActionEligibilityEngine()
        strategy_engine = RecoveryStrategyEngine()
        simulation_engine = DiscountSimulationEngine()
        value_engine = RecoveryValueEstimationEngine()
        optimization_engine = CapitalRecoveryOptimizationEngine()
        priority_engine = ActionPriorityScoringEngine()
        recommendation_engine = DecisionRecommendationEngine()
        explanation_engine = DecisionExplanationEngine()

        candidates: list[dict[str, Any]] = []
        for assessment in assessments:
            if assessment.sku in protected_skus:
                logger.info(
                    "Skipping refresh for SKU %s because an accepted action is active.",
                    assessment.sku,
                )
                continue
            product = products.get(assessment.sku) or products.get(assessment.canonical_sku_id)
            commercial_facts = CommercialFactSnapshotService.from_assessment(assessment)
            context = cls._decision_context(assessment, product, commercial_facts)
            eligibility = eligibility_engine.evaluate_sku_eligibility(context)
            strategy = strategy_engine.evaluate_sku_strategy(context, eligibility)
            projection_usable = cls._projection_is_usable(context, strategy)
            simulation = simulation_engine.simulate_sku_discount(context, strategy) if projection_usable else None
            # A financial decision cannot continue from a withheld simulation.
            projection_usable = bool(
                projection_usable and simulation and simulation.get('evaluation_status') == 'READY'
                and simulation.get('scenarios')
            )
            value = value_engine.estimate_sku_recovery_value(context, strategy, simulation) if projection_usable else None
            optimization = (
                optimization_engine.optimize_sku_capital_recovery(context, strategy, simulation, value)
                if projection_usable else None
            )
            priority = priority_engine.calculate_sku_action_priority(
                context, eligibility, strategy, optimization, value,
            )
            candidates.append({
                "assessment": assessment,
                "context": context,
                "eligibility": eligibility,
                "strategy": strategy,
                "simulation": simulation,
                "value": value,
                "optimization": optimization,
                "priority": priority,
                "projection_usable": projection_usable,
            })

        # Rank the queue as a portfolio, not in database iteration order.
        candidates.sort(key=lambda candidate: candidate["priority"]["priority_score"], reverse=True)
        created_decisions: list[Any] = []
        for rank, candidate in enumerate(candidates, start=1):
            assessment = candidate["assessment"]
            context = candidate["context"]
            eligibility = candidate["eligibility"]
            strategy = candidate["strategy"]
            simulation = candidate["simulation"]
            value = candidate["value"]
            optimization = candidate["optimization"]
            priority = candidate["priority"]
            priority["rank"] = rank

            recommendation = recommendation_engine.generate_sku_recommendation(
                context, eligibility, strategy, simulation, value, optimization, priority,
            )
            # The source assessment, rather than the calendar date, gives each
            # recommendation a reproducible identity across assessment runs.
            recommendation["recommendation_id"] = f"REC-{assessment.session_id}-{assessment.id}"
            action_parameters = recommendation["action"].setdefault("parameters", {})
            alternatives = strategy.get("ranked_strategies", [])[:3]
            requires_review = bool(strategy.get("requires_review")) or recommendation["decision_status"] == "NEEDS_REVIEW"
            action_parameters.update({
                "strategy_id": recommendation["action"]["type"],
                # Rule-driven slow-moving decisions do not pretend to be
                # model-backed. A governed calibrated probability is opt-in
                # and carries explicit lineage when introduced.
                "model_runtime_required": bool(
                    context.get('risk_context', {}).get('probability_status') == 'CALIBRATED_APPROVED'
                ),
                "model_runtime": {
                    "source": "RISK_ASSESSMENT",
                    "assessment_model_version": assessment.model_version,
                },
                "alternative_strategies": alternatives,
                "eligibility": {
                    "eligible_actions": eligibility.get("eligible_actions", []),
                    "requires_review_actions": eligibility.get("requires_review_actions", []),
                    "blocked_actions": eligibility.get("blocked_actions", []),
                },
                "requires_review": requires_review,
                "approval_required": requires_review or recommendation["action"]["type"] in {"CLEARANCE", "STOP_REPLENISHMENT"},
                "input_readiness": context.get("input_readiness", {}),
                "commercial_fact_snapshot": commercial_facts,
                # This is a compact, immutable fingerprint of the verified
                # Odoo facts available when the recommendation was generated.
                # It is compared again before a price-sensitive action starts.
                "evidence_snapshot": evidence_snapshots.get(assessment.sku),
                "projection": {
                    "status": "SCENARIO_ESTIMATE" if candidate["projection_usable"] else "UNAVAILABLE",
                    "basis": "Observed sales velocity, inventory, price and cost" if candidate["projection_usable"] else "A financial scenario is not shown until observed demand, stock, price and cost are available.",
                    "simulation_policy_version": simulation.get("simulation_policy_version") if simulation else None,
                },
                "execution_guardrails": [
                    "No price, procurement or ERP document is changed automatically.",
                    "A merchant approval is required before execution.",
                ],
            })
            # Store the merchant display model together with the immutable
            # decision. It contains readiness/trade-offs, never strategy fit
            # scores masquerading as an ROI comparison.
            action_parameters["merchant_option_set"] = DecisionOptionSetService.build(
                recommendation=recommendation,
                eligibility=eligibility,
                commercial_facts=commercial_facts,
                projection_usable=candidate["projection_usable"],
                value=value,
                optimization=optimization,
            )
            readiness = context.get("input_readiness", {})
            if readiness.get("demand_observed") and not readiness.get("demand_positive"):
                action_parameters["operational_guidance"] = [
                    "Tạm dừng tái nhập sau khi đối chiếu các đơn mua đang mở.",
                    "Rà soát phương án xả kho ngoài kênh; hệ thống không có cơ sở để dự báo doanh số từ giảm giá.",
                ]
                recommendation["reason_codes"] = list(dict.fromkeys([
                    *recommendation.get("reason_codes", []),
                    "ZERO_RECENT_DEMAND_NO_PRICE_PROJECTION",
                ]))
            if not candidate["projection_usable"]:
                recommendation["expected_impact"] = {
                    "capital_exposure": context["capital_context"]["capital_exposure"],
                    "expected_recovery_value": 0.0,
                    "recovery_rate": 0.0,
                    "residual_exposure": context["capital_context"]["capital_exposure"],
                }
                recommendation["confidence"] = "LOW"
                recommendation["reason_codes"] = list(dict.fromkeys([
                    *recommendation.get("reason_codes", []),
                    "PROJECTION_UNAVAILABLE_MISSING_OBSERVED_INPUT",
                ]))

            explanation = explanation_engine.explain_sku_decision(
                context, recommendation, eligibility, strategy, simulation, value, optimization, priority,
            )
            explanation["limitations"] = list(dict.fromkeys([
                *explanation.get("limitations", []),
                "Recommendation selection is deterministic and policy-governed; it is not an automatic execution order.",
                "Operational outcomes require merchant input or ERP reconciliation and do not establish causal impact by themselves.",
            ]))

            try:
                decision = DecisionPersistenceService.persist_decision(
                    recommendation=recommendation,
                    explanation=explanation,
                    dataset_version=assessment.dataset_version or "v1.0",
                    workspace_id=workspace_id,
                    assessment_run=assessment.assessment_run,
                    decision_evidence_snapshot=commercial_facts,
                )
                created_decisions.append(decision)
            except Exception:
                logger.exception("Unable to persist governed decision for SKU %s", assessment.sku)
        DecisionPersistenceService.supersede_replaceable_for_sources(
            workspace_id=workspace_id,
            source_keys=[run.source_key for run in current_runs],
            current_run_ids=[run.id for run in current_runs],
        )
        return created_decisions
