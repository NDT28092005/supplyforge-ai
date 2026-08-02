import json
import uuid
from decimal import Decimal
from datetime import datetime
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.models import Product, Order, OrderItem


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
