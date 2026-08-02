export interface MatchProposal {
    confidenceScore: number;
    skuA: {
        id: string;
        skuCode: string;
        name: string;
        price: number;
        stock: number;
        source: string;
    };
    skuB: {
        id: string;
        skuCode: string;
        name: string;
        price: number;
        stock: number;
        source: string;
    };
}
