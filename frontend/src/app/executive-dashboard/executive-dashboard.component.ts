import {
  Component,
  OnInit,
  OnChanges,
  AfterViewInit,
  OnDestroy,
  Input,
  Output,
  EventEmitter,
  ElementRef,
  ViewChild,
  HostListener,
  SimpleChanges
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

declare var echarts: any;

export interface TopPrioritySku {
  sku: string;
  capitalExposure: string; // e.g. "93.8M"
  riskLevel: 'HIGH_RISK';
  badgeClass: string;
}

@Component({
  selector: 'app-executive-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './executive-dashboard.component.html',
  styleUrls: ['./executive-dashboard.component.css']
})
export class ExecutiveDashboardComponent implements OnInit, OnChanges, AfterViewInit, OnDestroy {
  @Input() data: any = null;
  @Input() sessionId: string = '';
  @Input() loading: boolean = false;

  @Output() analyzeSku = new EventEmitter<string>();
  @Output() navigateTo = new EventEmitter<string>();
  @Output() navigateToRiskAnalysis = new EventEmitter<void>();

  @ViewChild('donutChartRef') set donutRef(ref: ElementRef<HTMLDivElement> | undefined) {
    if (ref) {
      this.donutChartRef = ref;
      setTimeout(() => this.initDonutChart(), 50);
    }
  }

  @ViewChild('priorityChartRef') set priorityRef(ref: ElementRef<HTMLDivElement> | undefined) {
    if (ref) {
      this.priorityChartRef = ref;
      setTimeout(() => this.initPriorityChart(), 50);
    }
  }

  @ViewChild('riskCapitalChartRef') set riskCapitalRef(ref: ElementRef<HTMLDivElement> | undefined) {
    if (ref) {
      this.riskCapitalChartRef = ref;
      setTimeout(() => this.initRiskCapitalChart(), 50);
    }
  }

  donutChartRef!: ElementRef<HTMLDivElement>;
  priorityChartRef!: ElementRef<HTMLDivElement>;
  riskCapitalChartRef!: ElementRef<HTMLDivElement>;
  private donutChartInstance: any = null;
  private priorityChartInstance: any = null;
  private riskCapitalChartInstance: any = null;

  isRefreshing: boolean = false;
  viewState: 'loading' | 'ready' | 'empty' | 'error' = 'loading';
  loadError = '';

  // Color Coding Constants (Strict Compliance)
  readonly COLOR_SAFE = '#22C55E';     // Green-500
  readonly COLOR_WATCH = '#EAB308';    // Yellow-500
  readonly COLOR_HIGH_RISK = '#EF4444';// Red-500

  // 1. DASH-001: Shop Health Summary Direct Answer State ("Shop đang thế nào?")
  shopHealthSummary = {
    statusBadge: 'ĐANG TẢI...',
    statusLevel: 'LOADING',
    verdictTitle: 'Đang hệ thống hóa dữ liệu kho hàng...',
    verdictMessage: 'Hệ thống đang tính toán tổng hợp chỉ số tồn kho, phân nhóm rủi ro và giá trị vốn đọng.',
    takeaways: [
      'Đang kiểm tra chỉ số quay vòng vốn.',
      'Đang xác định danh sách sản phẩm ưu tiên.',
      'Đang tính toán khả năng giải phóng dòng tiền.'
    ]
  };

  // 2. DASH-002: Exact 5 Required KPI Metrics (100% Plain Friendly Vietnamese)
  kpiGrid = {
    monitoredSkus: '0 sản phẩm',
    highRiskSkus: '0 sản phẩm',
    totalCapitalExposure: '0 VNĐ',
    atRiskCapital: '0 VNĐ',
    agedCapital: '0 VNĐ',
    safePct: '0%',
    needActionPct: '0%'
  };

  // 3. DASH-003: Drill Down Flow Steps (Overview → Risk → Explanation → Capital → Decision)
  drillDownSteps = [
    { step: 1, label: '1. Tổng quan', description: 'Cửa hàng thế nào', stage: 'dashboard', active: true },
    { step: 2, label: '2. Cảnh báo rủi ro', description: 'Hàng chậm bán', stage: 'slow-moving-risk', active: false },
    { step: 3, label: '3. Nguyên nhân', description: 'Lý do bị tồn đọng', stage: 'slow-moving-risk', active: false },
    { step: 4, label: '4. Đánh giá vốn đọng', description: 'Thiệt hại dòng tiền', stage: 'capital-exposure', active: false },
    { step: 5, label: '5. Phương án xử lý', description: 'Đề xuất & theo dõi', stage: 'decision-support', active: false }
  ];

  // Risk Distribution Data (For Donut Chart & Text List)
  riskBreakdown = [
    { label: 'Rủi ro rất cao', pct: '0%', value: 0, color: '#B91C1C' },
    { label: 'Rủi ro cao', pct: '0%', value: 0, color: '#E25555' },
    { label: 'Cần theo dõi', pct: '0%', value: 0, color: '#D97706' },
    { label: 'Rủi ro thấp', pct: '0%', value: 0, color: '#059669' }
  ];

  // Top 3 Priorities List (Today's Priorities)
  topPriorities: TopPrioritySku[] = [];
  topRiskChartData: Array<{
    sku: string;
    name: string;
    capitalExposureVnd: number;
    daysInInventory: number;
    riskClass: string;
  }> = [];
  riskCapitalChartData: Array<{
    label: string;
    value: number;
    color: string;
  }> = [];

  // Attention Notice State
  attentionNotice = {
    highRiskCountText: '0 sản phẩm',
    slowCountText: '0 sản phẩm',
    deadCountText: '0 sản phẩm'
  };

  constructor(
    private apiService: ApiService,
    private dashboardState: DashboardStateService,
    private router: Router
  ) {}

  get hasRiskCapitalChartData(): boolean {
    return this.riskCapitalChartData.some(item => item.value > 0);
  }

  ngOnInit(): void {
    // Do not render a client-side cache before the backend confirms that it
    // belongs to the currently active dataset.
    this.fetchDashboardData();
  }

  formatVndHuman(amount: number): string {
    if (!amount || amount === 0) return '0 VNĐ';
    if (amount >= 1_000_000_000) {
      return (amount / 1_000_000_000).toFixed(1) + ' Tỷ VNĐ';
    }
    if (amount >= 1_000_000) {
      return (amount / 1_000_000).toFixed(1) + ' Triệu VNĐ';
    }
    if (amount >= 1_000) {
      return (amount / 1_000).toFixed(0) + ' K VNĐ';
    }
    return amount.toLocaleString('vi-VN') + ' VNĐ';
  }

  fetchDashboardData(): void {
    this.loading = true;
    this.viewState = 'loading';
    this.loadError = '';
    this.data = null;
    this.apiService.getExecutiveDashboardSummaryCached().subscribe({
      next: (summary: any) => {
        this.isRefreshing = false;
        if (summary && summary.hasData) {
          this.loading = false;
          this.kpiGrid = {
            monitoredSkus: `${summary.totalSkus} sản phẩm`,
            highRiskSkus: `${summary.criticalCount + summary.highRiskCount} sản phẩm`,
            totalCapitalExposure: this.formatVndHuman(summary.totalCapitalExposureVnd),
            atRiskCapital: this.formatVndHuman(summary.atRiskCapitalVnd),
            agedCapital: this.formatVndHuman(summary.agedCapitalVnd),
            safePct: `${Math.round(((summary.lowRiskCount || 0) / (summary.totalSkus || 1)) * 100)}%`,
            needActionPct: `${Math.round((((summary.criticalCount || 0) + (summary.highRiskCount || 0)) / (summary.totalSkus || 1)) * 100)}%`
          };

          const atRiskVal = summary.atRiskCapitalVnd || 0;
          const agedVal = summary.agedCapitalVnd || 0;
          const highRiskCount = summary.criticalCount + summary.highRiskCount;
          const highRiskPctVal = Math.round((highRiskCount / (summary.totalSkus || 1)) * 100);
          const topSkusNames = (summary.topRiskSkus || []).slice(0, 3).map((s: any) => s.name);

          this.shopHealthSummary = {
            statusBadge: highRiskCount > 0 ? 'CẦN ƯU TIÊN XỬ LÝ' : 'VẬN HÀNH ỔN ĐỊNH',
            statusLevel: highRiskCount > 0 ? 'HIGH_RISK' : 'SAFE',
            verdictTitle: highRiskCount > 0 ? `Danh mục có ${highRiskCount} SKU thuộc nhóm rủi ro vốn cao` : 'Danh mục đang vận hành ổn định',
            verdictMessage: highRiskCount > 0 ? `Có ${highRiskCount} SKU rủi ro cao với ${this.formatVndHuman(atRiskVal)} giá trị vốn cần được ưu tiên đánh giá. Trong đó, ${this.formatVndHuman(agedVal)} thuộc nhóm lưu kho trên 90 ngày.` : 'Danh mục đang duy trì tốc độ tiêu thụ phù hợp, chưa ghi nhận giá trị tồn kho lưu kho kéo dài đáng kể.',
            takeaways: [
              `Cần ưu tiên lập phương án xử lý cho ${highRiskPctVal}% số sản phẩm bán chậm (${highRiskCount} SKU).`,
              topSkusNames.length > 0 ? `Ưu tiên xử lý ${topSkusNames.length} mặt hàng chiếm vốn lớn nhất (${topSkusNames.join(', ')}).` : `Ưu tiên xử lý các sản phẩm có giá trị tồn đọng cao nhất.`,
              `Lập phương án xử lý riêng trước khi áp dụng điều chỉnh giá hoặc giải phóng tồn kho.`
            ]
          };

          const totSkus = summary.totalSkus || 1;
          const criticalPct = Math.round(((summary.criticalCount || 0) / totSkus) * 100);
          const highPct = Math.round(((summary.highRiskCount || 0) / totSkus) * 100);
          const medPct = Math.round(((summary.mediumRiskCount || 0) / totSkus) * 100);
          const lowPct = Math.round(((summary.lowRiskCount || 0) / totSkus) * 100);

          this.riskBreakdown = [
            { label: 'Rủi ro rất cao', pct: `${criticalPct}%`, value: summary.criticalCount || 0, color: '#B91C1C' },
            { label: 'Rủi ro cao', pct: `${highPct}%`, value: summary.highRiskCount || 0, color: '#E25555' },
            { label: 'Cần theo dõi', pct: `${medPct}%`, value: summary.mediumRiskCount || 0, color: '#D97706' },
            { label: 'Rủi ro thấp', pct: `${lowPct}%`, value: summary.lowRiskCount || 0, color: '#059669' }
          ];

          this.attentionNotice = {
            highRiskCountText: `${(summary.criticalCount || 0) + (summary.highRiskCount || 0)} sản phẩm`,
            slowCountText: `${summary.criticalCount || 0} sản phẩm`,
            deadCountText: `${summary.agedSkuCount || 0} sản phẩm`
          };

          this.topPriorities = (summary.topRiskSkus || []).slice(0, 3).map((s: any) => ({
            sku: s.sku,
            capitalExposure: this.formatVndHuman(s.capitalExposureVnd),
            riskLevel: 'HIGH_RISK',
            badgeClass: 'badge-danger'
          }));
          this.topRiskChartData = (summary.topRiskSkus || []).slice(0, 5).map((sku: any) => ({
            sku: sku.sku || 'SKU chưa xác định',
            name: sku.name || sku.sku || 'Sản phẩm chưa xác định',
            capitalExposureVnd: Number(sku.capitalExposureVnd || 0),
            daysInInventory: Number(sku.daysInInventory || 0),
            riskClass: sku.riskClass || 'HIGH_RISK'
          }));
          this.setRiskCapitalChartData(summary.riskCapitalByClassVnd);
          this.dashboardState.setHasData(true);
          this.viewState = 'ready';
          setTimeout(() => {
            this.initDonutChart();
            this.initPriorityChart();
            this.initRiskCapitalChart();
          }, 50);
        } else {
          this.setEmptyDashboardState();
        }
      },
      error: (err: any) => {
        this.isRefreshing = false;
        this.setDashboardError(err?.error?.error || 'Không thể tải dữ liệu tổng quan. Vui lòng thử lại.');
      }
    });
  }

  goToImport(): void {
    this.router.navigate(['/app/import']);
  }

  private setEmptyDashboardState(): void {
    this.loading = false;
    this.viewState = 'empty';
    this.dashboardState.reset();
    this.kpiGrid = {
      monitoredSkus: '0 sản phẩm', highRiskSkus: '0 sản phẩm', totalCapitalExposure: '0 VNĐ',
      atRiskCapital: '0 VNĐ', agedCapital: '0 VNĐ', safePct: '0%', needActionPct: '0%'
    };
    this.topPriorities = [];
    this.topRiskChartData = [];
    this.riskCapitalChartData = [];
    this.riskBreakdown = [
      { label: 'Rủi ro rất cao', pct: '0%', value: 0, color: '#B91C1C' },
      { label: 'Rủi ro cao', pct: '0%', value: 0, color: '#E25555' },
      { label: 'Cần theo dõi', pct: '0%', value: 0, color: '#D97706' },
      { label: 'Rủi ro thấp', pct: '0%', value: 0, color: '#059669' }
    ];
  }

  private setDashboardError(message: string): void {
    this.loading = false;
    this.viewState = 'error';
    this.loadError = message;
    this.data = null;
  }

  private processDashboardResponse(
    res: any,
    healthyList: any[],
    watchlistList: any[],
    slowList: any[],
    deadList: any[],
    allSkus: any[]
  ): void {
    const healthyVal = res.totalHealthyValue || 0;
    const watchlistVal = res.totalWatchlistValue || 0;
    const slowVal = res.totalSlowMovingValue || 0;
    const deadVal = res.totalDeadStockValue || 0;
    const totalInvVal = healthyVal + watchlistVal + slowVal + deadVal;

    let topStale = [...deadList, ...slowList].map((item: any) => ({
      sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
      name: item.name || item.product_name || 'SKU Sản phẩm',
      frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
      lastRecordDate: item.lastRecordDate || 'N/A'
    })).sort((a, b) => b.frozenValueVnd - a.frozenValueVnd).slice(0, 5);

    if (topStale.length === 0 && allSkus.length > 0) {
      topStale = allSkus.map((item: any) => ({
        sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
        name: item.name || item.product_name || 'SKU Sản phẩm',
        frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
        lastRecordDate: item.lastRecordDate || 'N/A'
      })).sort((a, b) => b.frozenValueVnd - a.frozenValueVnd).slice(0, 5);
    }

    const finalDeadStockValue = deadVal + slowVal;
    const finalStaleCount = deadList.length + slowList.length;
    const finalBleedingRate = res.totalBleedingRateMonthly || 0;

    this.data = {
      hasData: allSkus.length > 0,
      ...res,
      totalDeadStockValueVnd: finalDeadStockValue,
      staleSkuCount: finalStaleCount,
      estimatedLoss30DaysVnd: finalBleedingRate,
      totalInventoryValueVnd: totalInvVal,
      totalRootSkuCount: allSkus.length,
      topStaleSkus: topStale
    };
    this.dashboardState.setDashboardData(this.data);
    this.updateDashboardFromData();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['data']) {
      this.updateDashboardFromData();
    }
    if (this.donutChartInstance) {
      this.initDonutChart();
    }
    if (this.priorityChartInstance) {
      this.initPriorityChart();
    }
    if (this.riskCapitalChartInstance) {
      this.initRiskCapitalChart();
    }
  }

  updateDashboardFromData(): void {
    if (!this.data) return;

    const healthyList = this.data.healthySkus || [];
    const watchList = this.data.watchlistSkus || [];
    const slowList = this.data.slowMovingSkus || [];
    const deadList = this.data.deadStockSkus || [];

    const safeCount = healthyList.length;
    const watchCount = watchList.length;
    const slowCount = slowList.length;
    const deadCount = deadList.length;
    const highRiskCount = slowCount + deadCount;
    const totalCount = safeCount + watchCount + highRiskCount;

    this.attentionNotice = {
      highRiskCountText: `${highRiskCount} sản phẩm`,
      slowCountText: `${deadCount} sản phẩm`,
      deadCountText: `${deadCount} sản phẩm`
    };

    const formatVndHuman = (val: number): string => {
      if (!val || val === 0) return '0 VNĐ';
      if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)} Tỷ VNĐ`;
      if (val >= 1000000) return `${(val / 1000000).toFixed(1)} Triệu VNĐ`;
      if (val >= 1000) return `${(val / 1000).toFixed(0)} Nghìn VNĐ`;
      return `${Math.round(val).toLocaleString('vi-VN')} VNĐ`;
    };

    if (totalCount > 0) {
      const safePctVal = Math.round((safeCount / totalCount) * 100);
      const watchPctVal = Math.round((watchCount / totalCount) * 100);
      const highRiskPctVal = Math.max(0, 100 - safePctVal - watchPctVal);

      // Sum exact inventory values directly from data lists (no fixed magic numbers)
      const healthyVal = healthyList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0);
      const watchVal = watchList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0);
      const slowVal = slowList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0);
      const deadVal = deadList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0);

      const totalCapVnd = this.data.totalInventoryValueVnd || (healthyVal + watchVal + slowVal + deadVal);
      const atRiskVal = this.data.totalFrozenValue || (slowVal + deadVal);
      const agedVal = this.data.totalDeadStockValue || deadVal;

      const topStale = this.data.topStaleSkus || [];
      const topSkusNames = topStale.slice(0, 3).map((p: any) => p.sku || p.name).filter(Boolean);

      // DASH-002: Set exact 5 KPIs derived from real database
      this.kpiGrid = {
        monitoredSkus: `${totalCount} sản phẩm`,
        highRiskSkus: `${highRiskCount} sản phẩm`,
        totalCapitalExposure: formatVndHuman(totalCapVnd),
        atRiskCapital: formatVndHuman(atRiskVal),
        agedCapital: formatVndHuman(agedVal),
        safePct: `${safePctVal}%`,
        needActionPct: `${highRiskPctVal}%`
      };

      // DASH-001: Set Direct Shop Assessment Verdict ("Shop đang thế nào?")
      if (highRiskCount > 0) {
        const skuPriorityMessage = topSkusNames.length > 0
          ? `Ưu tiên xử lý ${topSkusNames.length} mặt hàng chiếm vốn lớn nhất (${topSkusNames.join(', ')}).`
          : `Ưu tiên xử lý các sản phẩm có giá trị tồn đọng cao nhất.`;

        this.shopHealthSummary = {
          statusBadge: 'CẦN ƯU TIÊN XỬ LÝ',
          statusLevel: 'HIGH_RISK',
          verdictTitle: `Danh mục có ${highRiskCount} SKU thuộc nhóm rủi ro vốn cao`,
          verdictMessage: `Có ${highRiskCount} SKU rủi ro cao với ${formatVndHuman(atRiskVal)} giá trị vốn cần được ưu tiên đánh giá. Trong đó, ${formatVndHuman(agedVal)} thuộc nhóm lưu kho trên 90 ngày. Cần đánh giá phương án xử lý phù hợp trước khi triển khai.`,
          takeaways: [
            `Cần ưu tiên lập phương án xử lý cho ${highRiskPctVal}% số sản phẩm bán chậm (${highRiskCount} SKU).`,
            skuPriorityMessage,
            `Lập phương án xử lý riêng trước khi áp dụng điều chỉnh giá hoặc giải phóng tồn kho.`
          ]
        };
      } else {
        this.shopHealthSummary = {
          statusBadge: 'VẬN HÀNH ỔN ĐỊNH',
          statusLevel: 'SAFE',
          verdictTitle: 'Danh mục đang vận hành ổn định',
          verdictMessage: 'Danh mục đang duy trì tốc độ tiêu thụ phù hợp, chưa ghi nhận giá trị tồn kho lưu kho kéo dài đáng kể.',
          takeaways: [
            'Dòng vốn quay vòng ổn định và lành mạnh.',
            'Tiếp tục theo dõi biến động sức mua của thị trường.',
            'Chưa cần áp dụng phương án chiết khấu hoặc xử lý tồn kho khẩn cấp.'
          ]
        };
      }

      this.riskBreakdown = [
        { label: 'Rủi ro rất cao', pct: `${Math.round((deadCount / totalCount) * 100)}%`, value: deadCount, color: '#B91C1C' },
        { label: 'Rủi ro cao', pct: `${Math.round((slowCount / totalCount) * 100)}%`, value: slowCount, color: this.COLOR_HIGH_RISK },
        { label: 'Cần theo dõi', pct: `${watchPctVal}%`, value: watchCount, color: this.COLOR_WATCH },
        { label: 'Rủi ro thấp', pct: `${safePctVal}%`, value: safeCount, color: this.COLOR_SAFE }
      ];
      this.setRiskCapitalChartData({
        CRITICAL: deadVal,
        HIGH_RISK: slowVal,
        MEDIUM_RISK: watchVal,
        LOW_RISK: healthyVal
      });

      if (topStale.length > 0) {
        this.topPriorities = topStale.slice(0, 3).map((item: any) => ({
          sku: item.name || item.sku || 'SKU Sản phẩm',
          capitalExposure: formatVndHuman(item.frozenValueVnd || item.totalValue || 0),
          riskLevel: 'HIGH_RISK',
          badgeClass: 'bg-rose-600 text-white'
        }));
      } else {
        this.topPriorities = [];
      }
    } else {
      this.kpiGrid = {
        monitoredSkus: '0 sản phẩm',
        highRiskSkus: '0 sản phẩm',
        totalCapitalExposure: '0 VNĐ',
        atRiskCapital: '0 VNĐ',
        agedCapital: '0 VNĐ',
        safePct: '0%',
        needActionPct: '0%'
      };
      this.shopHealthSummary = {
        statusBadge: '⚪ CHƯA CÓ DỮ LIỆU',
        statusLevel: 'EMPTY',
        verdictTitle: 'Chưa có thông tin dữ liệu sản phẩm',
        verdictMessage: 'Vui lòng nạp tệp CSV bán hàng để hệ thống đánh giá tình trạng kho và vốn đọng.',
        takeaways: [
          'Chưa có dữ liệu để đánh giá rủi ro.',
          'Vui lòng tải tệp CSV bán hàng.'
        ]
      };
      this.riskBreakdown = [
        { label: 'Chưa có dữ liệu', pct: '0%', value: 0, color: '#94A3B8' }
      ];
      this.topPriorities = [];
      this.riskCapitalChartData = [];
    }

    setTimeout(() => {
      this.initDonutChart();
      this.initRiskCapitalChart();
    }, 50);
  }

  ngAfterViewInit(): void {
    setTimeout(() => {
      this.initDonutChart();
      this.initRiskCapitalChart();
    }, 300);
  }

  ngOnDestroy(): void {
    this.disposeCharts();
  }

  @HostListener('window:resize')
  onResize(): void {
    if (this.donutChartInstance) this.donutChartInstance.resize();
    if (this.priorityChartInstance) this.priorityChartInstance.resize();
    if (this.riskCapitalChartInstance) this.riskCapitalChartInstance.resize();
  }

  private setRiskCapitalChartData(values: Record<string, unknown> | undefined): void {
    const amount = (key: string): number => {
      const value = Number(values?.[key] ?? 0);
      return Number.isFinite(value) && value > 0 ? value : 0;
    };
    this.riskCapitalChartData = [
      { label: 'Rủi ro rất cao', value: amount('CRITICAL'), color: '#B91C1C' },
      { label: 'Rủi ro cao', value: amount('HIGH_RISK'), color: '#E25555' },
      { label: 'Cần theo dõi', value: amount('MEDIUM_RISK'), color: '#D97706' },
      { label: 'Rủi ro thấp', value: amount('LOW_RISK'), color: '#059669' }
    ];
  }

  initDonutChart(): void {
    if (!this.donutChartRef || !this.donutChartRef.nativeElement) return;
    if (typeof echarts === 'undefined') return;

    if (this.donutChartInstance) {
      this.donutChartInstance.dispose();
    }

    this.donutChartInstance = echarts.init(this.donutChartRef.nativeElement);

    const option = {
      tooltip: {
        trigger: 'item',
        confine: true,
        appendToBody: true,
        backgroundColor: '#0F172A',
        borderColor: '#1E293B',
        borderWidth: 1,
        padding: [8, 12],
        textStyle: {
          color: '#FFFFFF',
          fontSize: 13,
          fontWeight: 600
        },
        extraCssText: 'z-index: 9999; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); border-radius: 10px; white-space: nowrap;',
        formatter: (params: any) => {
          return `<div style="display:flex;align-items:center;gap:8px;font-family:'Be Vietnam Pro',sans-serif;">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background-color:${params.color}"></span>
            <span style="color:#E2E8F0;font-weight:600;">${params.name}:</span>
            <span style="color:#FFFFFF;font-weight:800;font-family:'Be Vietnam Pro',sans-serif;font-size:14px;">${params.value} SKU (${params.data.pct})</span>
          </div>`;
        }
      },
      legend: {
        show: false
      },
      series: [
        {
          name: 'Tình Hình Rủi Ro',
          type: 'pie',
          radius: ['52%', '78%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: '#ffffff',
            borderWidth: 2
          },
          label: {
            show: false
          },
          emphasis: {
            scale: true,
            scaleSize: 6,
            label: {
              show: false
            }
          },
          data: this.riskBreakdown.map(b => ({
            value: b.value,
            name: b.label,
            pct: b.pct,
            itemStyle: { color: b.color }
          }))
        }
      ]
    };

    this.donutChartInstance.setOption(option);
  }

  initPriorityChart(): void {
    if (!this.priorityChartRef || !this.priorityChartRef.nativeElement || typeof echarts === 'undefined') return;

    if (this.priorityChartInstance) {
      this.priorityChartInstance.dispose();
    }

    this.priorityChartInstance = echarts.init(this.priorityChartRef.nativeElement);
    const rows = [...this.topRiskChartData].reverse();
    const formatCurrency = (value: number) => value.toLocaleString('vi-VN') + ' VNĐ';

    this.priorityChartInstance.setOption({
      animationDuration: 350,
      grid: { top: 12, right: 28, bottom: 28, left: 116, containLabel: false },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        confine: true,
        backgroundColor: '#0F172A',
        borderColor: '#1E293B',
        borderWidth: 1,
        textStyle: { color: '#FFFFFF', fontSize: 12 },
        formatter: (params: any[]) => {
          const item = params[0]?.data;
          if (!item) return '';
          return `<strong>${item.sku}</strong><br/>${item.name}<br/>Giá trị vốn có rủi ro: <strong>${formatCurrency(item.value)}</strong><br/>Số ngày chưa có giao dịch: ${item.daysInInventory}`;
        }
      },
      xAxis: {
        type: 'value',
        axisLabel: {
          color: '#64748B',
          fontSize: 10,
          formatter: (value: number) => this.formatVndHuman(value).replace(' VNĐ', '')
        },
        splitLine: { lineStyle: { color: '#E2E8F0' } }
      },
      yAxis: {
        type: 'category',
        data: rows.map(item => item.sku),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#334155', fontSize: 11, fontWeight: 700, width: 104, overflow: 'truncate' }
      },
      series: [{
        type: 'bar',
        barWidth: 18,
        borderRadius: [0, 6, 6, 0],
        data: rows.map(item => ({
          value: item.capitalExposureVnd,
          sku: item.sku,
          name: item.name,
          daysInInventory: item.daysInInventory,
          itemStyle: { color: item.riskClass === 'CRITICAL' ? '#B91C1C' : '#E25555' }
        }))
      }]
    });

    this.priorityChartInstance.on('click', (params: any) => {
      if (params?.data?.sku) this.onSelectSku(params.data.sku);
    });
  }

  initRiskCapitalChart(): void {
    if (!this.riskCapitalChartRef || !this.riskCapitalChartRef.nativeElement || typeof echarts === 'undefined') return;

    if (this.riskCapitalChartInstance) {
      this.riskCapitalChartInstance.dispose();
    }

    this.riskCapitalChartInstance = echarts.init(this.riskCapitalChartRef.nativeElement);
    const rows = [...this.riskCapitalChartData].reverse();
    const formatCurrency = (value: number) => value.toLocaleString('vi-VN') + ' VNĐ';

    this.riskCapitalChartInstance.setOption({
      animationDuration: 350,
      grid: { top: 12, right: 28, bottom: 28, left: 112, containLabel: false },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        confine: true,
        backgroundColor: '#0F172A',
        borderColor: '#1E293B',
        borderWidth: 1,
        textStyle: { color: '#FFFFFF', fontSize: 12 },
        formatter: (params: any[]) => {
          const item = params[0]?.data;
          return item ? `${item.label}<br/>Giá trị vốn: <strong>${formatCurrency(item.value)}</strong>` : '';
        }
      },
      xAxis: {
        type: 'value',
        axisLabel: {
          color: '#64748B',
          fontSize: 10,
          formatter: (value: number) => this.formatVndHuman(value).replace(' VNĐ', '')
        },
        splitLine: { lineStyle: { color: '#E2E8F0' } }
      },
      yAxis: {
        type: 'category',
        data: rows.map(item => item.label),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#334155', fontSize: 11, fontWeight: 700 }
      },
      series: [{
        type: 'bar',
        barWidth: 18,
        borderRadius: [0, 6, 6, 0],
        data: rows.map(item => ({
          ...item,
          itemStyle: { color: item.color }
        }))
      }]
    });

    this.riskCapitalChartInstance.on('click', () => this.onNavigateToStage('capital-exposure'));
  }

  disposeCharts(): void {
    if (this.donutChartInstance) {
      this.donutChartInstance.dispose();
      this.donutChartInstance = null;
    }
    if (this.priorityChartInstance) {
      this.priorityChartInstance.dispose();
      this.priorityChartInstance = null;
    }
    if (this.riskCapitalChartInstance) {
      this.riskCapitalChartInstance.dispose();
      this.riskCapitalChartInstance = null;
    }
  }

  refreshData(): void {
    this.isRefreshing = true;
    this.apiService.refreshExecutiveDashboardCache().subscribe({
      next: () => this.fetchDashboardData(),
      // Users without the cache-refresh permission can still reload their
      // latest accessible read model; the control must not strand the page.
      error: () => this.fetchDashboardData()
    });
  }

  onViewRiskAnalysisClick(): void {
    this.navigateTo.emit('slow-moving-risk');
    this.router.navigate(['/app/risk']);
  }

  onViewAllClick(): void {
    this.navigateTo.emit('slow-moving-risk');
    this.router.navigate(['/app/risk']);
  }

  onSelectSku(sku: string): void {
    this.analyzeSku.emit(sku);
    this.dashboardState.setSelectedSkuId(sku);
    this.router.navigate(['/app/risk'], { queryParams: { sku } });
  }

  onNavigateToStage(targetStage: string, sku?: string): void {
    if (sku) {
      this.dashboardState.setSelectedSkuId(sku);
      this.analyzeSku.emit(sku);
    }
    this.navigateTo.emit(targetStage);
    if (targetStage === 'slow-moving-risk') {
      this.router.navigate(['/app/risk'], sku ? { queryParams: { sku } } : {});
    } else if (targetStage === 'capital-exposure') {
      this.router.navigate(['/app/capital']);
    } else if (targetStage === 'decision-support') {
      this.router.navigate(['/app/decisions']);
    } else if (targetStage === 'dashboard') {
      this.router.navigate(['/app/dashboard']);
    }
  }
}
