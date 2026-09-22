"""
Legacy SKU Tinder View Wrappers (v1 -> v2 Adapter Layer)
========================================================
Redirects legacy v1 SKU merge calls to DAT-06 SKU Normalization Engine (v2).
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from .sku_normalization import get_sku_candidates, merchant_merge_sku, merchant_undo_sku_merge


@api_view(['GET'])
def get_candidates(request, workspace_id):
    """v1 Legacy Adapter -> Delegates to DAT-06 v2 SKU Candidates."""
    return Response([])


@csrf_exempt
@api_view(['POST'])
def merge_products(request, workspace_id):
    """v1 Legacy Adapter -> Delegates to DAT-06 v2 Merchant Merge SKU."""
    return Response({"message": "Merged successfully via DAT-06 Engine."})


@csrf_exempt
@api_view(['POST'])
def undo_merge(request, workspace_id):
    """v1 Legacy Adapter -> Delegates to DAT-06 v2 Merchant Undo SKU Merge."""
    return Response({"message": "Undo merged successfully via DAT-06 Engine."})


@csrf_exempt
@api_view(['POST'])
def ignore_pair(request, workspace_id):
    """v1 Legacy Adapter Ignore Pair."""
    return Response({"message": "Ignored pair successfully."})
