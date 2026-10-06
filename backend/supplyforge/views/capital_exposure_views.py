"""
REST API Views for Task M5-09 Capital Exposure API & Persistence
Module 05: Capital Exposure & Aging Analysis
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

import pandas as pd

from src.analytics.capital_exposure_repository import CapitalExposureRepository
from src.analytics.capital_valuation_engine import CapitalValuationEngine
from src.analytics.inventory_aging_engine import InventoryAgingEngine
from src.analytics.risk_weighted_exposure_engine import RiskWeightedExposureEngine
from src.analytics.aging_risk_classifier import AgingRiskClassifier
from src.analytics.capital_exposure_aggregator import CapitalExposureAggregator
from src.analytics.financial_impact_engine import FinancialImpactEngine

from supplyforge.serializers.capital_exposure_serializer import (
    CapitalExposureAnalysisSerializer,
    CapitalExposureItemSerializer,
    CreateCapitalExposureAnalysisRequestSerializer
)

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def create_capital_exposure_analysis(request):
    """
    POST /api/capital-exposure/analyses
    Triggers or registers a new Capital Exposure Analysis run.
    Runs pipeline M5-02 -> M5-08 and persists results atomically via Repository.
    """
    serializer = CreateCapitalExposureAnalysisRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    merchant_id = data.get("merchant_id", "default_merchant")
    dataset_version = data.get("dataset_version", "v1.0")
    annual_rate = data.get("annual_opportunity_rate", 0.12)
    aid = data.get("analysis_id")

    try:
        from supplyforge.models import IngestionSession, SlowMovingRiskAssessment, Order, Product
        from datetime import datetime, timedelta
        from django.db.models import Max

        latest_session = IngestionSession.objects.filter(risk_assessments__isnull=False).order_by('-created_at').first()
        assessments_qs = SlowMovingRiskAssessment.objects.filter(session=latest_session) if latest_session else SlowMovingRiskAssessment.objects.all()

        if assessments_qs.exists():
            # Determine reference date from actual data
            max_order_dt = Order.objects.aggregate(Max('created_at'))['created_at__max']
            ref_date = max_order_dt if max_order_dt else datetime.now()
            if hasattr(ref_date, 'tzinfo') and ref_date.tzinfo is not None:
                ref_date = ref_date.replace(tzinfo=None)

            product_rows = []
            risk_assessments = []
            for a in assessments_qs:
                ev = a.evidence if isinstance(a.evidence, dict) else {}
                stock = int(ev.get('stock_quantity') or 0)
                cost = float(ev.get('unit_cost') or 0.0)
                dsls = int(ev.get('dsls') or 0)
                cap_exp = float(ev.get('capital_exposure_vnd') or (stock * cost))
                r_prob = float(a.risk_probability or 0.0)
                r_score = float(a.risk_score or 0.0)

                product_rows.append({
                    'sku': a.sku,
                    'product_name': a.product_name,
                    'category': a.category or 'Tồn kho',
                    'stock_on_hand': stock,
                    'unit_cost': cost,
                    'dsls': dsls,
                    'capital_exposure_vnd': cap_exp,
                    'last_sale_date': None,
                })

                risk_assessments.append({
                    'sku': a.sku,
                    'risk_class': a.risk_class,
                    'risk_probability': r_prob,
                    'risk_score': r_score,
                })

            sample_df = pd.DataFrame(product_rows)
        else:
            ref_date = datetime.now()
            product_rows = [
                {
                    'sku': f'SKU_100{i}',
                    'product_name': f'Sample Product 100{i}',
                    'category': 'Electronics' if i % 2 == 0 else 'Apparel',
                    'stock_on_hand': 20 * i,
                    'unit_cost': 50.0 * i,
                    'dsls': 15 * i,
                    'last_sale_date': (ref_date - timedelta(days=15 * i)).strftime('%Y-%m-%d'),
                }
                for i in range(1, 6)
            ]
            sample_df = pd.DataFrame(product_rows)
            risk_assessments = [
                {
                    'sku': f'SKU_100{i}',
                    'risk_class': 'HIGH_RISK' if i > 3 else 'LOW_RISK',
                    'risk_probability': 0.8 if i > 3 else 0.15,
                    'risk_score': 80.0 if i > 3 else 15.0,
                }
                for i in range(1, 6)
            ]

        # Generate sample pipeline dataset if no custom data attached
        val_engine = CapitalValuationEngine()
        aging_engine = InventoryAgingEngine()
        exposure_engine = RiskWeightedExposureEngine()
        classifier = AgingRiskClassifier()
        aggregator = CapitalExposureAggregator()
        impact_engine = FinancialImpactEngine(default_opportunity_rate=annual_rate)

        sku_val_records, val_summary = val_engine.value_dataset(sample_df, risk_assessments)
        aging_records, matrix, aging_summary = aging_engine.analyze_dataset_aging(sku_val_records, analysis_date=ref_date.strftime('%Y-%m-%d') if 'ref_date' in dir() and ref_date else '2026-08-23')
        exposure_records, portfolio_summary = exposure_engine.evaluate_portfolio_exposure(aging_records)
        assessments, risk_dist, prio_dist, summary = classifier.evaluate_dataset_aging_risk(exposure_records)
        fin_summary = impact_engine.evaluate_portfolio_financial_impact(assessments, annual_rate=annual_rate)

        # Persist via Repository
        analysis_rec = CapitalExposureRepository.save_analysis(
            summary_payload=fin_summary,
            sku_assessment_records=assessments,
            merchant_id=merchant_id,
            dataset_version=dataset_version,
            analysis_id=aid
        )

        res_serializer = CapitalExposureAnalysisSerializer(analysis_rec)
        return Response(res_serializer.data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error("Failed to create capital exposure analysis: %s", e, exc_info=True)
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_capital_exposure_analysis(request, analysis_id):
    """
    GET /api/capital-exposure/analyses/{analysis_id}
    Retrieves status and metadata for a specific analysis run.
    """
    analysis_rec = CapitalExposureRepository.get_analysis(analysis_id)
    if not analysis_rec:
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
    if not analysis_rec:
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
    if not analysis_rec:
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    risk_level = request.query_params.get('risk_level')
    aging_bucket = request.query_params.get('aging_bucket')
    aging_priority = request.query_params.get('aging_priority')
    search = request.query_params.get('search')
    page = int(request.query_params.get('page', 1))
    limit = int(request.query_params.get('limit', 500))
    sort = request.query_params.get('sort', '-risk_weighted_exposure')

    items, pagination_meta = CapitalExposureRepository.list_sku_items(
        analysis_id=analysis_id,
        risk_level=risk_level,
        aging_bucket=aging_bucket,
        aging_priority=aging_priority,
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
    if not analysis_rec:
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
    if not analysis_rec:
        return Response({"detail": f"Analysis run '{analysis_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        "analysis_id": analysis_id,
        "risk_distribution": analysis_rec.risk_distribution
    }, status=status.HTTP_200_OK)
