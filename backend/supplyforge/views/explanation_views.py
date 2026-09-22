"""
Task M4-08 — Explainability API & Persistence
Module 04: Slow-Moving Risk Explainability (XAI)

REST API Endpoints serving Canonical Risk Explanation Objects to Risk Dashboard
and Gemini Presentation Layer without performing any ML/XAI recalculation.
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from src.analytics.explanation_repository import ExplanationRepository, ExplanationRepositoryError
from supplyforge.serializers.explanation_serializer import (
    RiskExplanationRecordSerializer,
    BatchExplanationRequestSerializer
)

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_explanations_view(request):
    """
    GET /api/explanations
    Lists/filters canonical explanation objects.
    Query params: risk_class, diagnostic_signal, model_version, explanation_version, limit.
    """
    try:
        r_class = request.query_params.get('risk_class')
        diag_sig = request.query_params.get('diagnostic_signal')
        m_ver = request.query_params.get('model_version')
        e_ver = request.query_params.get('explanation_version')
        limit = int(request.query_params.get('limit', 100))

        repo = ExplanationRepository()
        explanations = repo.filter_explanations(
            risk_class=r_class,
            diagnostic_signal=diag_sig,
            model_version=m_ver,
            explanation_version=e_ver,
            limit=limit
        )

        return Response({
            "status": "success",
            "total_records": len(explanations),
            "explanations": explanations
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Failed in list_explanations_view: %s", e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_global_explanation_view(request):
    """
    GET /api/explanations/global
    Serves latest Global Population Model Explanation payload.
    """
    try:
        repo = ExplanationRepository()
        global_payload = repo.get_global_explanation()
        return Response(global_payload, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Failed in get_global_explanation_view: %s", e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def get_batch_explanations_view(request):
    """
    POST /api/explanations/batch
    Batch retrieves latest explanations for a list of SKUs.
    Body: {"skus": ["SKU_1", "SKU_2"]}
    """
    try:
        serializer = BatchExplanationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "status": "error",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        skus = serializer.validated_data["skus"]
        repo = ExplanationRepository()
        results = repo.get_batch_explanations(skus)

        return Response({
            "status": "success",
            "total_requested": len(skus),
            "explanations": results
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Failed in get_batch_explanations_view: %s", e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_sku_explanation_view(request, sku_id):
    """
    GET /api/explanations/{sku_id}
    Retrieves latest Canonical Risk Explanation Object for a specific SKU.
    """
    try:
        repo = ExplanationRepository()
        explanation = repo.get_latest_sku_explanation(sku_id)

        if not explanation:
            return Response({
                "status": "error",
                "message": f"No explanation found for SKU '{sku_id}'."
            }, status=status.HTTP_404_NOT_FOUND)

        return Response(explanation, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Failed in get_sku_explanation_view for SKU %s: %s", sku_id, e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_sku_explanation_history_view(request, sku_id):
    """
    GET /api/explanations/{sku_id}/history
    Retrieves historical explanation records for a SKU across model/explanation versions.
    """
    try:
        repo = ExplanationRepository()
        history = repo.get_sku_explanation_history(sku_id)

        return Response({
            "status": "success",
            "sku": sku_id,
            "total_records": len(history),
            "history": history
        }, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error("Failed in get_sku_explanation_history_view for SKU %s: %s", sku_id, e)
        return Response({
            "status": "error",
            "message": str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
