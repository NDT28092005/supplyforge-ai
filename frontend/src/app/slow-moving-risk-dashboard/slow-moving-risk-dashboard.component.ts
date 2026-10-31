import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';
import { forkJoin } from 'rxjs';

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
  riskClass: 'CRITICAL' | 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
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
  forecast7d: number | null;
  forecast14d: number | null;
  forecast30d: number | null;
  forecastTrend: string | null;
  forecastModel: string | null;

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
  sourceMode: 'CSV' | 'ODOO' = 'CSV';
  odooConnections: any[] = [];
  selectedOdooConnectionId = '';
  sourceMetadata: any = null;

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
  dataState: 'loading' | 'ready' | 'empty' | 'error' = 'loading';
  loadError = '';
  tableLoading = false;
  pageSize = 50;
  page = 1;
  totalItems = 0;
  riskSummary = {
    total_skus: 0,
    critical: 0,
    high_risk: 0,
    medium_risk: 0,
    low_risk: 0,
  };

  constructor(
    private apiService: ApiService,
    private dashboardState: DashboardStateService,
    private route: ActivatedRoute,
    private router: Router
  ) { }

  ngOnInit(): void {
    const routeSku = this.route.snapshot.queryParamMap.get('sku');
    const routeSource = this.route.snapshot.queryParamMap.get('source');
    const routeConnection = this.route.snapshot.queryParamMap.get('connection');
    if (routeSku) {
      this.skuId = routeSku;
    } else {
      this.skuId = null;
    }
    if (routeSource === 'odoo') {
      this.sourceMode = 'ODOO';
      this.selectedOdooConnectionId = routeConnection || '';
    }

    this.loadOdooSources();
    this.loadRealAssessments();
  }

  ngOnDestroy(): void { }

  loadRealAssessments(resetPage: boolean = false): void {
    if (resetPage) this.page = 1;
    const isInitialLoad = this.dataState === 'loading';
    if (isInitialLoad) this.dataState = 'loading';
    else this.tableLoading = true;
    this.loadError = '';
    const params = this.buildListParams();
    if (this.sourceMode === 'ODOO' && !this.selectedOdooConnectionId) {
      this.items = [];
      this.totalItems = 0;
      this.riskSummary = { total_skus: 0, critical: 0, high_risk: 0, medium_risk: 0, low_risk: 0 };
      this.sourceMetadata = null;
      this.dataState = 'empty';
      this.tableLoading = false;
      return;
    }
    const requests = this.sourceMode === 'ODOO'
      ? {
          list: this.apiService.getOperationalRiskAssessments(this.selectedOdooConnectionId, params),
          summary: this.apiService.getOperationalRiskSummary(this.selectedOdooConnectionId),
        }
      : {
          list: this.apiService.getM3RiskAssessments(params),
          summary: this.apiService.getM3RiskSummary(this.sessionId || undefined),
        };
    forkJoin(requests).subscribe({
      next: ({ list, summary }: any) => {
        const res = list;
        this.sourceMetadata = summary?.source || res?.source || null;
        this.riskSummary = {
          total_skus: Number(summary?.total_skus || 0),
          critical: Number(summary?.critical || 0),
          high_risk: Number(summary?.high_risk || 0),
          medium_risk: Number(summary?.medium_risk || 0),
          low_risk: Number(summary?.low_risk || 0),
        };
        this.totalItems = Number(res?.total_count || 0);
        if (res && Array.isArray(res.assessments) && res.assessments.length > 0) {
          this.items = res.assessments.map((a: any) => this.mapAssessmentToSkuRiskItem(a));
          if (this.skuId) {
            const match = this.items.find(i => i.sku === this.skuId || i.name === this.skuId);
            if (match) this.openDrawer(match);
          }
          this.dataState = 'ready';
        } else if (this.totalItems === 0 && !this.hasActiveFilters()) {
          this.dataState = 'empty';
        } else {
          this.items = [];
          this.dataState = 'ready';
        }
        this.tableLoading = false;
      },
      error: (err: any) => {
        this.dataState = 'error';
        this.tableLoading = false;
        this.loadError = err?.error?.detail || err?.error?.error || 'Không thể tải kết quả đánh giá rủi ro. Vui lòng thử lại.';
      }
    });
  }

  private loadOdooSources(): void {
    this.apiService.listIntegrationConnections().subscribe({
      next: (response: any) => {
        this.odooConnections = (response?.connections || []).filter((connection: any) => connection.status === 'ACTIVE');
      },
      // ERP is a paid capability. A CSV-only workspace must not see an error
      // merely because the optional source picker cannot be loaded.
      error: () => { this.odooConnections = []; },
    });
  }

  onSourceChanged(): void {
    if (this.sourceMode === 'ODOO' && !this.selectedOdooConnectionId) {
      this.selectedOdooConnectionId = this.odooConnections[0]?.id || '';
    }
    this.selectedRiskFilter = '';
    this.searchTerm = '';
    this.sourceMetadata = null;
    this.loadRealAssessments(true);
  }

  get selectedOdooConnectionName(): string {
    return this.odooConnections.find(connection => connection.id === this.selectedOdooConnectionId)?.display_name || 'Odoo';
  }

  private buildListParams(): Record<string, string | number> {
    const params: Record<string, string | number> = {
      limit: this.pageSize,
      offset: (this.page - 1) * this.pageSize,
      sort_by: this.serverSort(),
    };
    if (this.sessionId) params['session_id'] = this.sessionId;
    if (this.selectedRiskFilter) params['risk_class'] = this.selectedRiskFilter;
    if (this.searchTerm.trim()) params['sku'] = this.searchTerm.trim();
    if (this.categoryFilter) params['category'] = this.categoryFilter;
    if (this.capitalFilter) params['capital_band'] = this.capitalFilter;
    if (this.agingFilter) params['aging_band'] = this.agingFilter;
    return params;
  }

  private serverSort(): string {
    const fields: Record<string, string> = {
      probabilityValue: 'risk_probability',
      capitalExposureVal: 'capital_exposure',
      rwceVal: 'risk_score',
      dslsDays: 'dsls',
      priorityScore: 'risk_score',
    };
    const field = fields[this.sortField] || 'risk_probability';
    return this.sortDirection === 'desc' ? `-${field}` : field;
  }

  private hasActiveFilters(): boolean {
    return Boolean(
      this.selectedRiskFilter || this.searchTerm.trim() || this.categoryFilter ||
      this.capitalFilter || this.agingFilter || this.demandPatternFilter,
    );
  }

  goToImport(): void {
    this.router.navigate(['/app/import']);
  }

  mapAssessmentToSkuRiskItem(a: any): SkuRiskItem {
    // 1. Extract risk class safely from backend response schema
    const rawClass = (a.risk?.class || a.risk_class || a.risk_level || 'LOW_RISK').toString().toUpperCase();

    let riskClass: SkuRiskItem['riskClass'] = 'LOW_RISK';
    if (rawClass.includes('CRITICAL') || rawClass.includes('DEAD')) {
      riskClass = 'CRITICAL';
    } else if (rawClass.includes('HIGH')) {
      riskClass = 'HIGH_RISK';
    } else if (rawClass.includes('MEDIUM') || rawClass.includes('WATCH')) {
      riskClass = 'MEDIUM_RISK';
    } else {
      riskClass = 'LOW_RISK';
    }

    // 2. Extract the risk probability from the classifier response.
    const rawProb = a.risk?.probability ?? a.risk_probability ?? a.slow_moving_probability ?? (a.risk?.score ? (a.risk.score / 100.0) : undefined);
    const probVal = rawProb !== undefined && rawProb !== null
      ? (Number(rawProb) > 1.0 ? Number(rawProb) / 100.0 : Number(rawProb))
      : 0;
    const probPct = `${(probVal * 100).toFixed(1)}%`;

    // 3. Extract evidence metrics
    const ev = a.evidence || {};
    const dslsDays = ev.dsls ?? a.days_since_last_sale ?? a.dsls ?? 0;
    const rawVel = ev.sales_velocity_90d ?? ev.velocity_90d ?? ev.sales_velocity_30d ?? ev.velocity_30d ?? a.sales_velocity ?? 0;
    const velocity = Number(Number(rawVel).toFixed(2));
    const sales30d = ev.sold_30d ?? a.sales_30d ?? 0;
    const sales90d = ev.sold_90d ?? a.sales_90d ?? 0;
    const zeroRateVal = ev.zero_rate_90d ?? a.zero_sales_rate ?? 0;
    const zeroRatePct = `${(zeroRateVal * 100).toFixed(1)}%`;

    const capVal = Number(a.capital_exposure_vnd ?? 0);
    const formatCap = (val: number) => {
      if (!val || val === 0) return '0';
      if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)}B`;
      if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
      if (val >= 1000) return `${(val / 1000).toFixed(0)}K`;
      return `${Math.round(val)}`;
    };

    // These are persisted diagnostic signals from the risk pipeline, not
    // synthetic SHAP scores produced by the UI.
    const shapFactors = this.buildDiagnosticFactors(
      [...(a.primary_signals || []), ...(a.supporting_signals || []), ...(a.diagnostics || [])],
      ev,
      velocity,
      dslsDays
    );

    const rec = a.recommendation || a.conclusion;
    const conclusion = rec || (riskClass === 'CRITICAL' || riskClass === 'HIGH_RISK'
      ? 'Sản phẩm thuộc nhóm nguy cơ đọng vốn cao hoặc rất cao. Cần lập phương án khuyến mãi hoặc xử lý tồn kho ưu tiên.'
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
      demandPattern: a.demand_pattern || ev.demand_pattern || 'Chưa xác định',

      // LightGBM Tweedie Demand Forecast Fields
      forecast7d: this.toNullableNumber(a.forecast_7d ?? ev.forecast_7d),
      forecast14d: this.toNullableNumber(a.forecast_14d ?? ev.forecast_14d),
      forecast30d: this.toNullableNumber(a.forecast_30d ?? ev.forecast_30d),
      forecastTrend: (a.forecast_trend ?? ev.forecast_trend ?? null) as string | null,
      forecastModel: (a.forecast_model ?? ev.forecast_model ?? null) as string | null,

      shapFactors: shapFactors,
      conclusion: conclusion
    };
  }

  private toNullableNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '') return null;
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  private buildDiagnosticFactors(signals: unknown[], evidence: any, velocity: number, dslsDays: number): ShapFactorItem[] {
    const uniqueSignals = [...new Set(signals.filter((signal): signal is string => typeof signal === 'string'))];
    const descriptions: Record<string, Pick<ShapFactorItem, 'label' | 'subDesc' | 'impactText' | 'severity'>> = {
      LOW_SALES_VELOCITY: {
        label: 'Tốc độ bán hàng thấp',
        subDesc: `Tốc độ ghi nhận: ${velocity} sản phẩm/ngày.`,
        impactText: 'Tín hiệu chính', severity: 'amber'
      },
      POSSIBLE_OBSOLESCENCE: {
        label: 'Dấu hiệu nhu cầu suy giảm kéo dài',
        subDesc: dslsDays >= 999 ? 'Chưa ghi nhận đơn hàng trong cửa sổ quan sát.' : `Đã ${dslsDays} ngày chưa phát sinh đơn hàng.`,
        impactText: 'Tín hiệu chính', severity: 'red'
      },
      LUMPY_DEMAND: {
        label: 'Nhu cầu phát sinh không đều',
        subDesc: `Tỷ lệ ngày không có đơn trong 90 ngày: ${(Number(evidence.zero_rate_90d || 0) * 100).toFixed(1)}%.`,
        impactText: 'Tín hiệu chính', severity: 'amber'
      },
      HIGH_ZERO_SALES_RATE: {
        label: 'Tỷ lệ ngày không có đơn cao',
        subDesc: `Tỷ lệ ngày không có đơn trong 90 ngày: ${(Number(evidence.zero_rate_90d || 0) * 100).toFixed(1)}%.`,
        impactText: 'Tín hiệu hỗ trợ', severity: 'amber'
      },
      NO_SALES_LAST_30D: {
        label: 'Không phát sinh doanh số gần đây',
        subDesc: 'Odoo chưa ghi nhận sản lượng bán trong 30 ngày gần nhất.',
        impactText: 'Quy tắc vận hành', severity: 'red'
      },
      LONG_TIME_SINCE_LAST_SALE: {
        label: 'Khoảng cách từ lần bán gần nhất kéo dài',
        subDesc: `Đã ${dslsDays} ngày kể từ lần bán gần nhất theo dữ liệu Odoo.`,
        impactText: 'Quy tắc vận hành', severity: 'red'
      },
      MONITOR_SALES_VELOCITY: {
        label: 'Theo dõi tốc độ tiêu thụ',
        subDesc: `Tốc độ ghi nhận: ${velocity} sản phẩm/ngày.`,
        impactText: 'Quy tắc vận hành', severity: 'emerald'
      }
    };

    const factors = uniqueSignals.map((signal) => descriptions[signal]).filter(Boolean) as Array<Pick<ShapFactorItem, 'label' | 'subDesc' | 'impactText' | 'severity'>>;
    if (factors.length === 0) {
      return [{
        label: 'Chưa có tín hiệu chẩn đoán chi tiết',
        subDesc: 'Pipeline chưa cung cấp danh sách tín hiệu giải thích cho bản ghi này.',
        impactText: 'Chưa xác định', score: 0, pct: 0, severity: 'emerald'
      }];
    }
    return factors.map((factor) => ({ ...factor, score: 0, pct: 0 }));
  }

  get filteredItems(): SkuRiskItem[] {
    return this.items;
  }

  exportReport(format: 'csv' | 'excel' = 'csv'): void {
    const headers = ['Mã sản phẩm', 'Tên sản phẩm', 'Danh mục', 'Mức rủi ro', 'Xác suất rủi ro (%)', 'Số ngày tồn kho (DSLS)', 'Giá trị vốn tồn đọng (VND)', 'Tín hiệu tiêu thụ', 'Đánh giá mô hình'];
    const rows = this.filteredItems.map(item => [
      item.sku,
      `"${item.name.replace(/"/g, '""')}"`,
      `"${(item.category || 'Thiết bị & Phụ kiện').replace(/"/g, '""')}"`,
      item.riskClass === 'CRITICAL' ? 'Rủi ro rất cao' : (item.riskClass === 'HIGH_RISK' ? 'Rủi ro cao' : (item.riskClass === 'MEDIUM_RISK' ? 'Cần theo dõi' : 'Rủi ro thấp')),
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
    return this.riskSummary.total_skus;
  }

  get highRiskCount(): number {
    return this.riskSummary.high_risk;
  }

  get criticalCount(): number {
    return this.riskSummary.critical;
  }

  get mediumRiskCount(): number {
    return this.riskSummary.medium_risk;
  }

  get watchCount(): number {
    return this.mediumRiskCount;
  }

  get lowRiskCount(): number {
    return this.riskSummary.low_risk;
  }

  get safeCount(): number {
    return this.lowRiskCount;
  }

  setFilter(filter: string): void {
    this.selectedRiskFilter = filter;
    this.loadRealAssessments(true);
  }

  onFiltersChanged(): void {
    this.loadRealAssessments(true);
  }

  changePage(nextPage: number): void {
    if (nextPage < 1 || nextPage > this.totalPages || nextPage === this.page) return;
    this.page = nextPage;
    this.loadRealAssessments();
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pageStart(): number {
    return this.totalItems === 0 ? 0 : (this.page - 1) * this.pageSize + 1;
  }

  get pageEnd(): number {
    return Math.min(this.page * this.pageSize, this.totalItems);
  }

  trackBySku(_: number, item: SkuRiskItem): string {
    return item.sku;
  }

  getPatternLabel(pattern?: string): string {
    if (!pattern) return 'Chưa xác định';
    const lower = pattern.toLowerCase();
    if (lower.includes('smooth')) return 'Bán đều đặn';
    if (lower.includes('intermittent')) return 'Bán không liên tục';
    if (lower.includes('erratic')) return 'Bán biến động';
    if (lower.includes('lumpy')) return 'Bán gián đoạn';
    return pattern;
  }

  navigateToCapitalExposure(): void {
    this.closeDrawer();
    this.navigateTo.emit('capital-exposure');
    this.router.navigate(['/app/capital'], { queryParams: this.sourceQuery() });
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
    if (targetStage === 'capital-exposure') this.router.navigate(['/app/capital'], { queryParams: this.sourceQuery() });
    else if (targetStage === 'decision-support') this.router.navigate(['/app/decisions']);
    else if (targetStage === 'executive-dashboard') this.router.navigate(['/app/dashboard']);
  }

  private sourceQuery(extra: Record<string, string> = {}): Record<string, string> {
    return this.sourceMode === 'ODOO'
      ? { ...extra, source: 'odoo', connection: this.selectedOdooConnectionId }
      : extra;
  }
}
