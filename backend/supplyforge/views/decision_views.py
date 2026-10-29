"""
REST API Views for Task M6-10 Decision API & Persistence.
Module 06: Decision Support & Capital Recovery Engine

Provides REST endpoints:
- POST /api/v1/decisions/: Persist recommendation & explanation.
- GET /api/v1/decisions/: List decisions with filtering.
- GET /api/v1/decisions/{decision_id}/: Retrieve full decision contract.
- PATCH /api/v1/decisions/{decision_id}/status/: Update decision status & log audit.
- GET /api/v1/decisions/{decision_id}/history/: Retrieve audit timeline.
- GET /api/v1/decisions/{decision_id}/explanation/: Retrieve explanation payload & evidence.
"""

from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from supplyforge.models import Product
from supplyforge.models.decision import DecisionRecord, DecisionExplanationRecord
from supplyforge.serializers.decision_serializer import (
    DecisionSerializer, DecisionExplanationSerializer,
    DecisionAuditEventSerializer, DecisionStatusUpdateSerializer,
)
from supplyforge.services.decision_service import (
    DecisionPersistenceService, DecisionStatusService, DecisionHistoryService,
    InvalidStatusTransitionError, DecisionNotFoundError,
)


def _decision_is_visible_to_request(request, decision):
    """Check the persisted workspace scope of a decision record."""
    if not getattr(request, "tenant_context_validated", False):
        return True
    return decision.workspace_id == request.workspace_id


def _decision_queryset_for_request(request, queryset):
    if not getattr(request, "tenant_context_validated", False):
        return queryset
    return queryset.filter(workspace_id=request.workspace_id)


