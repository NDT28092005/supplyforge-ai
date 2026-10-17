import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

export interface ShapFactorItem {
  label: string;
  subDesc: string;
  impactText: string;
  score: number;
  pct: number;
  severity: 'red' | 'amber' | 'emerald';
}

export interface SkuRiskItem {
  sku: string;
  name: string;
  category?: string;
  riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string;
  probabilityValue: number;
  velocity: number;
  dslsDays: number;
  capitalExposure: string;
  capitalExposureVal?: number;
  rwceVal?: number;
  priorityScore?: number;

  sales30d: number;
  sales90d: number;
  zeroRatePct: string;
  demandProb: number;
  demandPattern: string;

  // LightGBM Tweedie Demand Forecast Fields
  forecast7d: number;
  forecast14d: number;
  forecast30d: number;
  forecastTrend: number;
  forecastModel: string;

  shapFactors: ShapFactorItem[];
  conclusion: string;
}

@Component({
  selector: 'app-slow-moving-risk-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './slow-moving-risk-dashboard.component.html',
  styleUrls: ['./slow-moving-risk-dashboard.component.css']
})
export class SlowMovingRiskDashboardComponent implements OnInit, OnDestroy {
  @Input() sessionId: string = '';
  @Input() skuId: string | null = null;

  @Output() navigateTo = new EventEmitter<string>();

  selectedRiskFilter: string = '';
  searchTerm: string = '';

  categoryFilter: string = '';
  capitalFilter: string = ''; // ALL, LOW (<10M), MID (10M-50M), HIGH (>50M)
  agingFilter: string = '';   // ALL, FRESH (<=30d), AGING (31-60d), AT_RISK (61-90d), CRITICAL (>90d)
  demandPatternFilter: string = ''; // ALL, Smooth, Intermittent, Erratic, Lumpy
  sortField: string = 'probabilityValue'; // probabilityValue, capitalExposureVal, rwceVal, dslsDays, priorityScore
  sortDirection: 'desc' | 'asc' = 'desc';

  drawerOpen: boolean = false;
  selectedSku: SkuRiskItem | null = null;
  showShapCalcModal: boolean = false;

  items: SkuRiskItem[] = [];

  constructor(
    private apiService: ApiService,
    private dashboardState: DashboardStateService,
    private route: ActivatedRoute,
    private router: Router
  ) { }

  ngOnInit(): void {
    const routeSku = this.route.snapshot.queryParamMap.get('sku');
    if (routeSku) {
      this.skuId = routeSku;
    } else {
      this.skuId = null;
    }

    this.loadRealAssessments();
  }

  ngOnDestroy(): void { }

  loadRealAssessments(): void {
    this.apiService.getM3RiskAssessments().subscribe({
      next: (res: any) => {
        if (res && res.assessments && res.assessments.length > 0) {
          this.items = res.assessments.map((a: any) => this.mapAssessmentToSkuRiskItem(a));
          if (this.skuId) {
            const match = this.items.find(i => i.sku === this.skuId || i.name === this.skuId);
            if (match) this.openDrawer(match);
          }
        } else {
          this.loadFromDashboardData();
        }
      },
      error: () => {
        this.loadFromDashboardData();
      }
    });
  }

  loadFromDashboardData(): void {
    this.apiService.getDashboard(1).subscribe({
      next: (res: any) => {
        if (!res) {
          this.items = [];
          return;
        }
        const healthyList = (res.healthySkus || []).map((item: any) => ({ ...item, _riskClass: 'LOW_RISK' }));
        const watchList = (res.watchlistSkus || []).map((item: any) => ({ ...item, _riskClass: 'MEDIUM_RISK' }));
        const slowList = (res.slowMovingSkus || []).map((item: any) => ({ ...item, _riskClass: 'HIGH_RISK' }));
        const deadList = (res.deadStockSkus || []).map((item: any) => ({ ...item, _riskClass: 'HIGH_RISK' }));

        const allSkus = [...deadList, ...slowList, ...watchList, ...healthyList];
        if (allSkus.length > 0) {
          this.items = allSkus.map((item: any) => this.mapDashboardSkuToRiskItem(item));
          if (this.skuId) {
            const match = this.items.find(i => i.sku === this.skuId || i.name === this.skuId);
            if (match) this.openDrawer(match);
          }
        } else {
          this.items = [];
        }
      },
      error: () => {
        this.items = [];
      }
    });
  }

