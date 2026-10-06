import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';

export interface CapitalSkuItem {
  sku: string;
  name: string;
  category?: string;
  riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string;
  dslsDays: number;
  capitalExposureVal?: number;
  capitalExposure: string;
  capitalPriority: string;
  opportunityCostVal?: number;
  opportunityCost: string;
  agingBucket: string;
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

  selectedRiskFilter: string = '';
  searchTerm: string = '';
  capitalFilter: string = '';
  agingFilter: string = '';
  sortField: string = 'capitalExposureVal';
  sortDirection: 'desc' | 'asc' = 'desc';
  selectedPeriod: string = '30 ngày qua';

  drawerOpen: boolean = false;
  selectedSkuItem: CapitalSkuItem | null = null;
  showShapCalcModal: boolean = false;

  summaryGrid = {
    totalExposure: '0',
    highRiskExposure: '0',
    opportunityCost: '0',
    affectedSkus: '0 SKU'
  };

  riskDistribution: any[] = [];
  agingDistribution: any[] = [];
  skuItems: CapitalSkuItem[] = [];

  constructor(
    private apiService: ApiService,
    private router: Router
  ) {}

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
          this.apiService.listCapitalExposureItems(aid, { limit: 500 }).subscribe({
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
    this.skuItems = itemsList.map((i: any) => {
      const rawClass = i.slow_moving_risk_class || i.risk_class || 'LOW_RISK';
      const riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK' = (rawClass === 'CRITICAL' || rawClass === 'HIGH_RISK') ? 'HIGH_RISK' : (rawClass === 'MEDIUM_RISK' ? 'MEDIUM_RISK' : 'LOW_RISK');
      const dsls = i.aging_days !== undefined ? i.aging_days : (i.dsls || 0);
      const rawProb = i.risk_probability ?? (i.risk_score ? (i.risk_score > 1 ? i.risk_score / 100 : i.risk_score) : undefined);
      const probVal = rawProb !== undefined && rawProb !== null
        ? Number(rawProb)
        : (riskClass === 'HIGH_RISK' ? 0.92 : (riskClass === 'MEDIUM_RISK' ? 0.55 : 0.08));
      const invVal = i.inventory_value || i.capital_exposure || i.capital_locked || 0;
      const oppCostVal = i.estimated_opportunity_cost || (invVal * 0.12 / 365 * Math.max(1, dsls));

      let agingBucketStr = 'Dưới 30 ngày';
      if (dsls > 90) agingBucketStr = 'Trên 90 ngày';
      else if (dsls > 60) agingBucketStr = '61–90 ngày';
      else if (dsls > 30) agingBucketStr = '31–60 ngày';

      const prioMultiplier = riskClass === 'HIGH_RISK' ? 0.9 : (riskClass === 'MEDIUM_RISK' ? 0.5 : 0.0);

      const rawZeroRate = i.zero_rate_90d ?? i.zero_sales_rate ?? (dsls > 90 ? 0.92 : (dsls > 30 ? 0.55 : 0.12));

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
        zeroRatePct: `${(rawZeroRate * 100).toFixed(1)}%`,
        demandProb: 0.1,
        demandPattern: dsls > 90 ? 'Bán lắt nhắt' : 'Bán không đều',
        shapFactors: [
          { label: 'Số ngày chưa có đơn hàng mới', subDesc: `Đã ${dsls} ngày đọng vốn trong kho`, impactText: dsls > 60 ? 'Tác động mạnh' : 'Mức vừa', score: dsls > 60 ? 4 : 2, pct: Math.min(100, Math.round(dsls / 2)), severity: (dsls > 90 ? 'red' : (dsls > 30 ? 'amber' : 'emerald')) as 'red' | 'amber' | 'emerald' }
        ],
        conclusion: `SKU đang đọng vốn ${this.formatCurrencyShort(invVal)} trong kho, thời gian lưu kho ${dsls} ngày.`
      };
    });

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

  get totalCount(): number {
    return this.skuItems.length;
  }

  get highRiskCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'HIGH_RISK').length;
  }

  get watchCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'MEDIUM_RISK').length;
  }

  get safeCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'LOW_RISK').length;
  }

  get filteredSkuItems(): CapitalSkuItem[] {
    let result = this.skuItems.filter(i => {
      const matchRisk = !this.selectedRiskFilter || i.riskClass === this.selectedRiskFilter;
      const term = this.searchTerm.toLowerCase().trim();
      const matchSearch = !term ||
        i.sku.toLowerCase().includes(term) ||
        i.name.toLowerCase().includes(term) ||
        (i.category && i.category.toLowerCase().includes(term));

      let matchCapital = true;
      const capVal = i.capitalExposureVal || 0;
      if (this.capitalFilter === 'LOW') matchCapital = capVal < 10000000;
      else if (this.capitalFilter === 'MID') matchCapital = capVal >= 10000000 && capVal <= 50000000;
      else if (this.capitalFilter === 'HIGH') matchCapital = capVal > 50000000;

      let matchAging = true;
      const dsls = i.dslsDays || 0;
      if (this.agingFilter === 'FRESH') matchAging = dsls <= 30;
      else if (this.agingFilter === 'AGING') matchAging = dsls > 30 && dsls <= 60;
      else if (this.agingFilter === 'AT_RISK') matchAging = dsls > 60 && dsls <= 90;
      else if (this.agingFilter === 'CRITICAL') matchAging = dsls > 90;

      return matchRisk && matchSearch && matchCapital && matchAging;
    });

    result.sort((a, b) => {
      let valA: number = 0;
      let valB: number = 0;

      if (this.sortField === 'capitalExposureVal') {
        valA = a.capitalExposureVal || 0;
        valB = b.capitalExposureVal || 0;
      } else if (this.sortField === 'opportunityCostVal') {
        valA = a.opportunityCostVal || 0;
        valB = b.opportunityCostVal || 0;
      } else if (this.sortField === 'dslsDays') {
        valA = a.dslsDays || 0;
        valB = b.dslsDays || 0;
      }

      if (valA < valB) return this.sortDirection === 'desc' ? 1 : -1;
      if (valA > valB) return this.sortDirection === 'desc' ? -1 : 1;
      return 0;
    });

    return result;
  }

  exportReport(format: 'csv' | 'excel' = 'csv'): void {
    const headers = ['Mã sản phẩm', 'Tên sản phẩm', 'Danh mục', 'Phân nhóm rủi ro', 'Số ngày đọng vốn', 'Tổng vốn tồn đọng (VND)', 'Chi phí cơ hội ước tính (VND)', 'Phân loại thời gian tồn kho'];
    const rows = this.filteredSkuItems.map(item => [
      item.sku,
      `"${item.name.replace(/"/g, '""')}"`,
      `"${(item.category || 'Thiết bị & Phụ kiện').replace(/"/g, '""')}"`,
      item.riskClass === 'HIGH_RISK' ? 'Rủi ro cao' : (item.riskClass === 'MEDIUM_RISK' ? 'Cần theo dõi' : 'An toàn'),
      item.dslsDays,
      item.capitalExposureVal || 0,
      item.opportunityCostVal || 0,
      `"${item.agingBucket}"`
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const fileName = `bao_cao_von_dong_nguy_co_${new Date().toISOString().split('T')[0]}.${format === 'excel' ? 'csv' : 'csv'}`;
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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
    this.router.navigate(['/app/risk']);
  }

  navigateToDecisions(): void {
    this.closeSkuDetail();
    this.navigateTo.emit('decision-support');
    this.router.navigate(['/app/decisions']);
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
