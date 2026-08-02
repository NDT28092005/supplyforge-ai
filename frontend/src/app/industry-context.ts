export interface IndustryContext {
    industryCode: string;
    displayName: string;
    agingRiskMultiplier: number;
    maxShelfLifeDays: number;
    liquidationStrategies: string[];
    riskFactors: string[];
    agingScore: number;
    isCritical: boolean;
}