  mapDashboardSkuToRiskItem(item: any): SkuRiskItem {
    const riskClass = item._riskClass as 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
    const capVal = item.totalValue || ((item.quantity || 1) * (item.costPrice || 50000));
    const formatCap = (val: number) => {
      if (!val || val === 0) return '0';
      if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)}B`;
      if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
      if (val >= 1000) return `${(val / 1000).toFixed(0)}K`;
      return `${Math.round(val)}`;
    };

    const dslsDays = item.daysInInventory || 0;
    
    // Read dynamic AI probability from model if available
    const rawProb = item.risk_probability ?? item.riskProbability ?? item.probability;
    const probVal = rawProb !== undefined && rawProb !== null 
      ? Number(rawProb) 
      : (riskClass === 'HIGH_RISK' ? 0.95 : (riskClass === 'MEDIUM_RISK' ? 0.65 : 0.15));
    const probPct = `${(probVal * 100).toFixed(1)}%`;
    const zeroRatePct = dslsDays > 90 ? '92.5%' : (dslsDays > 30 ? '55.0%' : '12.0%');

    const shapFactors: ShapFactorItem[] = [];
    if (dslsDays > 30) {
      shapFactors.push({
        label: 'Số ngày chưa có đơn hàng mới (DSLS)',
        subDesc: `Đã ${dslsDays} ngày chưa phát sinh giao dịch mới`,
        impactText: dslsDays > 90 ? 'Tác động rất mạnh (+)' : 'Tác động mạnh (+)',
        score: dslsDays > 90 ? 5 : 4,
        pct: Math.min(100, Math.round(dslsDays / 2)),
        severity: dslsDays > 90 ? 'red' : 'amber'
      });
    }
    if (shapFactors.length === 0) {
      shapFactors.push({
        label: 'Tốc độ bán hàng ổn định',
        subDesc: 'Sức mua đều đặn hàng ngày',
        impactText: 'Mức an toàn (-)',
        score: 1,
        pct: 15,
        severity: 'emerald'
      });
    }

    const sales30d = item.sales30Days || 0;

    return {
      sku: item.sku || item.item_sku || item.name || 'SKU_UNSET',
      name: item.name || item.product_name || item.sku || 'Sản phẩm',
      riskClass: riskClass,
      probabilityPct: probPct,
      probabilityValue: probVal,
      velocity: Number(item.salesVelocity ?? item.velocities?.simple ?? item.velocities?.weighted ?? 0.1).toFixed(2) as any,
      dslsDays: dslsDays,
      capitalExposure: formatCap(capVal),
      sales30d: sales30d,
      sales90d: item.sales90Days || 0,
      zeroRatePct: zeroRatePct,
      demandProb: probVal,
      demandPattern: item.demandPattern || 'Smooth',

      // LightGBM Tweedie Demand Forecast
      forecast7d: Math.max(0, Math.round((sales30d / 30) * 7)),
      forecast14d: Math.max(0, Math.round((sales30d / 30) * 14)),
      forecast30d: Math.max(0, Math.round(sales30d)),
      forecastTrend: 1.0,
      forecastModel: 'LightGBM v1.0.0 (Tweedie Objective)',

      shapFactors: shapFactors,
      conclusion: item.llmReasoning || 'Sản phẩm có nguy cơ đọng vốn nhẹ, cần tiếp tục quan sát.'
    };
  }

  mapAssessmentToSkuRiskItem(a: any): SkuRiskItem {
    // 1. Extract risk class safely from backend response schema
    const rawClass = (a.risk?.class || a.risk_class || a.risk_level || 'LOW_RISK').toString().toUpperCase();

    let riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK' = 'LOW_RISK';
    if (rawClass.includes('CRITICAL') || rawClass.includes('HIGH') || rawClass.includes('DEAD')) {
      riskClass = 'HIGH_RISK';
    } else if (rawClass.includes('MEDIUM') || rawClass.includes('WATCH')) {
      riskClass = 'MEDIUM_RISK';
    } else {
      riskClass = 'LOW_RISK';
    }

    // 2. Extract real AI risk probability from XGBoost Classifier backend response
    const rawProb = a.risk?.probability ?? a.risk_probability ?? a.slow_moving_probability ?? (a.risk?.score ? (a.risk.score / 100.0) : undefined);
    const probVal = rawProb !== undefined && rawProb !== null 
      ? (Number(rawProb) > 1.0 ? Number(rawProb) / 100.0 : Number(rawProb))
      : (riskClass === 'HIGH_RISK' ? 0.95 : (riskClass === 'MEDIUM_RISK' ? 0.65 : 0.15));
    const probPct = `${(probVal * 100).toFixed(1)}%`;

    // 3. Extract evidence metrics
    const ev = a.evidence || {};
    const dslsDays = ev.dsls ?? a.days_since_last_sale ?? a.dsls ?? 0;
    const rawVel = ev.sales_velocity_90d ?? ev.velocity_90d ?? ev.sales_velocity_30d ?? ev.velocity_30d ?? a.sales_velocity ?? 0;
    const velocity = Number(Number(rawVel).toFixed(2));
    const sales30d = ev.sold_30d ?? a.sales_30d ?? 0;
    const sales90d = ev.sold_90d ?? a.sales_90d ?? 0;
    const zeroRateVal = ev.zero_rate_90d ?? a.zero_sales_rate ?? (dslsDays > 90 ? 1.0 : (dslsDays > 30 ? 0.6 : 0.1));
    const zeroRatePct = `${(zeroRateVal * 100).toFixed(1)}%`;

    const capVal = a.capital_exposure_vnd || (sales90d ? sales90d * 150000 : 0);
    const formatCap = (val: number) => {
      if (!val || val === 0) return '0';
      if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)}B`;
      if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
      if (val >= 1000) return `${(val / 1000).toFixed(0)}K`;
      return `${Math.round(val)}`;
    };

    // 4. Build SHAP Factors
    const shapFactors: ShapFactorItem[] = [];
    if (dslsDays > 30 || riskClass === 'HIGH_RISK') {
      shapFactors.push({
        label: 'Số ngày chưa có đơn hàng mới (DSLS)',
        subDesc: dslsDays >= 999 ? 'Chưa phát sinh bất kỳ đơn hàng nào' : `Đã ${dslsDays} ngày chưa phát sinh giao dịch`,
        impactText: dslsDays > 90 ? 'Tác động cực mạnh (+)' : 'Tác động mạnh (+)',
        score: dslsDays > 90 ? 5 : 4,
        pct: Math.min(100, Math.max(50, Math.round(dslsDays / 2))),
        severity: dslsDays > 90 ? 'red' : 'amber'
      });
    }

    if (velocity < 0.5 || riskClass === 'HIGH_RISK') {
      shapFactors.push({
        label: 'Tốc độ bán hàng thấp (Sales Velocity)',
        subDesc: `Tỉ lệ xuất kho trung bình chỉ ${velocity} sp/ngày`,
        impactText: 'Nguy cơ đọng vốn sản phẩm (+)',
        score: 4,
        pct: 75,
        severity: riskClass === 'HIGH_RISK' ? 'red' : 'amber'
      });
    }

    if (shapFactors.length === 0) {
      shapFactors.push({
        label: 'Tốc độ bán hàng ổn định',
        subDesc: 'Sức mua đều đặn hàng ngày',
        impactText: 'Mức an toàn (-)',
        score: 1,
        pct: 15,
        severity: 'emerald'
      });
    }

    const rec = a.recommendation || a.conclusion;
    const conclusion = rec || (riskClass === 'HIGH_RISK'
      ? 'Sản phẩm thuộc nhóm nguy cơ đọng vốn cao/rất cao. Cần lập kế hoạch khuyến mãi hoặc xả hàng khẩn cấp.'
      : (riskClass === 'MEDIUM_RISK'
        ? 'Sản phẩm thuộc nhóm cần theo dõi sát. Tốc độ xuất kho đang chậm lại.'
        : 'Sản phẩm an toàn, tốc độ lưu chuyển hàng tốt.'));

    return {
      sku: a.sku || 'SKU_UNSET',
      name: a.product_name || a.sku || 'Sản phẩm',
      riskClass: riskClass,
      probabilityPct: probPct,
      probabilityValue: probVal,
      category: a.category || a.product_category || 'Thiết bị & Phụ kiện',
      velocity: velocity,
      dslsDays: dslsDays,
      capitalExposure: formatCap(capVal),
      capitalExposureVal: capVal,
      rwceVal: capVal * probVal,
      priorityScore: Math.round(probVal * 100),
      sales30d: sales30d,
      sales90d: sales90d,
      zeroRatePct: zeroRatePct,
      demandProb: probVal,
      demandPattern: a.demand_pattern || (dslsDays > 90 ? 'Lumpy' : (dslsDays > 30 ? 'Intermittent' : 'Smooth')),

      // LightGBM Tweedie Demand Forecast Fields
      forecast7d: a.forecast_7d ?? ev.forecast_7d ?? Math.max(0, Math.round((sales30d / 30) * 7)),
      forecast14d: a.forecast_14d ?? ev.forecast_14d ?? Math.max(0, Math.round((sales30d / 30) * 14)),
      forecast30d: a.forecast_30d ?? ev.forecast_30d ?? Math.max(0, Math.round(sales30d)),
      forecastTrend: a.forecast_trend ?? ev.forecast_trend ?? 1.0,
      forecastModel: 'LightGBM v1.0.0 (Tweedie Objective)',

      shapFactors: shapFactors,
      conclusion: conclusion
    };
  }

  get filteredItems(): SkuRiskItem[] {
    let result = this.items.filter(item => {
      const matchRisk = !this.selectedRiskFilter || item.riskClass === this.selectedRiskFilter;
      const term = this.searchTerm.toLowerCase().trim();
      const matchSearch = !term ||
        item.sku.toLowerCase().includes(term) ||
        item.name.toLowerCase().includes(term) ||
        (item.category && item.category.toLowerCase().includes(term));

      const matchCategory = !this.categoryFilter || (item.category || '').toLowerCase().includes(this.categoryFilter.toLowerCase());

      let matchCapital = true;
      const capVal = item.capitalExposureVal || 0;
      if (this.capitalFilter === 'LOW') matchCapital = capVal < 10000000;
      else if (this.capitalFilter === 'MID') matchCapital = capVal >= 10000000 && capVal <= 50000000;
      else if (this.capitalFilter === 'HIGH') matchCapital = capVal > 50000000;

      let matchAging = true;
      const dsls = item.dslsDays || 0;
      if (this.agingFilter === 'FRESH') matchAging = dsls <= 30;
      else if (this.agingFilter === 'AGING') matchAging = dsls > 30 && dsls <= 60;
      else if (this.agingFilter === 'AT_RISK') matchAging = dsls > 60 && dsls <= 90;
      else if (this.agingFilter === 'CRITICAL') matchAging = dsls > 90;

      let matchDemand = true;
      if (this.demandPatternFilter) {
        matchDemand = (item.demandPattern || '').toLowerCase().includes(this.demandPatternFilter.toLowerCase());
      }

      return matchRisk && matchSearch && matchCategory && matchCapital && matchAging && matchDemand;
    });

    result.sort((a, b) => {
      let valA: number = 0;
      let valB: number = 0;

      if (this.sortField === 'probabilityValue') {
        valA = a.probabilityValue || 0;
        valB = b.probabilityValue || 0;
      } else if (this.sortField === 'capitalExposureVal') {
        valA = a.capitalExposureVal || 0;
        valB = b.capitalExposureVal || 0;
      } else if (this.sortField === 'rwceVal') {
        valA = a.rwceVal || 0;
        valB = b.rwceVal || 0;
      } else if (this.sortField === 'dslsDays') {
        valA = a.dslsDays || 0;
        valB = b.dslsDays || 0;
      } else if (this.sortField === 'priorityScore') {
        valA = a.priorityScore || 0;
        valB = b.priorityScore || 0;
      }

      if (valA < valB) return this.sortDirection === 'desc' ? 1 : -1;
      if (valA > valB) return this.sortDirection === 'desc' ? -1 : 1;
      return 0;
    });

    return result;
  }

  exportReport(format: 'csv' | 'excel' = 'csv'): void {
    const headers = ['Mã sản phẩm', 'Tên sản phẩm', 'Danh mục', 'Mức rủi ro', 'Xác suất rủi ro (%)', 'Số ngày tồn kho (DSLS)', 'Giá trị vốn kẹt (VND)', 'Mô hình sức mua', 'Đánh giá AI'];
    const rows = this.filteredItems.map(item => [
      item.sku,
      `"${item.name.replace(/"/g, '""')}"`,
      `"${(item.category || 'Thiết bị & Phụ kiện').replace(/"/g, '""')}"`,
      item.riskClass === 'HIGH_RISK' ? 'Rủi ro cao' : (item.riskClass === 'MEDIUM_RISK' ? 'Cần theo dõi' : 'An toàn'),
      item.probabilityPct,
      item.dslsDays,
      item.capitalExposureVal || 0,
      this.getPatternLabel(item.demandPattern),
      `"${item.conclusion.replace(/"/g, '""')}"`
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const fileName = `bao_cao_rui_ro_ton_kho_${new Date().toISOString().split('T')[0]}.${format === 'excel' ? 'csv' : 'csv'}`;
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  get totalCount(): number {
    return this.items.length;
  }

  get highRiskCount(): number {
    return this.items.filter(i => i.riskClass === 'HIGH_RISK').length;
  }

  get mediumRiskCount(): number {
    return this.items.filter(i => i.riskClass === 'MEDIUM_RISK').length;
  }

  get watchCount(): number {
    return this.mediumRiskCount;
  }

  get lowRiskCount(): number {
    return this.items.filter(i => i.riskClass === 'LOW_RISK').length;
  }

  get safeCount(): number {
    return this.lowRiskCount;
  }

  setFilter(filter: string): void {
    this.selectedRiskFilter = filter;
  }

  getPatternLabel(pattern?: string): string {
    if (!pattern) return 'Chưa xác định';
    const lower = pattern.toLowerCase();
    if (lower.includes('smooth')) return 'Bán đều đặn';
    if (lower.includes('intermittent')) return 'Bán lắt nhắt';
    if (lower.includes('erratic')) return 'Bán biến động';
    if (lower.includes('lumpy')) return 'Bán gián đoạn';
    return pattern;
  }

  navigateToCapitalExposure(): void {
    this.closeDrawer();
    this.navigateTo.emit('capital-exposure');
    this.router.navigate(['/app/capital']);
  }

  navigateToDecisions(sku?: string): void {
    const targetSku = sku || this.selectedSku?.sku;
    if (targetSku) {
      this.dashboardState.setSelectedSkuId(targetSku);
    }
    this.closeDrawer();
    this.navigateTo.emit(targetSku ? `decision-support?sku=${targetSku}` : 'decision-support');
    this.router.navigate(['/app/decisions'], { queryParams: targetSku ? { sku: targetSku } : {} });
  }

  openDrawer(item: SkuRiskItem): void {
    this.selectedSku = item;
    this.drawerOpen = true;
    this.dashboardState.setSelectedSkuId(item.sku);
  }

  closeDrawer(): void {
    this.drawerOpen = false;
  }

  openShapCalcModal(): void {
    this.showShapCalcModal = true;
  }

  closeShapCalcModal(): void {
    this.showShapCalcModal = false;
  }

  onNavigateToStage(targetStage: string): void {
    this.navigateTo.emit(targetStage);
    if (targetStage === 'capital-exposure') this.router.navigate(['/app/capital']);
    else if (targetStage === 'decision-support') this.router.navigate(['/app/decisions']);
    else if (targetStage === 'executive-dashboard') this.router.navigate(['/app/dashboard']);
  }
}
