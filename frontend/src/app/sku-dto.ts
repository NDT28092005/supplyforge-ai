import { IndustryContext } from './industry-context';
import { UnitVelocities } from './unit-velocities';

export interface SkuDTO {
    id: string;
    name: string;
    sku: string;
    quantity: number;
    costPrice: number;
    sellingPrice: number;
    totalValue: number;
    accumulatedSunkCost: number;
    lastRecordDate: string;
    daysInInventory: number;
    bucket: 'HEALTHY' | 'WATCHLIST' | 'SLOW_MOVING' | 'DEAD_STOCK';
    industryContext: IndustryContext;
    velocities: UnitVelocities;
    expirationDate?: string;
    daysLeft?: number;
}
