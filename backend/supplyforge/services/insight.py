from django.conf import settings
from supplyforge.models import Product


class InventoryInsightService:
    @staticmethod
    def get_dead_stock_analysis(user_id):
        from supplyforge.services.financial import InventoryFinancialEngineService
        return InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
