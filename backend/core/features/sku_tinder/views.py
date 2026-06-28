from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from .services import SkuNormalizationService

@api_view(['GET'])
def get_candidates(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    clusters = SkuNormalizationService.find_duplicate_candidates(user_id)
    
    pairs = []
    for cluster in clusters:
        if len(cluster) >= 2:
            pA = cluster[0]
            for i in range(1, len(cluster)):
                pB = cluster[i]
                pairs.append({
                    "skuAId": pA.id,
                    "skuAName": pA.product_name,
                    "skuACode": pA.item_sku or pA.id,
                    "skuAPrice": float(pA.price or 0.0),
                    "skuAStock": pA.stock or 0,
                    "skuASource": pA.platform or "Hệ thống",
                    "skuBId": pB.id,
                    "skuBName": pB.product_name,
                    "skuBCode": pB.item_sku or pB.id,
                    "skuBPrice": float(pB.price or 0.0),
                    "skuBStock": pB.stock or 0,
                    "skuBSource": pB.platform or "Hệ thống",
                    "distance": 2
                })
    return Response(pairs)


@csrf_exempt
@api_view(['POST'])
def merge_products(request, workspace_id):
    parent_id = request.data.get("parentSkuId")
    child_id = request.data.get("childSkuId")
    
    if not parent_id or not child_id:
        return Response("Merge failed: Missing parent or child ID", status=status.HTTP_400_BAD_REQUEST)
        
    try:
        SkuNormalizationService.merge_products(parent_id, child_id)
        return Response("Merged successfully")
    except Exception as e:
        return Response(f"Merge failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST'])
def undo_merge(request, workspace_id):
    parent_id = request.data.get("parentSkuId")
    child_id = request.data.get("childSkuId")
    
    if not parent_id or not child_id:
        return Response("Undo failed: Missing parent or child ID", status=status.HTTP_400_BAD_REQUEST)
        
    try:
        SkuNormalizationService.undo_merge(parent_id, child_id)
        return Response("Undo merged successfully")
    except Exception as e:
        return Response(f"Undo failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST'])
def ignore_pair(request, workspace_id):
    sku_a_id = request.data.get("skuAId")
    sku_b_id = request.data.get("skuBId")
    user_id = request.data.get("userId", "user_default_001")
    
    if not sku_a_id or not sku_b_id:
        return Response("Ignore failed: Missing SKU IDs", status=status.HTTP_400_BAD_REQUEST)
        
    try:
        SkuNormalizationService.ignore_pair(sku_a_id, sku_b_id, user_id)
        return Response("Ignored successfully")
    except Exception as e:
        return Response(f"Ignore failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
