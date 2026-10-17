from rest_framework.decorators import api_view
from rest_framework.response import Response

from supplyforge.services.insight import InventoryInsightService
from supplyforge.services.financial import InventoryFinancialEngineService


@api_view(['POST'])
def refresh_dead_stock(request, workspace_id):
    user_id = request.user_id
    workspace_id = request.workspace_id
    insights = InventoryInsightService.get_dead_stock_analysis(user_id)
    return Response(insights)


@api_view(['GET'])
def get_dead_stock(request, workspace_id):
    user_id = request.user_id
    workspace_id = request.workspace_id
    insights = InventoryInsightService.get_dead_stock_analysis(user_id)
    return Response(insights)


@api_view(['GET'])
def get_aging(request, workspace_id):
    user_id = request.user_id
    workspace_id = request.workspace_id
    aging_data = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
    return Response(aging_data)
