import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

export interface CapitalSkuItem {
  sku: string;
  name: string;
  category?: string;
  riskClass: 'CRITICAL' | 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string;
  dslsDays: number;
  capitalExposureVal?: number;
  capitalExposure: string;
  capitalPriority: string;
  capitalPriorityVal?: number;
  opportunityCostVal: number | null;
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
  imports: [CommonModule, FormsModule, PageMotionDirective],
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
  dataState: 'loading' | 'ready' | 'empty' | 'error' = 'loading';
  loadError = '';

  constructor(
    private apiService: ApiService,
    private router: Router
  ) {}

  formatCurrencyShort(val: number | null | undefined): string {
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
    this.dataState = 'loading';
    this.loadError = '';
    this.skuItems = [];
    this.apiService.createCapitalExposureAnalysis({
      merchant_id: this.merchantId,
      dataset_version: this.datasetVersion
    }).subscribe({
      next: (res: any) => {
        if (res && res.analysis_id) {
          const aid = res.analysis_id;
          this.apiService.getAllCapitalExposureItems(aid).subscribe({
            next: (itemsRes: any) => {
              const realItems = itemsRes.items || [];
              if (realItems.length > 0) {
                this.processRealData(res, realItems);
              } else {
                this.setEmptyDataState();
              }
            },
            error: (err: any) => {
              this.setErrorDataState(err?.error?.detail || 'Không thể tải toàn bộ danh mục đánh giá vốn. Vui lòng thử lại.');
            }
          });
        } else {
          this.setEmptyDataState();
        }
      },
      error: (err: any) => {
        this.setErrorDataState(err?.error?.detail || err?.error?.error || 'Không thể tải dữ liệu đánh giá vốn đọng. Vui lòng thử lại.');
      }
    });
  }

  goToImport(): void {
    this.router.navigate(['/app/import']);
  }

  setEmptyDataState(): void {
    this.dataState = 'empty';
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

  private setErrorDataState(message: string): void {
    this.dataState = 'error';
    this.loadError = message;
    this.skuItems = [];
    this.summaryGrid = { totalExposure: '0', highRiskExposure: '0', opportunityCost: '0', affectedSkus: '0 SKU' };
    this.riskDistribution = [];
    this.agingDistribution = [];
  }

  processRealData(analysisRes: any, itemsList: any[]): void {
    this.skuItems = itemsList.map((i: any) => {
      const rawClass = String(i.slow_moving_risk_class || i.risk_class || 'LOW_RISK').toUpperCase();
      const riskClass: CapitalSkuItem['riskClass'] = rawClass === 'CRITICAL'
        ? 'CRITICAL'
        : (rawClass === 'HIGH_RISK' ? 'HIGH_RISK' : (rawClass === 'MEDIUM_RISK' ? 'MEDIUM_RISK' : 'LOW_RISK'));
      const dsls = Number(i.aging_days ?? i.dsls ?? 0);
      const rawProb = i.risk_probability ?? (i.risk_score ? (i.risk_score > 1 ? i.risk_score / 100 : i.risk_score) : undefined);
      const probVal = rawProb !== undefined && rawProb !== null
        ? Number(rawProb)
        : 0;
      const invVal = Number(i.inventory_value ?? i.capital_exposure ?? i.capital_locked ?? 0);
      const riskWeightedVal = Number(i.risk_weighted_exposure ?? i.probability_adjusted_exposure ?? 0);
      const oppCostRaw = i.estimated_opportunity_cost;
      const oppCostVal = oppCostRaw === null || oppCostRaw === undefined ? null : Number(oppCostRaw);

      let agingBucketStr = 'Dưới 30 ngày';
      if (dsls > 90) agingBucketStr = 'Trên 90 ngày';
      else if (dsls > 60) agingBucketStr = '61–90 ngày';
      else if (dsls > 30) agingBucketStr = '31–60 ngày';

      return {
        sku: i.sku || i.canonical_sku_id || 'SKU_UNKNOWN',
        name: i.product_name || i.name || i.sku || 'Sản phẩm',
        riskClass: riskClass,
        probabilityPct: `${(probVal * 100).toFixed(1)}%`,
        dslsDays: dsls,
        capitalExposureVal: invVal,
        capitalExposure: this.formatCurrencyShort(invVal),
        capitalPriorityVal: riskWeightedVal,
        capitalPriority: this.formatCurrencyShort(riskWeightedVal),
        opportunityCostVal: oppCostVal,
        opportunityCost: oppCostVal === null ? 'Chưa có dữ liệu' : this.formatCurrencyShort(oppCostVal),
        agingBucket: agingBucketStr,
        sales30d: Number(i.sold_30d || 0),
        sales90d: Number(i.sold_90d || 0),
        zeroRatePct: 'Chưa có dữ liệu',
        demandProb: probVal,
        demandPattern: 'Chưa có dữ liệu',
        shapFactors: [
          { label: 'Thời gian lưu kho', subDesc: `Ghi nhận ${dsls} ngày tồn kho theo bản phân tích vốn.`, impactText: 'Dữ liệu đầu vào', score: 0, pct: 0, severity: (dsls > 90 ? 'red' : (dsls > 30 ? 'amber' : 'emerald')) as 'red' | 'amber' | 'emerald' }
        ],
        conclusion: `Bản ghi có giá trị vốn tồn kho ${this.formatCurrencyShort(invVal)} và thời gian lưu kho ${dsls} ngày. Cần đối chiếu chính sách hàng hóa trước khi triển khai phương án xử lý.`
      };
    });

    const totalVal = this.skuItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const totalOppCost = this.skuItems.reduce((acc, i) => acc + (i.opportunityCostVal || 0), 0);
    const highRiskItems = this.skuItems.filter(i => i.riskClass === 'CRITICAL' || i.riskClass === 'HIGH_RISK');
    const highRiskVal = highRiskItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);

    this.summaryGrid = {
      totalExposure: this.formatCurrencyShort(totalVal),
      highRiskExposure: this.formatCurrencyShort(highRiskVal),
      opportunityCost: this.formatCurrencyShort(totalOppCost),
      affectedSkus: `${highRiskItems.length} SKU`
    };

    const criticalItems = this.skuItems.filter(i => i.riskClass === 'CRITICAL');
    const highItems = this.skuItems.filter(i => i.riskClass === 'HIGH_RISK');
    const medItems = this.skuItems.filter(i => i.riskClass === 'MEDIUM_RISK');
    const lowItems = this.skuItems.filter(i => i.riskClass === 'LOW_RISK');

    const criticalExp = criticalItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const highExp = highItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const medExp = medItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);
    const lowExp = lowItems.reduce((acc, i) => acc + (i as any).capitalExposureVal, 0);

