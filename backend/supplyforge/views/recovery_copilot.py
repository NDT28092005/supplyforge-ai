from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.services.portfolio import PortfolioOrchestrationService


@api_view(['GET'])
def get_portfolio_command(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    command_plan = PortfolioOrchestrationService.get_portfolio_command(user_id, workspace_id)
    return Response(command_plan)


@api_view(['GET'])
def get_financial_analysis(request, workspace_id):
    user_id = request.GET.get('userId', 'user_default_001')
    sku_id = request.GET.get('skuId')
    discount_pct = float(request.GET.get('discount', '0.30'))
    accounting_method = request.GET.get('accounting', 'FIFO')

    if not sku_id:
        return Response({"error": "skuId query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    result = PortfolioOrchestrationService.get_financial_analysis(
        user_id=user_id,
        sku_id=sku_id,
        discount_pct=discount_pct,
        accounting_method=accounting_method,
        workspace_id=workspace_id
    )

    if not result:
        return Response({"error": "SKU not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(result)
