import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';
import { forkJoin } from 'rxjs';

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
  sourceMode: 'CSV' | 'ODOO' = 'CSV';
  odooConnections: any[] = [];
  selectedOdooConnectionId = '';
  sourceMetadata: any = null;
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
    affectedSkus: '0'
  };

  riskDistribution: any[] = [];
  agingDistribution: any[] = [];
  skuItems: CapitalSkuItem[] = [];
  dataState: 'loading' | 'pending' | 'ready' | 'empty' | 'error' = 'loading';
  loadError = '';
  tableLoading = false;
  analysisId = '';
  pendingDescription = 'Bộ dữ liệu đã được nạp; hệ thống đang tạo bản tổng hợp phục vụ dashboard.';
  pageSize = 50;
  page = 1;
  totalItems = 0;
  private capitalAnalysisRequested = false;
  private capitalPollAttempts = 0;
  private capitalPollingTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly capitalPollDelayMs = 3000;
  private readonly maxCapitalPollAttempts = 20;
  riskCounts = {
    CRITICAL: 0,
    HIGH_RISK: 0,
    MEDIUM_RISK: 0,
    LOW_RISK: 0,
  };

  constructor(
    private apiService: ApiService,
    private router: Router,
    private route: ActivatedRoute,
  ) {}

  formatCurrencyShort(val: number | null | undefined): string {
    if (!val || val === 0) return '0';
    if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)}B`;
    if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `${(val / 1000).toFixed(1)}K`;
    return `${Math.round(val)}`;
  }

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('source') === 'odoo') {
      this.sourceMode = 'ODOO';
      this.selectedOdooConnectionId = this.route.snapshot.queryParamMap.get('connection') || '';
    }
    this.loadOdooSources();
    this.loadRealCapitalExposureData();
  }

  loadRealCapitalExposureData(): void {
    this.stopCapitalPolling();
    this.capitalAnalysisRequested = false;
    this.capitalPollAttempts = 0;
    this.dataState = 'loading';
    this.loadError = '';
    this.analysisId = '';
    this.skuItems = [];
    this.sourceMetadata = null;
    if (this.sourceMode === 'ODOO') {
      if (!this.selectedOdooConnectionId) {
        this.setEmptyDataState();
        return;
      }
      this.apiService.getOperationalCapitalAnalysis(this.selectedOdooConnectionId).subscribe({
        next: (res: any) => {
          this.sourceMetadata = res?.source || null;
          this.analysisId = res.analysis_id;
          this.page = 1;
          this.loadSummaryAndPage();
        },
        error: (err: any) => {
          const payload = err?.error || {};
          this.sourceMetadata = payload?.source || null;
          if (payload?.code === 'ODOO_OPERATIONAL_ANALYSIS_PENDING') {
            this.dataState = 'pending';
            this.pendingDescription = payload?.detail || 'Đang chờ đồng bộ Odoo hoặc xác nhận liên kết SKU.';
            return;
          }
          this.setErrorDataState(payload?.detail || payload?.error || 'Không thể tải bản phân tích Odoo.');
        },
      });
      return;
    }
    this.apiService.getLatestCapitalExposureAnalysis().subscribe({
      next: (res: any) => {
        if (res && res.analysis_id) {
          this.stopCapitalPolling();
          this.analysisId = res.analysis_id;
          this.page = 1;
          this.loadSummaryAndPage();
        } else {
          this.setEmptyDataState();
        }
      },
      error: (err: any) => {
        if (err?.error?.code === 'CAPITAL_ANALYSIS_PENDING') {
          this.dataState = 'pending';
          this.requestCapitalAnalysis();
          return;
        }
        this.setErrorDataState(err?.error?.detail || err?.error?.error || 'Không thể tải dữ liệu đánh giá vốn đọng. Vui lòng thử lại.');
      }
    });
  }

  private loadOdooSources(): void {
    this.apiService.listIntegrationConnections().subscribe({
      next: (response: any) => {
        this.odooConnections = (response?.connections || []).filter((connection: any) => connection.status === 'ACTIVE');
      },
      error: () => { this.odooConnections = []; },
    });
  }

  onSourceChanged(): void {
    if (this.sourceMode === 'ODOO' && !this.selectedOdooConnectionId) {
      this.selectedOdooConnectionId = this.odooConnections[0]?.id || '';
    }
    this.selectedRiskFilter = '';
    this.searchTerm = '';
    this.loadRealCapitalExposureData();
  }

  get selectedOdooConnectionName(): string {
    return this.odooConnections.find(connection => connection.id === this.selectedOdooConnectionId)?.display_name || 'Odoo';
  }

  private requestCapitalAnalysis(): void {
    if (this.capitalAnalysisRequested) return;

    this.capitalAnalysisRequested = true;
    this.pendingDescription = 'Đang khởi tạo bản phân tích vốn từ bộ dữ liệu hiện hành.';
    this.apiService.createCapitalExposureAnalysis().subscribe({
      next: (res: any) => {
        if (res?.analysis_id) {
          this.stopCapitalPolling();
          this.analysisId = res.analysis_id;
          this.page = 1;
          this.loadSummaryAndPage();
          return;
        }
        this.pendingDescription = 'Bản phân tích vốn đang được chuẩn bị. Trang sẽ tự cập nhật khi hoàn tất.';
        this.scheduleCapitalPoll();
      },
      error: (err: any) => {
        this.setErrorDataState(
          err?.error?.detail || err?.error?.error ||
          'Không thể khởi tạo bản phân tích vốn. Vui lòng thử lại.'
        );
      }
    });
  }

  private scheduleCapitalPoll(): void {
    this.stopCapitalPolling();
    if (this.capitalPollAttempts >= this.maxCapitalPollAttempts) {
      this.setErrorDataState(
        'Bản phân tích vốn chưa hoàn tất trong thời gian chờ. Vui lòng thử lại hoặc kiểm tra trạng thái xử lý dữ liệu.'
      );
      return;
    }

    this.capitalPollingTimer = setTimeout(() => {
      this.capitalPollAttempts += 1;
      this.apiService.getLatestCapitalExposureAnalysis().subscribe({
        next: (res: any) => {
          if (res?.analysis_id) {
            this.stopCapitalPolling();
            this.analysisId = res.analysis_id;
            this.page = 1;
            this.loadSummaryAndPage();
            return;
          }
          this.scheduleCapitalPoll();
        },
        error: (err: any) => {
          if (err?.error?.code === 'CAPITAL_ANALYSIS_PENDING') {
            this.scheduleCapitalPoll();
            return;
          }
          this.setErrorDataState(
            err?.error?.detail || err?.error?.error ||
            'Không thể kiểm tra trạng thái phân tích vốn. Vui lòng thử lại.'
          );
        }
      });
    }, this.capitalPollDelayMs);
  }

  private stopCapitalPolling(): void {
    if (this.capitalPollingTimer !== null) {
      clearTimeout(this.capitalPollingTimer);
      this.capitalPollingTimer = null;
    }
  }

  private loadSummaryAndPage(): void {
    if (!this.analysisId) return;
    forkJoin({
      summary: this.apiService.getCapitalExposureSummary(this.analysisId),
      page: this.apiService.listCapitalExposureItems(this.analysisId, this.buildListParams()),
    }).subscribe({
      next: ({ summary, page }: any) => {
        this.processSummary(summary);
        this.processPageItems(page?.items || []);
        this.totalItems = Number(page?.pagination?.total_items || 0);
        this.dataState = this.totalItems > 0 || this.hasActiveFilters() ? 'ready' : 'empty';
        this.tableLoading = false;
      },
      error: (err: any) => {
        this.tableLoading = false;
        this.setErrorDataState(err?.error?.detail || 'Không thể tải danh mục đánh giá vốn. Vui lòng thử lại.');
      }
    });
  }

  private loadPage(resetPage: boolean = false): void {
    if (!this.analysisId) return;
    if (resetPage) this.page = 1;
    this.tableLoading = true;
    this.loadSummaryAndPage();
  }

  private buildListParams(): Record<string, string | number> {
    const params: Record<string, string | number> = {
      page: this.page,
      limit: this.pageSize,
      sort: this.serverSort(),
    };
    if (this.selectedRiskFilter) params['risk_level'] = this.selectedRiskFilter;
    if (this.searchTerm.trim()) params['search'] = this.searchTerm.trim();
    if (this.capitalFilter) params['capital_band'] = this.capitalFilter;
    return params;
  }

  private serverSort(): string {
    const fields: Record<string, string> = {
      capitalExposureVal: 'capital_exposure',
      opportunityCostVal: 'estimated_opportunity_cost',
      dslsDays: 'aging_days',
    };
    const field = fields[this.sortField] || 'risk_weighted_exposure';
    return this.sortDirection === 'desc' ? `-${field}` : field;
  }

  private hasActiveFilters(): boolean {
    return Boolean(this.selectedRiskFilter || this.searchTerm.trim() || this.capitalFilter || this.agingFilter);
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
      affectedSkus: '0'
    };
    this.riskDistribution = [];
    this.agingDistribution = [];
  }

  private setErrorDataState(message: string): void {
    this.dataState = 'error';
    this.loadError = message;
    this.skuItems = [];
    this.summaryGrid = { totalExposure: '0', highRiskExposure: '0', opportunityCost: '0', affectedSkus: '0' };
    this.riskDistribution = [];
    this.agingDistribution = [];
  }

  private processPageItems(itemsList: any[]): void {
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
  }

  private processSummary(response: any): void {
    const summary = response?.summary || {};
    const totalVal = Number(summary.total_inventory_value || 0);
    const riskRows = Array.isArray(response?.risk_distribution) ? response.risk_distribution : [];
    const agingRows = Array.isArray(response?.aging_distribution) ? response.aging_distribution : [];
    const byRisk = new Map<string, any>(riskRows.map((row: any) => [String(row.group || '').toUpperCase(), row]));
    const byAging = new Map<string, any>(agingRows.map((row: any) => [String(row.group || '').toUpperCase(), row]));
    const highRiskValue = ['CRITICAL', 'HIGH_RISK'].reduce(
      (total, key) => total + Number(byRisk.get(key)?.inventory_value || 0),
      0,
    );
    this.riskCounts = {
      CRITICAL: Number(byRisk.get('CRITICAL')?.sku_count || 0),
      HIGH_RISK: Number(byRisk.get('HIGH_RISK')?.sku_count || 0),
      MEDIUM_RISK: Number(byRisk.get('MEDIUM_RISK')?.sku_count || 0),
      LOW_RISK: Number(byRisk.get('LOW_RISK')?.sku_count || 0),
    };
    this.summaryGrid = {
      totalExposure: this.formatCurrencyShort(totalVal),
      highRiskExposure: this.formatCurrencyShort(highRiskValue),
      opportunityCost: this.formatCurrencyShort(Number(summary.total_opportunity_cost || 0)),
      affectedSkus: `${this.riskCounts.CRITICAL + this.riskCounts.HIGH_RISK}`
    };
    const calcSharePct = (val: number) => totalVal > 0 ? Math.round((val / totalVal) * 100) : 0;
    const makeRiskRow = (key: string, label: string, color: string, badgeClass: string) => {
      const row: any = byRisk.get(key) || {};
      const value = Number(row.inventory_value || 0);
      return { label, exposure: this.formatCurrencyShort(value), sharePct: calcSharePct(value), count: Number(row.sku_count || 0), color, badgeClass };
    };
    this.riskDistribution = [
      makeRiskRow('CRITICAL', 'Rủi ro rất cao', 'bg-rose-700', 'bg-rose-50 text-rose-800 border-rose-200'),
      makeRiskRow('HIGH_RISK', 'Rủi ro cao', 'bg-rose-500', 'bg-rose-50 text-rose-700 border-rose-200'),
      makeRiskRow('MEDIUM_RISK', 'Cần theo dõi', 'bg-amber-500', 'bg-amber-50 text-amber-700 border-amber-200'),
      makeRiskRow('LOW_RISK', 'An toàn', 'bg-emerald-500', 'bg-emerald-50 text-emerald-700 border-emerald-200'),
    ];
    const makeAgingRow = (key: string, label: string, desc: string, color: string) => {
      const row: any = byAging.get(key) || {};
      const value = Number(row.inventory_value || 0);
      return { label, exposure: this.formatCurrencyShort(value), sharePct: calcSharePct(value), count: Number(row.sku_count || 0), color, desc };
    };
    this.agingDistribution = [
      makeAgingRow('FRESH', 'Lưu kho ngắn hạn', 'Hàng lưu thông trong ngưỡng theo dõi.', 'bg-emerald-500'),
      makeAgingRow('AGING', 'Cần theo dõi', 'Có dấu hiệu lưu kho kéo dài.', 'bg-amber-500'),
      makeAgingRow('AT_RISK', 'Tồn kho có rủi ro', 'Cần đánh giá phương án xúc tiến phù hợp.', 'bg-amber-600'),
      makeAgingRow('CRITICAL_AGING', 'Lưu kho kéo dài', 'Ưu tiên đánh giá phương án thu hồi vốn.', 'bg-rose-500'),
    ];
  }

  get totalCount(): number {
    return this.riskCounts.CRITICAL + this.riskCounts.HIGH_RISK + this.riskCounts.MEDIUM_RISK + this.riskCounts.LOW_RISK;
  }

  get highRiskCount(): number {
    return this.riskCounts.CRITICAL + this.riskCounts.HIGH_RISK;
  }

  get criticalCount(): number {
    return this.riskCounts.CRITICAL;
  }

  get watchCount(): number {
    return this.riskCounts.MEDIUM_RISK;
  }

  get safeCount(): number {
    return this.riskCounts.LOW_RISK;
  }

  get filteredSkuItems(): CapitalSkuItem[] {
    return this.skuItems;
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
    this.loadPage(true);
  }

  onFiltersChanged(): void {
    this.loadPage(true);
  }

  changePage(nextPage: number): void {
    if (nextPage < 1 || nextPage > this.totalPages || nextPage === this.page) return;
    this.page = nextPage;
    this.loadPage();
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

  trackBySku(_: number, item: CapitalSkuItem): string {
    return item.sku;
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
    this.stopCapitalPolling();
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
