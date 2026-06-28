from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt

from .services import PortfolioOrchestrationService, FinancialLiquidationEngine
from core.features.leak_detector.services import InventoryFinancialEngineService

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
    sku_id = request.GET.get('skuId') or request.GET.get('sku')
    sku_name = request.GET.get('skuName')
    
    aging_data = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
    
    all_skus = []
    for bucket in ["deadStockSkus", "slowMovingSkus", "watchlistSkus", "healthySkus"]:
        all_skus.extend(aging_data.get(bucket, []))
        
    if not all_skus:
        return Response(status=status.HTTP_204_NO_CONTENT)
        
    top_sku = None
    if sku_id:
        top_sku = next((s for s in all_skus if str(s.get('id')) == str(sku_id) or str(s.get('sku')) == str(sku_id)), None)
    if not top_sku and sku_name:
        top_sku = next((s for s in all_skus if s.get('name') == sku_name), None)
        
    if not top_sku:
        target_list = aging_data["deadStockSkus"] if aging_data["deadStockSkus"] else aging_data["slowMovingSkus"]
        if not target_list:
            target_list = all_skus
        top_sku = max(target_list, key=lambda s: s["totalValue"])
        
    roi = FinancialLiquidationEngine.calculate_liquidation_roi(top_sku, discount_pct, accounting_method, user_id=user_id, workspace_id=workspace_id)
    return Response(roi)

