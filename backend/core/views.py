import json
import uuid
from decimal import Decimal
from datetime import datetime
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Product, Order, OrderItem, Sku, Workspace
from .services import (
    InventoryInsightService,
    InventoryFinancialEngineService,
    PortfolioOrchestrationService,
    FinancialLiquidationEngine,
    SkuNormalizationService,
    DynamicFileImportService,
    GeminiColumnMappingService
)

# ─── 1. Health API ───
@api_view(['GET'])
def ping(request):
    return Response({"service": "supplyforge-ai", "status": "ok"})


# ─── 2. Product API ───
@api_view(['GET'])
def check_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    count = Product.objects.filter(user_id=user_id).count()
    return Response({"hasData": count > 0, "count": count})


@csrf_exempt
@api_view(['POST'])
def sync_products(request):
    file = request.FILES.get('file')
    user_id = request.data.get('userId', 'user_default_001')
    
    if not file:
        return Response("File is missing", status=status.HTTP_400_BAD_REQUEST)
        
    try:
        content = file.read().decode('utf-8')
        root_node = json.loads(content)
        
        if isinstance(root_node, list):
            raw_products = root_node
        elif isinstance(root_node, dict) and "products" in root_node and isinstance(root_node["products"], list):
            raw_products = root_node["products"]
        else:
            raw_products = [root_node]
            
        products_to_create = []
        for raw in raw_products:
            p_id = raw.get('_id') or uuid.uuid4().hex[:24]
            
            def get_val(k1, k2, def_val):
                return raw.get(k1, raw.get(k2, def_val))
                
            def get_decimal(keys):
                for k in keys:
                    v = raw.get(k)
                    if v is not None:
                        return Decimal(str(v))
                return Decimal('0.00')
                
            def get_int(keys):
                for k in keys:
                    v = raw.get(k)
                    if v is not None:
                        return int(v)
                return 0

            p = Product(
                id=p_id,
                user_id=user_id,
                third_party_id=get_val('thirdPartyId', 'third_party_id', ''),
                item_id=get_val('itemId', 'item_id', None),
                product_name=get_val('productName', 'product_name', 'Unknown Product'),
                platform=get_val('platform', 'platform', 'shopee'),
                item_sku=get_val('itemSku', 'item_sku', ''),
                price=get_decimal(['price']),
                cost=get_decimal(['cost']),
                stock=get_int(['stock']),
                total_revenue=get_decimal(['totalRevenue', 'total_revenue']),
                total_profit=get_decimal(['totalProfit', 'total_profit']),
                total_orders=get_int(['totalOrders', 'total_orders']),
                data=raw,
                active_on_web=True,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            products_to_create.append(p)
            
        Product.objects.bulk_create(products_to_create)
        return Response("Products synced successfully.")
    except Exception as e:
        return Response(f"Sync failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── 3. Order API ───
@csrf_exempt
@api_view(['POST'])
def sync_orders(request):
    file = request.FILES.get('file')
    user_id = request.data.get('userId', 'user_default_001')
    
    if not file:
        return Response("File is empty", status=status.HTTP_400_BAD_REQUEST)
        
    try:
        content = file.read().decode('utf-8')
        root_node = json.loads(content)
        
        if isinstance(root_node, list):
            raw_orders = root_node
        elif isinstance(root_node, dict):
            if "orders" in root_node and isinstance(root_node["orders"], list):
                raw_orders = root_node["orders"]
            elif "order" in root_node and isinstance(root_node["order"], dict):
                raw_orders = [root_node["order"]]
            else:
                raw_orders = [root_node]
        else:
            return Response("Unsupported JSON root type", status=status.HTTP_400_BAD_REQUEST)
            
        for raw in raw_orders:
            o_id = uuid.uuid4().hex[:24]
            created_at = None
            if raw.get('createdAt'):
                try:
                    # Parse standard ISO string like "2026-06-21T15:00:59Z"
                    dt_str = raw['createdAt'].replace('Z', '')
                    created_at = datetime.fromisoformat(dt_str)
                except Exception:
                    pass

            o = Order.objects.create(
                id=o_id,
                user_id=user_id,
                order_id=str(raw.get('orderId', '')),
                platform=raw.get('platform'),
                amount=Decimal(str(raw.get('amount', 0.00))) if raw.get('amount') else None,
                buyer_user_name=raw.get('buyerUserName'),
                cancelled_after_packaged=bool(raw.get('cancelledAfterPackaged', False)),
                data=raw,
                created_at=created_at,
                updated_at=datetime.now()
            )
            
            if "items" in raw and isinstance(raw["items"], list):
                for item_raw in raw["items"]:
                    OrderItem.objects.create(
                        order=o,
                        item_id=item_raw.get('itemId'),
                        model_id=item_raw.get('modelId'),
                        sku=item_raw.get('sku'),
                        product_name=item_raw.get('productName'),
                        quantity=int(item_raw['quantity']) if item_raw.get('quantity') is not None else None,
                        price=Decimal(str(item_raw.get('price', 0))) if item_raw.get('price') is not None else None,
                        cost=Decimal(str(item_raw.get('cost', 0))) if item_raw.get('cost') is not None else Decimal('0.00')
                    )
                    
        return Response("Sync initiated successfully in batch mode.")
    except Exception as e:
        return Response(f"Sync failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── 4. Import API (Trust Theater) ───
@csrf_exempt
@api_view(['POST'])
def analyze_file(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "File upload không hợp lệ hoặc rỗng."}, status=status.HTTP_400_BAD_REQUEST)
        
    if not file.name.lower().endswith('.csv'):
        return Response({"error": "Hệ thống hiện tại chỉ hỗ trợ trích xuất luồng Streaming cho file CSV."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        # Peek at data (headers and 5 rows)
        headers, sample_rows = DynamicFileImportService.peek_sample_data(file)
        
        # Call Gemini AI Mapping
        ai_suggestions = GeminiColumnMappingService.infer_column_mapping(headers, sample_rows)
        
        response = {
            "headers": headers,
            "sampleData": sample_rows[0] if sample_rows else None,
            "aiSuggestions": ai_suggestions
        }
        return Response(response)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['POST'])
def process_file(request):
    file = request.FILES.get('file')
    mapping_rule_json = request.data.get('mappingRule')
    user_id = request.data.get('userId', 'user_default_001')
    
    if not file or not mapping_rule_json:
        return Response({"error": "File hoặc mapping rule bị thiếu."}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        mapping_rule = json.loads(mapping_rule_json)
        DynamicFileImportService.process_batch_import(file, mapping_rule, user_id)
        return Response({"message": "Batch import processed successfully."})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(['DELETE'])
def clear_data(request):
    user_id = request.GET.get('userId', 'user_default_001')
    try:
        DynamicFileImportService.clear_data(user_id)
        return Response({"message": "Đã xóa dữ liệu cũ thành công."})
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── 5. Dashboard API ───
@csrf_exempt
@api_view(['POST'])
def refresh_dead_stock(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    insights = InventoryInsightService.get_dashboard_insights(user_id, refresh=True)
    return Response(insights)


@api_view(['GET'])
def get_dead_stock(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    insights = InventoryInsightService.get_dashboard_insights(user_id, refresh=False)
    return Response(insights)


@api_view(['GET'])
def get_aging(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    aging_data = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
    return Response(aging_data)


@api_view(['GET'])
def get_portfolio_command(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    command_plan = PortfolioOrchestrationService.build_command_plan(user_id)
    return Response(command_plan)


@api_view(['GET'])
def get_financial_analysis(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    discount_pct = float(request.GET.get('discount', '0.35'))
    accounting_method = request.GET.get('accounting', 'FIFO')
    
    aging_data = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
    
    target_list = aging_data["deadStockSkus"] if aging_data["deadStockSkus"] else aging_data["slowMovingSkus"]
    if not target_list:
        return Response(status=status.HTTP_204_NO_CONTENT)
        
    # Choose top sku to calculate ROI
    top_sku = max(target_list, key=lambda s: s["totalValue"])
    roi = FinancialLiquidationEngine.calculate_liquidation_roi(top_sku, discount_pct, accounting_method)
    return Response(roi)


# ─── 6. SKU Merge API ───
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
        SkuNormalizationService.merge_products(parent_id, [child_id])
        return Response("Merged successfully")
    except Exception as e:
        return Response(f"Merge failed: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
