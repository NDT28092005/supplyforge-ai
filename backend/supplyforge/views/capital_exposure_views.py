"""
REST API Views for Task M5-09 Capital Exposure API & Persistence
Module 05: Capital Exposure & Aging Analysis
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from src.analytics.capital_exposure_repository import CapitalExposureRepository
from supplyforge.services.capital_exposure_service import CapitalExposureAnalysisService

from supplyforge.serializers.capital_exposure_serializer import (
    CapitalExposureAnalysisSerializer,
    CapitalExposureItemSerializer,
    CreateCapitalExposureAnalysisRequestSerializer
)

logger = logging.getLogger(__name__)


def _analysis_is_visible_to_request(request, analysis_rec):
    """Restrict authenticated requests to analyses created for their workspace.

    Legacy unauthenticated calls remain available in local development and the
    older repository tests. Deployed requests always pass tenant context in
    middleware and therefore cannot enumerate another workspace's analysis.
    """
    if not getattr(request, "tenant_context_validated", False):
        return True
    return analysis_rec.merchant_id == f"workspace:{request.workspace_id}"


@api_view(['POST'])
@permission_classes([AllowAny])
def create_capital_exposure_analysis(request):
    """
    POST /api/capital-exposure/analyses
    Queues a capital exposure analysis when the active dataset has no read model.

    The portfolio calculation is intentionally worker-only. Returning a 202
    prevents a first dashboard visit from monopolising a Gunicorn worker.
    """
    serializer = CreateCapitalExposureAnalysisRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    workspace_id = getattr(request, "workspace_id", None)
    if not (getattr(request, "tenant_context_validated", False) and workspace_id):
        return Response({"detail": "Yêu cầu cần workspace đã xác thực."}, status=status.HTTP_401_UNAUTHORIZED)

    analysis = CapitalExposureAnalysisService.get_current_analysis(int(workspace_id))
    if analysis:
        return Response(CapitalExposureAnalysisSerializer(analysis).data, status=status.HTTP_200_OK)

    from supplyforge.tasks import run_capital_exposure_analysis

    run_capital_exposure_analysis.delay(int(workspace_id))
    return Response({
        "status": "QUEUED",
        "code": "CAPITAL_ANALYSIS_QUEUED",
        "detail": "Phân tích vốn đang được chuẩn bị từ bộ dữ liệu đã nạp.",
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_latest_capital_exposure_analysis(request):
    """Return the completed analysis for the authenticated active workspace."""
    workspace_id = getattr(request, 'workspace_id', None)
    if not (getattr(request, 'tenant_context_validated', False) and workspace_id):
        return Response({"detail": "Yêu cầu cần workspace đã xác thực."}, status=status.HTTP_401_UNAUTHORIZED)

    analysis = CapitalExposureAnalysisService.get_current_analysis(int(workspace_id))
    if not analysis:
        return Response({
            'detail': 'Phân tích vốn chưa sẵn sàng cho bộ dữ liệu hiện tại.',
            'code': 'CAPITAL_ANALYSIS_PENDING',
        }, status=status.HTTP_409_CONFLICT)
    return Response(CapitalExposureAnalysisSerializer(analysis).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_analysis(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}
    Retrieves status and metadata for a specific analysis run.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = CapitalExposureAnalysisSerializer(analysis_rec)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_summary(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}/summary
    Retrieves executive summary KPIs for Capital Exposure Dashboard.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "analysis_id": analysis_rec.analysis_id,
        "merchant_id": analysis_rec.merchant_id,
        "dataset_version": analysis_rec.dataset_version,
        "status": analysis_rec.status,
        "summary": {
            "total_skus": analysis_rec.total_skus,
            "total_inventory_value": analysis_rec.total_inventory_value,
            "total_risk_weighted_exposure": analysis_rec.total_risk_weighted_exposure,
            "total_probability_adjusted_exposure": analysis_rec.total_probability_adjusted_exposure,
            "total_opportunity_cost": analysis_rec.total_opportunity_cost,
            "annual_opportunity_rate": analysis_rec.annual_opportunity_rate
        },
        "risk_distribution": analysis_rec.risk_distribution,
        "aging_distribution": analysis_rec.aging_distribution,
        "risk_aging_matrix": analysis_rec.risk_aging_matrix,
        "reconciliation_status": analysis_rec.reconciliation_status
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_capital_exposure_items(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}/items
    Returns paginated, filtered, and sorted SKU exposure item records.
    Query params: risk_level, aging_bucket, aging_priority, search, page, limit, sort.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    risk_level = request.query_params.get('risk_level')
    aging_bucket = request.query_params.get('aging_bucket')
    aging_priority = request.query_params.get('aging_priority')
    capital_band = request.query_params.get('capital_band')
    search = request.query_params.get('search')
    try:
        page = max(1, int(request.query_params.get('page', 1)))
        limit = min(100, max(1, int(request.query_params.get('limit', 50))))
    except (TypeError, ValueError):
        return Response({'detail': 'page và limit phải là số nguyên hợp lệ.'}, status=status.HTTP_400_BAD_REQUEST)
    sort = request.query_params.get('sort', '-risk_weighted_exposure')

    items, pagination_meta = CapitalExposureRepository.list_sku_items(
        analysis_id=analysis_id,
        risk_level=risk_level,
        aging_bucket=aging_bucket,
        aging_priority=aging_priority,
        capital_band=capital_band,
        search=search,
        page=page,
        limit=limit,
        sort=sort
    )

    serializer = CapitalExposureItemSerializer(items, many=True)
    return Response({
        "analysis_id": analysis_id,
        "pagination": pagination_meta,
        "items": serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_sku_detail(request, analysis_id, sku_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}/items/{sku_id}
    Retrieves full financial exposure detail for a single SKU.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    item = CapitalExposureRepository.get_sku_item_detail(analysis_id, sku_id)
    if not item:
        return Response({"detail": f"SKU '{sku_id}' not found in analysis '{analysis_id}'."}, status=status.HTTP_404_NOT_FOUND)

    serializer = CapitalExposureItemSerializer(item)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_aging_distribution(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}/aging
    Retrieves aging risk level breakdown for analysis_id.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "analysis_id": analysis_id,
        "aging_distribution": analysis_rec.aging_distribution
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_risk_distribution(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}/risk-distribution
    Retrieves slow-moving risk class breakdown for analysis_id.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec or not _analysis_is_visible_to_request(request, analysis_rec):
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "analysis_id": analysis_id,
        "risk_distribution": analysis_rec.risk_distribution
    }, status=status.HTTP_200_OK)
