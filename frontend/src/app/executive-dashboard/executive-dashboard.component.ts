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
  imports: [CommonModule, FormsModule],
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

  donutChartRef!: ElementRef<HTMLDivElement>;
  private donutChartInstance: any = null;

  // Selected Analysis Period Dropdown State
  selectedPeriod: string = '30 ngày qua';
  isRefreshing: boolean = false;

  // Color Coding Constants (Strict Compliance)
  readonly COLOR_SAFE = '#22C55E';     // Green-500
  readonly COLOR_WATCH = '#EAB308';    // Yellow-500
  readonly COLOR_HIGH_RISK = '#EF4444';// Red-500

  // 1. DASH-001: Shop Health Summary Direct Answer State ("Shop đang thế nào?")
  shopHealthSummary = {
    statusBadge: 'CẦN XỬ LÝ GẤP',
    statusLevel: 'HIGH_RISK',
    verdictTitle: 'Cửa hàng đang có rủi ro vốn đọng ở mức cao',
    verdictMessage: 'Hiện tại cửa hàng có 25 sản phẩm rủi ro cao với 317.5 Triệu VNĐ vốn đang bị đọng. Trong đó, 190.5 Triệu VNĐ đã kẹt trong kho trên 90 ngày.',
    takeaways: [
      'Cần kích hoạt ngay chiến dịch xả hàng cho 25% mặt hàng bán chậm.',
      'Ưu tiên xử lý 3 mặt hàng chiếm vốn lớn nhất (CRIT-024, CRIT-019, CRIT-017).',
      'Dự kiến giải phóng và thu hồi lại 75% - 80% giá trị vốn bị chôn.'
    ]
  };

  // 2. DASH-002: Exact 5 Required KPI Metrics (100% Plain Friendly Vietnamese)
  kpiGrid = {
    monitoredSkus: '100 sản phẩm',
    highRiskSkus: '25 sản phẩm',
    totalCapitalExposure: '1.27 Tỷ VNĐ',
    atRiskCapital: '317.5 Triệu VNĐ',
    agedCapital: '190.5 Triệu VNĐ',
    safePct: '69%',
    needActionPct: '25%'
  };

  // 3. DASH-003: Drill Down Flow Steps (Overview → Risk → Explanation → Capital → Decision)
  drillDownSteps = [
    { step: 1, label: '1. Tổng quan', description: 'Cửa hàng thế nào', stage: 'dashboard', active: true },
    { step: 2, label: '2. Cảnh báo rủi ro', description: 'Hàng chậm bán', stage: 'slow-moving-risk', active: false },
    { step: 3, label: '3. Nguyên nhân', description: 'Lý do bị tồn đọng', stage: 'slow-moving-risk', active: false },
    { step: 4, label: '4. Đánh giá vốn đọng', description: 'Thiệt hại dòng tiền', stage: 'capital-exposure', active: false },
    { step: 5, label: '5. Quyết định xả hàng', description: 'Đề xuất & thu hồi', stage: 'decision-support', active: false }
  ];

  // Risk Distribution Data (For Donut Chart & Text List)
  riskBreakdown = [
    { label: 'An toàn', pct: '69%', value: 69, color: '#22C55E' },
    { label: 'Cần theo dõi', pct: '6%', value: 6, color: '#EAB308' },
    { label: 'Rủi ro cao', pct: '25%', value: 25, color: '#EF4444' }
  ];

  // Top 3 Priorities List (Today's Priorities)
  topPriorities: TopPrioritySku[] = [
    { sku: 'CRIT-024', capitalExposure: '93.8M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' },
    { sku: 'CRIT-019', capitalExposure: '88.7M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' },
    { sku: 'CRIT-017', capitalExposure: '84.8M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' }
  ];

  // Attention Notice State
  attentionNotice = {
    highRiskCountText: '25 sản phẩm',
    slowCountText: '10 sản phẩm',
    deadCountText: '15 sản phẩm'
  };

  constructor(
    private apiService: ApiService,
    private dashboardState: DashboardStateService,
    private router: Router
  ) {}

  ngOnInit(): void {
    if (!this.data) {
      this.data = this.dashboardState.state.dashboardData;
    }
    if (!this.data) {
      this.fetchDashboardData();
    } else {
      this.updateDashboardFromData();
    }
  }

  fetchDashboardData(): void {
    this.loading = true;
    this.apiService.getDashboard(1).subscribe({
      next: (res) => {
        this.loading = false;
        if (res) {
          const healthyVal = res.totalHealthyValue || 0;
          const watchlistVal = res.totalWatchlistValue || 0;
          const slowVal = res.totalSlowMovingValue || 0;
          const deadVal = res.totalDeadStockValue || 0;
          const totalInvVal = healthyVal + watchlistVal + slowVal + deadVal;

          const healthyList = res.healthySkus || [];
          const watchlistList = res.watchlistSkus || [];
          const slowList = res.slowMovingSkus || [];
          const deadList = res.deadStockSkus || [];
          const allSkus = [...deadList, ...slowList, ...watchlistList, ...healthyList];

          let topStale = [...deadList, ...slowList].map((item: any) => ({
            sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
            name: item.name || item.product_name || 'SKU Sản phẩm',
            frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
            lastRecordDate: item.lastRecordDate || 'N/A'
          })).slice(0, 5);

          if (topStale.length === 0 && allSkus.length > 0) {
            topStale = allSkus.map((item: any) => ({
              sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
              name: item.name || item.product_name || 'SKU Sản phẩm',
              frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
              lastRecordDate: item.lastRecordDate || 'N/A'
            })).slice(0, 5);
          }

          const finalDeadStockValue = deadVal + slowVal;
          const finalStaleCount = deadList.length + slowList.length;
          const finalBleedingRate = res.totalBleedingRateMonthly || Math.round(finalDeadStockValue * 0.08);

          this.data = {
            hasData: true,
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
      },
      error: () => {
        this.loading = false;
      }
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['data']) {
      this.updateDashboardFromData();
    }
    if (this.donutChartInstance) {
      this.initDonutChart();
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
      slowCountText: `${slowCount} sản phẩm`,
      deadCountText: `${deadCount} sản phẩm`
    };

    const formatVndHuman = (val: number): string => {
      if (!val || val === 0) return '0 VNĐ';
      if (val >= 1000000000) return `${(val / 1000000000).toFixed(2)} Tỷ VNĐ`;
      if (val >= 1000000) return `${(val / 1000000).toFixed(1)} Triệu VNĐ`;
      if (val >= 1000) return `${(val / 1000).toFixed(0)} Nghìn VNĐ`;
      return `${val} VNĐ`;
    };

    if (totalCount > 0) {
      const safePctVal = Math.round((safeCount / totalCount) * 100);
      const watchPctVal = Math.round((watchCount / totalCount) * 100);
      const highRiskPctVal = Math.max(0, 100 - safePctVal - watchPctVal);

      const totalCapVnd = this.data.totalInventoryValueVnd || (
        healthyList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0) +
        slowList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0) +
        deadList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0)
      ) || 1270000000;

      const atRiskVal = (
        slowList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0) +
        deadList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0)
      ) || Math.round(totalCapVnd * 0.25);

      const agedVal = (
        deadList.reduce((acc: number, item: any) => acc + (item.totalValue || 0), 0)
      ) || Math.round(totalCapVnd * 0.15);

      const topStale = this.data.topStaleSkus || [];

      // DASH-002: Set exact 5 KPIs with human Vietnamese titles
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
        this.shopHealthSummary = {
          statusBadge: 'CẦN XỬ LÝ GẤP',
          statusLevel: 'HIGH_RISK',
          verdictTitle: `Cửa hàng đang có ${highRiskCount} sản phẩm gặp rủi ro vốn đọng`,
          verdictMessage: `Hiện tại cửa hàng có ${highRiskCount} sản phẩm rủi ro cao với ${formatVndHuman(atRiskVal)} vốn đang có nguy cơ đọng vốn nặng. Trong đó, có ${formatVndHuman(agedVal)} vốn đã kẹt trong kho hơn 90 ngày. Cửa hàng nên triển khai chiết khấu để giải phóng dòng tiền.`,
          takeaways: [
            `Cần kích hoạt chiến dịch xả kho cho ${highRiskPctVal}% số sản phẩm bán chậm.`,
            `Ưu tiên xử lý 3 mặt hàng chiếm vốn lớn nhất (${topStale.slice(0, 3).map((p: any) => p.sku || p.name).join(', ') || 'CRIT-024, CRIT-019'}).`,
            `Dự kiến giải phóng và thu hồi lại đến 80% vốn bị chôn khi áp dụng kịch bản khuyến nghị.`
          ]
        };
      } else {
        this.shopHealthSummary = {
          statusBadge: 'HOẠT ĐỘNG TỐT',
          statusLevel: 'SAFE',
          verdictTitle: 'Kho hàng đang vận hành ổn định và an toàn',
          verdictMessage: 'Toàn bộ các mặt hàng trong kho đang duy trì tốc độ tiêu thụ tốt, không ghi nhận tình trạng đọng vốn đọng lâu ngày.',
          takeaways: [
            'Dòng vốn quay vòng ổn định và lành mạnh.',
            'Tiếp tục theo dõi biến động sức mua của thị trường.',
            'Không cần thực hiện chiết khấu hay xả hàng khẩn cấp.'
          ]
        };
      }

      this.riskBreakdown = [
        { label: 'An toàn', pct: `${safePctVal}%`, value: safePctVal, color: this.COLOR_SAFE },
        { label: 'Cần theo dõi', pct: `${watchPctVal}%`, value: watchPctVal, color: this.COLOR_WATCH },
        { label: 'Rủi ro cao', pct: `${highRiskPctVal}%`, value: highRiskPctVal, color: this.COLOR_HIGH_RISK }
      ];

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
    }
  }

  ngAfterViewInit(): void {
    setTimeout(() => {
      this.initDonutChart();
    }, 300);
  }

  ngOnDestroy(): void {
    this.disposeCharts();
  }

  @HostListener('window:resize')
  onResize(): void {
    if (this.donutChartInstance) this.donutChartInstance.resize();
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
            <span style="color:#FFFFFF;font-weight:800;font-family:'Be Vietnam Pro',sans-serif;font-size:14px;">${params.value}%</span>
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
            itemStyle: { color: b.color }
          }))
        }
      ]
    };

    this.donutChartInstance.setOption(option);
  }

  disposeCharts(): void {
    if (this.donutChartInstance) {
      this.donutChartInstance.dispose();
      this.donutChartInstance = null;
    }
  }

  refreshData(): void {
    this.isRefreshing = true;
    this.fetchDashboardData();
    setTimeout(() => {
      this.isRefreshing = false;
      this.initDonutChart();
    }, 600);
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
