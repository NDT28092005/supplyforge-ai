import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';

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
  riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string;
  probabilityValue: number;
  velocity: number;
  dslsDays: number;
  capitalExposure: string;

  sales30d: number;
  sales90d: number;
  zeroRatePct: string;
  demandProb: number;
  demandPattern: string;

  shapFactors: ShapFactorItem[];
  conclusion: string;
}

@Component({
  selector: 'app-slow-moving-risk-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './slow-moving-risk-dashboard.component.html',
  styleUrls: ['./slow-moving-risk-dashboard.component.css']
})
export class SlowMovingRiskDashboardComponent implements OnInit, OnDestroy {
  @Input() sessionId: string = '';
  @Input() skuId: string | null = null;

  @Output() navigateTo = new EventEmitter<string>();

  selectedRiskFilter: string = '';
  searchTerm: string = '';

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
    } else if (!this.skuId) {
      this.skuId = this.dashboardState.state.selectedSkuId;
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
    const probPct = riskClass === 'HIGH_RISK' ? '96.5%' : (riskClass === 'MEDIUM_RISK' ? '65.0%' : '15.0%');
    const probVal = riskClass === 'HIGH_RISK' ? 0.965 : (riskClass === 'MEDIUM_RISK' ? 0.65 : 0.15);
    const zeroRatePct = dslsDays > 90 ? '92.5%' : (dslsDays > 30 ? '55.0%' : '12.0%');

    const shapFactors: ShapFactorItem[] = [];
    if (dslsDays > 30) {
      shapFactors.push({
        label: 'Số ngày chưa có đơn hàng mới',
        subDesc: `Đã ${dslsDays} ngày chưa phát sinh giao dịch mới`,
        impactText: dslsDays > 90 ? 'Tác động rất mạnh' : 'Tác động mạnh',
        score: dslsDays > 90 ? 5 : 4,
        pct: Math.min(100, Math.round(dslsDays / 2)),
        severity: dslsDays > 90 ? 'red' : 'amber'
      });
    }
    if (shapFactors.length === 0) {
      shapFactors.push({
        label: 'Tốc độ bán hàng ổn định',
        subDesc: 'Sức mua đều đặn hàng ngày',
        impactText: 'Mức an toàn',
        score: 1,
        pct: 15,
        severity: 'emerald'
      });
    }

    return {
      sku: item.sku || item.item_sku || item.name || 'SKU_UNSET',
      name: item.name || item.product_name || item.sku || 'Sản phẩm',
      riskClass: riskClass,
      probabilityPct: probPct,
      probabilityValue: probVal,
      velocity: Number(item.salesVelocity ?? item.velocities?.simple ?? item.velocities?.weighted ?? 0.1).toFixed(2) as any,
      dslsDays: dslsDays,
      capitalExposure: formatCap(capVal),
      sales30d: item.sales30Days || 0,
      sales90d: item.sales90Days || 0,
      zeroRatePct: zeroRatePct,
      demandProb: probVal,
      demandPattern: item.demandPattern || 'Smooth',
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

    // 2. Extract risk probability & score
    const rawProb = a.risk?.probability ?? a.risk_probability ?? a.slow_moving_probability;
    const probVal = rawProb !== undefined && rawProb !== null ? Number(rawProb) : (riskClass === 'HIGH_RISK' ? 0.95 : (riskClass === 'MEDIUM_RISK' ? 0.65 : 0.15));
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
        impactText: dslsDays > 90 ? 'Tác động cực mạnh' : 'Tác động mạnh',
        score: dslsDays > 90 ? 5 : 4,
        pct: Math.min(100, Math.max(50, Math.round(dslsDays / 2))),
        severity: dslsDays > 90 ? 'red' : 'amber'
      });
    }

    if (velocity < 0.5 || riskClass === 'HIGH_RISK') {
      shapFactors.push({
        label: 'Tốc độ bán hàng thấp (Sales Velocity)',
        subDesc: `Tỉ lệ xuất kho trung bình chỉ ${velocity} sp/ngày`,
        impactText: 'Nguy cơ đọng vốn sản phẩm',
        score: 4,
        pct: 75,
        severity: riskClass === 'HIGH_RISK' ? 'red' : 'amber'
      });
    }

    if (shapFactors.length === 0) {
      shapFactors.push({
        label: 'Tốc độ bán hàng ổn định',
        subDesc: 'Sức mua đều đặn hàng ngày',
        impactText: 'Mức an toàn',
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
      velocity: velocity,
      dslsDays: dslsDays,
      capitalExposure: formatCap(capVal),
      sales30d: sales30d,
      sales90d: sales90d,
      zeroRatePct: zeroRatePct,
      demandProb: probVal,
      demandPattern: a.demand_pattern || (dslsDays > 60 ? 'Lumpy' : 'Smooth'),
      shapFactors: shapFactors,
      conclusion: conclusion
    };
  }

  get filteredItems(): SkuRiskItem[] {
    return this.items.filter(item => {
      const matchFilter = !this.selectedRiskFilter || item.riskClass === this.selectedRiskFilter;
      const matchSearch = !this.searchTerm ||
        item.sku.toLowerCase().includes(this.searchTerm.toLowerCase()) ||
        item.name.toLowerCase().includes(this.searchTerm.toLowerCase());
      return matchFilter && matchSearch;
    });
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

  navigateToDecisions(): void {
    this.closeDrawer();
    this.navigateTo.emit('decision-support');
    this.router.navigate(['/app/decisions']);
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