class DecisionListCreateView(APIView):
    """
    POST /api/v1/decisions/: Persist a new recommendation and explanation.
    GET /api/v1/decisions/: List decisions with filtering.
    """

    def post(self, request, *args, **kwargs):
        payload = request.data
        if not payload or ("recommendation" not in payload and "sku" not in payload):
            return Response(
                {"success": False, "error": {"code": "INVALID_DECISION", "message": "Missing recommendation or SKU payload."}},
                status=status.HTTP_400_BAD_REQUEST
            )

        recommendation = payload.get("recommendation") or payload
        explanation = payload.get("explanation")
        dataset_version = payload.get("dataset_version", "v1.0")

        try:
            decision = DecisionPersistenceService.persist_decision(
                recommendation=recommendation,
                explanation=explanation,
                dataset_version=dataset_version,
                workspace_id=request.workspace_id if getattr(request, "tenant_context_validated", False) else None,
            )
            serializer = DecisionSerializer(decision)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"success": False, "error": {"code": "INVALID_DECISION", "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST
            )

    def get(self, request, *args, **kwargs):
        risk_class = request.query_params.get("risk_class")
        priority = request.query_params.get("priority")
        action_type = request.query_params.get("action_type")
        status_param = request.query_params.get("status")
        sku = request.query_params.get("sku")
        dataset_version = request.query_params.get("dataset_version")

        queryset = DecisionPersistenceService.list_decisions(
            risk_class=risk_class,
            priority=priority,
            action_type=action_type,
            status=status_param,
            sku=sku,
            dataset_version=dataset_version,
            workspace_id=request.workspace_id if getattr(request, "tenant_context_validated", False) else None,
        )
        queryset = _decision_queryset_for_request(request, queryset)

        serializer = DecisionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DecisionDetailView(APIView):
    """GET /api/v1/decisions/{decision_id}/: Retrieve a single decision context by decision_id."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            serializer = DecisionSerializer(decision)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionStatusUpdateView(APIView):
    """PATCH /api/v1/decisions/{decision_id}/status/: Update decision lifecycle status."""

    def patch(self, request, decision_id, *args, **kwargs):
        serializer = DecisionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"success": False, "error": {"code": "INVALID_STATUS", "message": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_status = serializer.validated_data["status"]
        actor = serializer.validated_data.get("actor", "merchant")
        notes = serializer.validated_data.get("notes", "")

        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            decision = DecisionStatusService.update_status(
                decision_id=decision_id,
                new_status=new_status,
                actor=actor,
                notes=notes
            )
            response_serializer = DecisionSerializer(decision)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )
        except InvalidStatusTransitionError as e:
            return Response(
                {"success": False, "error": {"code": "INVALID_STATUS_TRANSITION", "message": str(e)}},
                status=status.HTTP_400_BAD_REQUEST
            )


class DecisionHistoryView(APIView):
    """GET /api/v1/decisions/{decision_id}/history/: Retrieve decision audit timeline history."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            history_data = DecisionHistoryService.get_history(decision_id)
            return Response(history_data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionExplanationView(APIView):
    """GET /api/v1/decisions/{decision_id}/explanation/: Retrieve M6-09 explanation payload."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
            if not _decision_is_visible_to_request(request, decision):
                raise DecisionNotFoundError(f"Decision {decision_id} not found.")
            exp = decision.explanations.first()
            if not exp:
                return Response(
                    {"success": False, "error": {"code": "EXPLANATION_NOT_FOUND", "message": f"Explanation not found for decision {decision_id}."}},
                    status=status.HTTP_404_NOT_FOUND
                )
            serializer = DecisionExplanationSerializer(exp)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except DecisionNotFoundError as e:
            return Response(
                {"success": False, "error": {"code": "DECISION_NOT_FOUND", "message": str(e)}},
                status=status.HTTP_404_NOT_FOUND
            )


class DecisionSimulationView(APIView):
    """
    POST /api/v1/decisions/simulate/: SIM-001 & SIM-002 Simulation Engine Endpoint.
    
    Merchant Inputs:
    - discount_rate (default 0.15)
    - duration_days (default 14)
    - discount_rates (default [0.10, 0.15, 0.20])
    - decision_context or decision_id
    """

    def post(self, request, *args, **kwargs):
        from src.analytics.discount_simulation_engine import DiscountSimulationEngine

        payload = request.data or {}
        discount_rate = float(payload.get("discount_rate", 0.15))
        duration_days = int(payload.get("duration_days", 14))
        custom_rates = payload.get("discount_rates", [0.10, 0.15, 0.20])

        decision_ctx = payload.get("decision_context") or {}
        decision_id = payload.get("decision_id")

        if not decision_ctx and decision_id:
            try:
                decision_rec = DecisionPersistenceService.get_decision(decision_id)
                if not _decision_is_visible_to_request(request, decision_rec):
                    raise DecisionNotFoundError(f"Decision {decision_id} not found.")
                product_query = Product.objects.filter(item_sku=decision_rec.sku)
                if getattr(request, "tenant_context_validated", False):
                    product_query = product_query.filter(user_id=str(request.user_id))
                product = product_query.first()
                if not product or product.price is None or product.cost is None or product.stock is None:
                    return Response({
                        "success": False,
                        "code": "SIMULATION_INPUT_UNAVAILABLE",
                        "detail": "SKU chưa có đủ giá bán, giá vốn và tồn kho để mô phỏng.",
                    }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
                decision_ctx = {
                    "sku": decision_rec.sku,
                    "unit_price": float(product.price),
                    "unit_cost": float(product.cost),
                    "stock_on_hand": float(product.stock),
                    "capital_context": {
                        "capital_exposure": float(decision_rec.capital_exposure)
                    }
                }
            except DecisionNotFoundError:
                return Response({
                    "success": False,
                    "code": "DECISION_NOT_FOUND",
                    "detail": "Không tìm thấy đề xuất thuộc bộ dữ liệu hiện tại.",
                }, status=status.HTTP_404_NOT_FOUND)

        if not decision_ctx:
            return Response({
                "success": False,
                "code": "SIMULATION_INPUT_REQUIRED",
                "detail": "Cần chọn một đề xuất có dữ liệu SKU để chạy mô phỏng.",
            }, status=status.HTTP_400_BAD_REQUEST)

        sim_engine = DiscountSimulationEngine()
        sim_001 = sim_engine.simulate_single_scenario(
            decision_context=decision_ctx,
            discount_rate=discount_rate,
            duration_days=duration_days
        )
        sim_002 = sim_engine.compare_scenarios(
            decision_context=decision_ctx,
            discount_rates=custom_rates,
            duration_days=duration_days
        )

        return Response({
            "success": True,
            "sku": decision_ctx.get("sku"),
            "sim_001": sim_001,
            "sim_002": sim_002
        }, status=status.HTTP_200_OK)
