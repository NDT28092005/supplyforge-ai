import { SkuDTO } from './sku-dto';

export interface InventoryAgingAnalysis {
    totalHealthyValue: number;
    totalWatchlistValue: number;
    totalSlowMovingValue: number;
    totalDeadStockValue: number;
    totalFrozenValue: number;
    totalBleedingRateMonthly: number;
    turnoverRate: number;
    dso: string;
    accumulatedSunkCost: number;
    storageCostMonthly: number;
    depreciationCostMonthly: number;
    opportunityCostMonthly: number;
    expiredDeactivatedCount: number;
    nearExpiryWarnings: any[];
    healthySkus: SkuDTO[];
    watchlistSkus: SkuDTO[];
    slowMovingSkus: SkuDTO[];
    deadStockSkus: SkuDTO[];
}
