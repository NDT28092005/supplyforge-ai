from supplyforge.services.financial import InventoryFinancialEngineService, FinancialLiquidationEngine


class PortfolioOrchestrationService:
    @staticmethod
    def get_portfolio_command(user_id, workspace_id=1):
        """
        Orchestrates the full portfolio command center data:
        1. Get aging & hidden cost analysis (including F&B expiration)
        2. For each dead stock SKU, calculate liquidation ROI
        """
        analysis = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
        
        dead_stock_with_roi = []
        for sku_dto in analysis.get('deadStockSkus', []):
            roi_data = FinancialLiquidationEngine.calculate_liquidation_roi(
                sku_dto=sku_dto,
                discount_pct=0.30,
                accounting_method='FIFO',
                user_id=user_id,
                workspace_id=workspace_id
            )
            dead_stock_with_roi.append({**sku_dto, "roiAnalysis": roi_data})

        analysis['deadStockSkus'] = dead_stock_with_roi
        return analysis

    @staticmethod
    def get_financial_analysis(user_id, sku_id, discount_pct, accounting_method, workspace_id=1):
        """
        Detailed financial liquidation analysis for a single SKU.
        """
        analysis = InventoryFinancialEngineService.calculate_aging_and_hidden_costs(user_id)
        
        target_sku = None
        for bucket_key in ['deadStockSkus', 'slowMovingSkus', 'watchlistSkus', 'healthySkus']:
            for sku in analysis.get(bucket_key, []):
                if str(sku['id']) == str(sku_id):
                    target_sku = sku
                    break
            if target_sku:
                break
        
        if not target_sku:
            return None
        
        return FinancialLiquidationEngine.calculate_liquidation_roi(
            sku_dto=target_sku,
            discount_pct=discount_pct,
            accounting_method=accounting_method,
            user_id=user_id,
            workspace_id=workspace_id
        )