    const calcSharePct = (val: number) => totalVal > 0 ? Math.round((val / totalVal) * 100) : 0;

    this.riskDistribution = [
      { label: 'Rủi ro rất cao', exposure: this.formatCurrencyShort(criticalExp), sharePct: calcSharePct(criticalExp), count: criticalItems.length, color: 'bg-rose-700', badgeClass: 'bg-rose-50 text-rose-800 border-rose-200' },
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
      { label: '61–90 ngày (Tồn đọng nhẹ)', exposure: this.formatCurrencyShort(atRiskExp), sharePct: calcSharePct(atRiskExp), count: atRiskItems.length, color: 'bg-amber-600', desc: 'Cần đánh giá phương án xúc tiến phù hợp' },
      { label: 'Trên 90 ngày (Lưu kho kéo dài)', exposure: this.formatCurrencyShort(critAgingExp), sharePct: calcSharePct(critAgingExp), count: critAgingItems.length, color: 'bg-rose-500', desc: 'Ưu tiên đánh giá phương án thu hồi vốn' }
    ];
    this.dataState = 'ready';
  }

  get totalCount(): number {
    return this.skuItems.length;
  }

  get highRiskCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'CRITICAL' || i.riskClass === 'HIGH_RISK').length;
  }

  get criticalCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'CRITICAL').length;
  }

  get watchCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'MEDIUM_RISK').length;
  }

  get safeCount(): number {
    return this.skuItems.filter(i => i.riskClass === 'LOW_RISK').length;
  }

  get filteredSkuItems(): CapitalSkuItem[] {
    let result = this.skuItems.filter(i => {
      const matchRisk = !this.selectedRiskFilter
        || (this.selectedRiskFilter === 'AT_RISK'
          ? i.riskClass === 'CRITICAL' || i.riskClass === 'HIGH_RISK'
          : i.riskClass === this.selectedRiskFilter);
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
      item.riskClass === 'CRITICAL' ? 'Rủi ro rất cao' : (item.riskClass === 'HIGH_RISK' ? 'Rủi ro cao' : (item.riskClass === 'MEDIUM_RISK' ? 'Cần theo dõi' : 'Rủi ro thấp')),
      item.dslsDays,
      item.capitalExposureVal || 0,
      item.opportunityCostVal ?? '',
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
    const sku = this.selectedSkuItem?.sku;
    this.closeSkuDetail();
    this.navigateTo.emit(sku ? `decision-support?sku=${sku}` : 'decision-support');
    this.router.navigate(['/app/decisions'], { queryParams: sku ? { sku } : {} });
  }

}
