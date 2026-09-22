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
import { ApiService } from '../api.service';

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

  // 1. KPI Grid Data (Wireframe Exact Values - NO currency symbols)
  kpiGrid = {
    monitoredSkus: '100 SKU',
    safePct: '69%',
    highRiskSkus: '25 SKU',
    needActionPct: '25%',
    totalCapitalExposure: '1.27B',
    topPriorityValue: '93.8M'
  };

  // 2. Risk Distribution Data (For Donut Chart & Text List)
  riskBreakdown = [
    { label: 'An toàn', pct: '69%', value: 69, color: '#22C55E' },
    { label: 'Cần theo dõi', pct: '6%', value: 6, color: '#EAB308' },
    { label: 'Rủi ro cao', pct: '25%', value: 25, color: '#EF4444' }
  ];

  // 3. Top 3 Priorities List (Today's Priorities - NO currency symbols)
  topPriorities: TopPrioritySku[] = [
    { sku: 'CRIT-024', capitalExposure: '93.8M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' },
    { sku: 'CRIT-019', capitalExposure: '88.7M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' },
    { sku: 'CRIT-017', capitalExposure: '84.8M', riskLevel: 'HIGH_RISK', badgeClass: 'bg-rose-600 text-white' }
  ];

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    // Component initialization
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.donutChartInstance) {
      this.initDonutChart();
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
          data: [
            { value: 69, name: 'An toàn', itemStyle: { color: this.COLOR_SAFE } },
            { value: 6, name: 'Cần theo dõi', itemStyle: { color: this.COLOR_WATCH } },
            { value: 25, name: 'Rủi ro cao', itemStyle: { color: this.COLOR_HIGH_RISK } }
          ]
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
    setTimeout(() => {
      this.isRefreshing = false;
      this.initDonutChart();
    }, 600);
  }

  onViewRiskAnalysisClick(): void {
    this.navigateTo.emit('slow-moving-risk');
  }

  onViewAllClick(): void {
    this.navigateTo.emit('slow-moving-risk');
  }

  onSelectSku(sku: string): void {
    this.analyzeSku.emit(sku);
  }

  onNavigateToStage(targetStage: string): void {
    this.navigateTo.emit(targetStage);
  }
}
