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

from supplyforge.models.decision import DecisionRecord, DecisionExplanationRecord
from supplyforge.serializers.decision_serializer import (
    DecisionSerializer, DecisionExplanationSerializer,
    DecisionAuditEventSerializer, DecisionStatusUpdateSerializer,
)
from supplyforge.services.decision_service import (
    DecisionPersistenceService, DecisionStatusService, DecisionHistoryService,
    InvalidStatusTransitionError, DecisionNotFoundError,
)


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
                dataset_version=dataset_version
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
            dataset_version=dataset_version
        )

        serializer = DecisionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DecisionDetailView(APIView):
    """GET /api/v1/decisions/{decision_id}/: Retrieve a single decision context by decision_id."""

    def get(self, request, decision_id, *args, **kwargs):
        try:
            decision = DecisionPersistenceService.get_decision(decision_id)
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
