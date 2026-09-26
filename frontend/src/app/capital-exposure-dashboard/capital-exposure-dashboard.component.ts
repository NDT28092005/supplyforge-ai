import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';

export interface CapitalSkuItem {
  sku: string;
  name: string;
  riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string;
  dslsDays: number;
  capitalExposure: string; // e.g. "93.8M"
  capitalPriority: string; // e.g. "92.3M"
  opportunityCost: string; // e.g. "4.7M"
  agingBucket: string; // e.g. "Trên 90 ngày"
  sales30d: number;
  sales90d: number;
  zeroRatePct: string;
  demandProb: number;
  demandPattern: string;
  shapFactors: {
    label: string;
    subDesc: string;
    impactText: string;
    score: number;
    pct: number;
    severity: 'red' | 'amber' | 'emerald';
  }[];
  conclusion: string;
}

@Component({
  selector: 'app-capital-exposure-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './capital-exposure-dashboard.component.html',
  styleUrls: ['./capital-exposure-dashboard.component.css']
})
export class CapitalExposureDashboardComponent implements OnInit, OnDestroy {
  @Input() merchantId: string = 'default_merchant';
  @Input() datasetVersion: string = 'v1.0';

  @Output() navigateTo = new EventEmitter<string>();

  // Filter & Search State
  selectedRiskFilter: string = ''; // '' = Tất cả (100), 'HIGH_RISK' = 25, 'MEDIUM_RISK' = 6, 'LOW_RISK' = 69
  searchTerm: string = '';
  selectedPeriod: string = '30 ngày qua';

  // Modal State
  drawerOpen: boolean = false;
  selectedSkuItem: CapitalSkuItem | null = null;
  showShapCalcModal: boolean = false;

  // KPI Summary
  summaryGrid = {
    totalExposure: '0',
    highRiskExposure: '0',
    opportunityCost: '0',
    affectedSkus: '0 SKU'
  };

  // Distributions Data
  riskDistribution: any[] = [];
  agingDistribution: any[] = [];

  // Mock 100 SKUs List
  skuItems: CapitalSkuItem[] = [];

  constructor(private apiService: ApiService) {}

