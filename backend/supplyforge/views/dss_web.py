"""
SupplyForge AI — Merchant DSS Web REST API Views
"""
import io
import pandas as pd
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.services.dss_service import MerchantDSSWebService

_CACHE_PAYLOADS = {}
_CACHE_SUMMARY  = {}

@api_view(['POST'])
def dss_upload(request):
    """
    POST /api/v1/dss/upload
    Accepts CSV / Parquet file upload or uses default benchmark data.
    Returns summary and list of SKU IDs.
    """
    try:
        if 'file' in request.FILES:
            uploaded_file = request.FILES['file']
            filename = uploaded_file.name
            if filename.endswith('.parquet'):
                df_gt = pd.read_parquet(uploaded_file)
            else:
                df_gt = pd.read_csv(uploaded_file)
        else:
            # Benchmark default dataset
            from pathlib import Path
            p_gt = Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed" / "ground_truth_labels.parquet"
            df_gt = pd.read_parquet(p_gt)

        cutoff_date = request.data.get("cutoff_date", "2025-10-16")
        payloads, summary = MerchantDSSWebService.process_merchant_upload(df_gt, cutoff_date=cutoff_date)

        global _CACHE_PAYLOADS, _CACHE_SUMMARY
        _CACHE_PAYLOADS["default"] = payloads
        _CACHE_SUMMARY["default"]  = summary

        return Response({
            "status": "success",
            "message": f"Successfully processed {summary['total_skus']} SKUs.",
            "summary": summary,
            "sample_sku_ids": [p["itemId"] for p in payloads[:10]]
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def dss_summary(request):
    """
    GET /api/v1/dss/summary
    Returns current catalog risk overview summary.
    """
    global _CACHE_SUMMARY
    if "default" not in _CACHE_SUMMARY:
        # Auto trigger default upload
        from pathlib import Path
        p_gt = Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed" / "ground_truth_labels.parquet"
        df_gt = pd.read_parquet(p_gt)
        payloads, summary = MerchantDSSWebService.process_merchant_upload(df_gt)
        global _CACHE_PAYLOADS
        _CACHE_PAYLOADS["default"] = payloads
        _CACHE_SUMMARY["default"]  = summary

    return Response(_CACHE_SUMMARY["default"], status=status.HTTP_200_OK)


@api_view(['GET'])
def dss_sku_detail(request, sku_id):
    """
    GET /api/v1/dss/sku/<sku_id>
    Returns SKU decision card payload including SHAP evidence, cause tags, actions, and Vietnamese report.
    """
    global _CACHE_PAYLOADS
    if "default" not in _CACHE_PAYLOADS:
        dss_summary(request)

    payloads = _CACHE_PAYLOADS.get("default", [])
    card = MerchantDSSWebService.get_sku_decision_card(payloads, sku_id)
    if card is None:
        return Response({"error": f"SKU {sku_id} not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response(card, status=status.HTTP_200_OK)