  formatCurrencyShort(val: number): string {
    if (!val || val === 0) return '0';
    if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)}B`;
    if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `${(val / 1000).toFixed(1)}K`;
    return `${Math.round(val)}`;
  }

  ngOnInit(): void {
    this.loadRealCapitalExposureData();
  }

  loadRealCapitalExposureData(): void {
    this.apiService.createCapitalExposureAnalysis({
      merchant_id: this.merchantId,
      dataset_version: this.datasetVersion
    }).subscribe({
      next: (res: any) => {
        if (res && res.analysis_id) {
          const aid = res.analysis_id;
          this.apiService.listCapitalExposureItems(aid, { limit: 100 }).subscribe({
            next: (itemsRes: any) => {
              const realItems = itemsRes.items || [];
              if (realItems.length > 0) {
                this.processRealData(res, realItems);
              } else if (res.top_financial_skus && res.top_financial_skus.length > 0) {
                this.processRealData(res, res.top_financial_skus);
              } else {
                this.setEmptyDataState();
              }
            },
            error: () => {
              if (res.top_financial_skus && res.top_financial_skus.length > 0) {
                this.processRealData(res, res.top_financial_skus);
              } else {
                this.setEmptyDataState();
              }
            }
          });
        } else {
          this.setEmptyDataState();
        }
      },
      error: () => {
        this.setEmptyDataState();
      }
    });
  }

  setEmptyDataState(): void {
    this.skuItems = [];
    this.summaryGrid = {
      totalExposure: '0',
      highRiskExposure: '0',
      opportunityCost: '0',
      affectedSkus: '0 SKU'
    };
    this.riskDistribution = [];
    this.agingDistribution = [];
  }

  processRealData(analysisRes: any, itemsList: any[]): void {
    // 1. Map SKU Items first
    this.skuItems = itemsList.map((i: any) => {
      const rawClass = i.slow_moving_risk_class || i.risk_class || 'LOW_RISK';
      const riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK' = (rawClass === 'CRITICAL' || rawClass === 'HIGH_RISK') ? 'HIGH_RISK' : (rawClass === 'MEDIUM_RISK' ? 'MEDIUM_RISK' : 'LOW_RISK');
      const dsls = i.aging_days !== undefined ? i.aging_days : (i.dsls || 0);
      const probVal = i.risk_probability !== undefined ? i.risk_probability : (riskClass === 'HIGH_RISK' ? 0.95 : (riskClass === 'MEDIUM_RISK' ? 0.65 : 0.15));
      const invVal = i.inventory_value || i.capital_exposure || i.capital_locked || 0;
      const oppCostVal = i.estimated_opportunity_cost || (invVal * 0.12 / 365 * Math.max(1, dsls));

      let agingBucketStr = 'Dưới 30 ngày';
      if (dsls > 90) agingBucketStr = 'Trên 90 ngày';
      else if (dsls > 60) agingBucketStr = '61–90 ngày';
      else if (dsls > 30) agingBucketStr = '31–60 ngày';

      const prioMultiplier = riskClass === 'HIGH_RISK' ? 0.9 : (riskClass === 'MEDIUM_RISK' ? 0.5 : 0.0);

      return {
        sku: i.sku || i.canonical_sku_id || 'SKU_UNKNOWN',
        name: i.product_name || i.name || i.sku || 'Sản phẩm',
        riskClass: riskClass,
        probabilityPct: `${(probVal * 100).toFixed(1)}%`,
        dslsDays: dsls,
        capitalExposureVal: invVal,
        capitalExposure: this.formatCurrencyShort(invVal),
        capitalPriority: this.formatCurrencyShort(invVal * prioMultiplier),
        opportunityCostVal: oppCostVal,
        opportunityCost: this.formatCurrencyShort(oppCostVal),
        agingBucket: agingBucketStr,
        sales30d: i.sold_30d || 0,
        sales90d: i.sold_90d || 0,
        zeroRatePct: `${((i.zero_rate_90d || (dsls > 90 ? 0.92 : (dsls > 30 ? 0.55 : 0.12))) * 100).toFixed(1)}%`,
        demandProb: 0.1,
        demandPattern: dsls > 90 ? 'Bán lắt nhắt' : 'Bán không đều',
        shapFactors: [
          { label: 'Số ngày chưa có đơn hàng mới', subDesc: `Đã ${dsls} ngày đọng vốn trong kho`, impactText: dsls > 60 ? 'Tác động mạnh' : 'Mức vừa', score: dsls > 60 ? 4 : 2, pct: Math.min(100, Math.round(dsls / 2)), severity: (dsls > 90 ? 'red' : (dsls > 30 ? 'amber' : 'emerald')) as 'red' | 'amber' | 'emerald' }
        ],
        conclusion: `SKU đang đọng vốn ${this.formatCurrencyShort(invVal)} trong kho, thời gian lưu kho ${dsls} ngày.`
      };
    });

    // 2. Compute Summary KPIs directly from skuItems
    const totalVal = this.skuItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const totalOppCost = this.skuItems.reduce((acc, i) => acc + (i as any).opportunityCostVal, 0);
    const highRiskItems = this.skuItems.filter(i => i.riskClass === 'HIGH_RISK');
    const highRiskVal = highRiskItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);

    this.summaryGrid = {
      totalExposure: this.formatCurrencyShort(totalVal),
      highRiskExposure: this.formatCurrencyShort(highRiskVal),
      opportunityCost: this.formatCurrencyShort(totalOppCost),
      affectedSkus: `${highRiskItems.length} SKU`
    };

    // 3. Compute Risk Distribution directly from skuItems
    const highItems = this.skuItems.filter(i => i.riskClass === 'HIGH_RISK');
    const medItems = this.skuItems.filter(i => i.riskClass === 'MEDIUM_RISK');
    const lowItems = this.skuItems.filter(i => i.riskClass === 'LOW_RISK');

    const highExp = highItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const medExp = medItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const lowExp = lowItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);

    const calcSharePct = (val: number) => totalVal > 0 ? Math.round((val / totalVal) * 100) : 0;

    this.riskDistribution = [
      { label: 'Rủi ro cao', exposure: this.formatCurrencyShort(highExp), sharePct: calcSharePct(highExp), count: highItems.length, color: 'bg-rose-500', badgeClass: 'bg-rose-50 text-rose-700 border-rose-200' },
      { label: 'Cần theo dõi', exposure: this.formatCurrencyShort(medExp), sharePct: calcSharePct(medExp), count: medItems.length, color: 'bg-amber-500', badgeClass: 'bg-amber-50 text-amber-700 border-amber-200' },
      { label: 'An toàn', exposure: this.formatCurrencyShort(lowExp), sharePct: calcSharePct(lowExp), count: lowItems.length, color: 'bg-emerald-500', badgeClass: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
    ];

    // 4. Compute Aging Distribution directly from skuItems
    const freshItems = this.skuItems.filter(i => i.dslsDays <= 30);
    const agingItems = this.skuItems.filter(i => i.dslsDays > 30 && i.dslsDays <= 60);
    const atRiskItems = this.skuItems.filter(i => i.dslsDays > 60 && i.dslsDays <= 90);
    const critAgingItems = this.skuItems.filter(i => i.dslsDays > 90);

    const freshExp = freshItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const agingExp = agingItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const atRiskExp = atRiskItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const critAgingExp = critAgingItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);

    this.agingDistribution = [
      { label: 'Dưới 30 ngày (Lưu thông đều)', exposure: this.formatCurrencyShort(freshExp), sharePct: calcSharePct(freshExp), count: freshItems.length, color: 'bg-emerald-500', desc: 'Hàng mới lưu thông tốt' },
      { label: '31–60 ngày (Theo dõi)', exposure: this.formatCurrencyShort(agingExp), sharePct: calcSharePct(agingExp), count: agingItems.length, color: 'bg-amber-500', desc: 'Có dấu hiệu bán chậm' },
      { label: '61–90 ngày (Tồn đọng nhẹ)', exposure: this.formatCurrencyShort(atRiskExp), sharePct: calcSharePct(atRiskExp), count: atRiskItems.length, color: 'bg-amber-600', desc: 'Cần khuyến mãi đẩy đơn' },
      { label: 'Trên 90 ngày (Chôn vốn lâu)', exposure: this.formatCurrencyShort(critAgingExp), sharePct: calcSharePct(critAgingExp), count: critAgingItems.length, color: 'bg-rose-500', desc: 'Ưu tiên giải phóng vốn gấp' }
    ];
  }

  generateMockData(): void {
    const list: CapitalSkuItem[] = [];

    // 1. Exact Wireframe SKU: CRIT-024
    list.push({
      sku: 'CRIT-024',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 24',
      riskClass: 'HIGH_RISK',
      probabilityPct: '98.4%',
      dslsDays: 199,
      capitalExposure: '93.8M',
      capitalPriority: '92.3M',
      opportunityCost: '4.7M',
      agingBucket: 'Trên 90 ngày',
      sales30d: 2,
      sales90d: 5,
      zeroRatePct: '94.9%',
      demandProb: 0.04,
      demandPattern: 'Bán lắt nhắt',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '94.9% thời gian không phát sinh đơn hàng nào', impactText: 'Tác động rất mạnh', score: 5, pct: 95, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 199 ngày kể từ đơn hàng phát sinh gần nhất', impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' },
        { label: 'Tốc độ tiêu thụ trung bình (Sales Velocity)', subDesc: 'Sức bán cực yếu, trung bình 0.08 sản phẩm/ngày', impactText: 'Tác động mạnh', score: 4, pct: 75, severity: 'amber' }
      ],
      conclusion: 'SKU chôn lượng vốn lớn nhất trong kho, cần áp dụng chiến dịch giải phóng vốn ngay.'
    });

    // 2. Exact Wireframe SKU: CRIT-019
    list.push({
      sku: 'CRIT-019',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 19',
      riskClass: 'HIGH_RISK',
      probabilityPct: '97.9%',
      dslsDays: 204,
      capitalExposure: '88.7M',
      capitalPriority: '86.8M',
      opportunityCost: '4.4M',
      agingBucket: 'Trên 90 ngày',
      sales30d: 3,
      sales90d: 7,
      zeroRatePct: '92.1%',
      demandProb: 0.05,
      demandPattern: 'Bán lắt nhắt',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '92.1% thời gian không phát sinh đơn hàng nào', impactText: 'Tác động rất mạnh', score: 5, pct: 92, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 204 ngày chưa bán thêm được sản phẩm nào', impactText: 'Tác động mạnh', score: 4, pct: 85, severity: 'red' }
      ],
      conclusion: 'SKU chôn vốn kéo dài trên 200 ngày, chi phí gánh vốn phát sinh liên tục.'
    });

    // 3. Exact Wireframe SKU: CRIT-017
    list.push({
      sku: 'CRIT-017',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 17',
      riskClass: 'HIGH_RISK',
      probabilityPct: '97.2%',
      dslsDays: 199,
      capitalExposure: '84.8M',
      capitalPriority: '82.4M',
      opportunityCost: '4.2M',
      agingBucket: 'Trên 90 ngày',
      sales30d: 2,
      sales90d: 6,
      zeroRatePct: '93.5%',
      demandProb: 0.04,
      demandPattern: 'Bán lắt nhắt',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '93.5% thời gian không có lượt mua mới', impactText: 'Tác động rất mạnh', score: 5, pct: 93, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 199 ngày chôn vốn trong kho', impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' }
      ],
      conclusion: 'Sản phẩm có lượng vốn ứ đọng cao, ưu tiên cắt giảm tồn kho.'
    });

    // Generate remaining 22 HIGH_RISK items (Total 25 HIGH_RISK)
    for (let i = 1; i <= 22; i++) {
      const pad = i.toString().padStart(3, '0');
      const cap = (75 - i * 2.2).toFixed(1);
      const prio = (parseFloat(cap) * 0.95).toFixed(1);
      list.push({
        sku: `CRIT-${pad}`,
        name: `Sản phẩm Nguy Cơ Bán Chậm Rất Cao ${i}`,
        riskClass: 'HIGH_RISK',
        probabilityPct: `${(96.5 - i * 0.4).toFixed(1)}%`,
        dslsDays: 95 + i * 4,
        capitalExposure: `${cap}M`,
        capitalPriority: `${prio}M`,
        opportunityCost: `${(parseFloat(cap) * 0.05).toFixed(1)}M`,
        agingBucket: i % 2 === 0 ? 'Trên 90 ngày' : '61–90 ngày',
        sales30d: 1 + (i % 3),
        sales90d: 4 + (i % 5),
        zeroRatePct: `${(90 + (i % 6)).toFixed(1)}%`,
        demandProb: 0.05,
        demandPattern: i % 2 === 0 ? 'Bán lắt nhắt' : 'Bán không đều',
        shapFactors: [
          { label: 'Tỷ lệ ngày không bán', subDesc: 'Hơn 90% thời gian không bán được đơn nào', impactText: 'Tác động rất mạnh', score: 5, pct: 90, severity: 'red' },
          { label: 'Số ngày chôn hàng (DSLS)', subDesc: `Đã ${95 + i * 4} ngày chưa có giao dịch mới`, impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' }
        ],
        conclusion: 'Sản phẩm có lượng hàng chôn dài ngày, cần xem xét xử lý vốn.'
      });
    }

    // Generate 6 MEDIUM_RISK items
    for (let i = 1; i <= 6; i++) {
      const pad = i.toString().padStart(3, '0');
      const cap = (22 - i * 1.5).toFixed(1);
      list.push({
        sku: `WATCH-${pad}`,
        name: `Sản phẩm Cần Theo Dõi ${i}`,
        riskClass: 'MEDIUM_RISK',
        probabilityPct: `${(68.5 - i * 1.5).toFixed(1)}%`,
        dslsDays: 35 + i * 4,
        capitalExposure: `${cap}M`,
        capitalPriority: `${(parseFloat(cap) * 0.6).toFixed(1)}M`,
        opportunityCost: `${(parseFloat(cap) * 0.03).toFixed(1)}M`,
        agingBucket: '31–60 ngày',
        sales30d: 8 + i,
        sales90d: 22 + i * 2,
        zeroRatePct: `${(60 + i * 2).toFixed(1)}%`,
        demandProb: 0.22,
        demandPattern: 'Bán không đều',
        shapFactors: [
          { label: 'Tốc độ bán giảm nhẹ', subDesc: 'Sức mua chậm hơn so với trung bình cùng kỳ', impactText: 'Tác động trung bình', score: 3, pct: 50, severity: 'amber' }
        ],
        conclusion: 'Tồn đọng vốn mức vừa phải, theo dõi sát lượng xuất kho.'
      });
    }

    // Generate 69 LOW_RISK items
    for (let i = 1; i <= 69; i++) {
      const pad = i.toString().padStart(3, '0');
      const cap = (10 - (i % 8) * 0.9).toFixed(1);
      list.push({
        sku: `SAFE-${pad}`,
        name: `Sản phẩm An Toàn ${i}`,
        riskClass: 'LOW_RISK',
        probabilityPct: `${(18.5 - (i % 15) * 0.8).toFixed(1)}%`,
        dslsDays: 2 + (i % 12),
        capitalExposure: `${cap}M`,
        capitalPriority: `0.0M`,
        opportunityCost: `0.1M`,
        agingBucket: 'Dưới 30 ngày',
        sales30d: 28 + (i % 15),
        sales90d: 85 + (i % 40),
        zeroRatePct: `${(15 + (i % 10)).toFixed(1)}%`,
        demandProb: 0.88,
        demandPattern: 'Bán đều đặn',
        shapFactors: [
          { label: 'Tốc độ bán ổn định', subDesc: 'Sức mua đều đặn hàng ngày', impactText: 'Mức an toàn', score: 1, pct: 15, severity: 'emerald' }
        ],
        conclusion: 'Hàng lưu thông nhanh, dòng vốn quay vòng tối ưu.'
      });
    }

    this.skuItems = list;
  }

  // Getters for Filter Chip Counts
  get totalCount(): number {
    return this.skuItems.length; // 100
  }

  get highRiskCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'HIGH_RISK').length; // 25
  }

  get watchCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'MEDIUM_RISK').length; // 6
  }

  get safeCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'LOW_RISK').length; // 69
  }

  get filteredSkuItems(): CapitalSkuItem[] {
    let result = [...this.skuItems];

    if (this.selectedRiskFilter) {
      result = result.filter(i => i.riskClass === this.selectedRiskFilter);
    }

    if (this.searchTerm.trim()) {
      const term = this.searchTerm.toLowerCase().trim();
      result = result.filter(i =>
        i.sku.toLowerCase().includes(term) ||
        i.name.toLowerCase().includes(term)
      );
    }

    return result;
  }

  setFilter(filter: string): void {
    this.selectedRiskFilter = filter;
  }

  openSkuDetail(skuItem: CapitalSkuItem): void {
    this.selectedSkuItem = skuItem;
    this.drawerOpen = true;
    document.body.style.overflow = 'hidden';
  }

  closeSkuDetail(): void {
    this.drawerOpen = false;
    this.selectedSkuItem = null;
    this.showShapCalcModal = false;
    document.body.style.overflow = '';
  }

  ngOnDestroy(): void {
    document.body.style.overflow = '';
  }

  openShapCalcModal(): void {
    this.showShapCalcModal = true;
  }

  closeShapCalcModal(): void {
    this.showShapCalcModal = false;
  }

  navigateToRisk(): void {
    this.closeSkuDetail();
    this.navigateTo.emit('slow-moving-risk');
  }

  navigateToDecisions(): void {
    this.closeSkuDetail();
    this.navigateTo.emit('decision-support');
  }

  getMonthlyHoldingCost(exposureStr: string): string {
    if (!exposureStr) return '0.5M';
    const val = parseFloat(exposureStr.replace('M', '').replace('B', '000'));
    if (isNaN(val)) return '0.5M';
    const monthly = (val * 0.012).toFixed(1);
    return `${monthly}M / tháng`;
  }

  getQuickRecoveryAmount(exposureStr: string): string {
    if (!exposureStr) return '50.0M';
    const val = parseFloat(exposureStr.replace('M', '').replace('B', '000'));
    if (isNaN(val)) return '50.0M';
    const min = (val * 0.5).toFixed(1);
    const max = (val * 0.75).toFixed(1);
    return `${min}M – ${max}M`;
  }
}
