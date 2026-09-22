import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';

export interface ShapFactorItem {
  label: string;
  subDesc: string;
  impactText: string; // e.g. "Tác động rất mạnh", "Tác động mạnh", "Tác động vừa"
  score: number; // 1 to 5
  pct: number; // 20 to 100
  severity: 'red' | 'amber' | 'emerald';
}

export interface SkuRiskItem {
  sku: string;
  name: string;
  riskClass: 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
  probabilityPct: string; // e.g. "98.4%"
  probabilityValue: number; // e.g. 0.984
  velocity: number; // e.g. 0.08
  dslsDays: number; // e.g. 199
  capitalExposure: string; // e.g. "93.8M"
  
  // Drawer / Modal Behavior Data
  sales30d: number;
  sales90d: number;
  zeroRatePct: string; // e.g. "94.9%"
  demandProb: number; // e.g. 0.04
  demandPattern: string; // e.g. "Intermittent"
  
  // Merchant-Friendly SHAP Factors
  shapFactors: ShapFactorItem[];
  
  // LLM / System Conclusion
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

  // Filter & Search State
  selectedRiskFilter: string = ''; // '' = All (100), 'HIGH_RISK' = 25, 'MEDIUM_RISK' = 6, 'LOW_RISK' = 69
  searchTerm: string = '';

  // Detail Modal State
  drawerOpen: boolean = false;
  selectedSku: SkuRiskItem | null = null;
  showShapCalcModal: boolean = false;

  // Exact 100 Mock SKUs
  items: SkuRiskItem[] = [];

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    this.generateMockData();
    if (this.skuId) {
      const match = this.items.find(i => i.sku === this.skuId);
      if (match) {
        this.openDrawer(match);
      }
    }
  }

  generateMockData(): void {
    const list: SkuRiskItem[] = [];

    // 1. Exact Wireframe SKU: CRIT-024
    list.push({
      sku: 'CRIT-024',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 24',
      riskClass: 'HIGH_RISK',
      probabilityPct: '98.4%',
      probabilityValue: 0.984,
      velocity: 0.08,
      dslsDays: 199,
      capitalExposure: '93.8M',
      sales30d: 2,
      sales90d: 5,
      zeroRatePct: '94.9%',
      demandProb: 0.04,
      demandPattern: 'Intermittent',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '94.9% thời gian không phát sinh đơn hàng nào', impactText: 'Tác động rất mạnh', score: 5, pct: 95, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 199 ngày kể từ đơn hàng phát sinh gần nhất', impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' },
        { label: 'Tốc độ tiêu thụ trung bình (Sales Velocity)', subDesc: 'Sức bán cực yếu, trung bình 0.08 sản phẩm/ngày', impactText: 'Tác động mạnh', score: 4, pct: 75, severity: 'amber' },
        { label: 'Xác suất phát sinh nhu cầu mới (Demand Prob)', subDesc: 'Xác suất khách tìm mua mới chỉ đạt mức 4%', impactText: 'Tác động vừa', score: 3, pct: 60, severity: 'amber' }
      ],
      conclusion: 'SKU có tốc độ tiêu thụ thấp và nhiều ngày không phát sinh giao dịch trong giai đoạn quan sát.'
    });

    // 2. Exact Wireframe SKU: CRIT-019
    list.push({
      sku: 'CRIT-019',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 19',
      riskClass: 'HIGH_RISK',
      probabilityPct: '97.9%',
      probabilityValue: 0.979,
      velocity: 0.11,
      dslsDays: 204,
      capitalExposure: '88.7M',
      sales30d: 3,
      sales90d: 7,
      zeroRatePct: '92.1%',
      demandProb: 0.05,
      demandPattern: 'Intermittent',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '92.1% thời gian không phát sinh đơn hàng nào', impactText: 'Tác động rất mạnh', score: 5, pct: 92, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 204 ngày chưa bán thêm được sản phẩm nào', impactText: 'Tác động mạnh', score: 4, pct: 85, severity: 'red' },
        { label: 'Tốc độ tiêu thụ trung bình (Sales Velocity)', subDesc: 'Sức bán chỉ đạt 0.11 sản phẩm/ngày', impactText: 'Tác động mạnh', score: 4, pct: 70, severity: 'amber' },
        { label: 'Xác suất phát sinh nhu cầu mới (Demand Prob)', subDesc: 'Xác suất khách mua thấp ở mức 5%', impactText: 'Tác động vừa', score: 3, pct: 55, severity: 'amber' }
      ],
      conclusion: 'SKU có lượng chôn vốn lớn, phát sinh ít giao dịch trong 90 ngày và thời gian chôn hàng kéo dài.'
    });

    // 3. Exact Wireframe SKU: CRIT-017
    list.push({
      sku: 'CRIT-017',
      name: 'Sản phẩm Nguy Cơ Bán Chậm Rất Cao 17',
      riskClass: 'HIGH_RISK',
      probabilityPct: '97.2%',
      probabilityValue: 0.972,
      velocity: 0.09,
      dslsDays: 199,
      capitalExposure: '84.8M',
      sales30d: 2,
      sales90d: 6,
      zeroRatePct: '93.5%',
      demandProb: 0.04,
      demandPattern: 'Intermittent',
      shapFactors: [
        { label: 'Tỷ lệ ngày không bán (90 ngày qua)', subDesc: '93.5% thời gian không có lượt mua mới', impactText: 'Tác động rất mạnh', score: 5, pct: 93, severity: 'red' },
        { label: 'Số ngày chôn hàng chưa bán được (DSLS)', subDesc: 'Đã 199 ngày chôn vốn trong kho', impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' },
        { label: 'Tốc độ tiêu thụ trung bình (Sales Velocity)', subDesc: 'Sức bán chậm chỉ 0.09 sản phẩm/ngày', impactText: 'Tác động mạnh', score: 4, pct: 72, severity: 'amber' },
        { label: 'Xác suất phát sinh nhu cầu mới (Demand Prob)', subDesc: 'Nhu cầu thị trường yếu ở mức 4%', impactText: 'Tác động vừa', score: 3, pct: 58, severity: 'amber' }
      ],
      conclusion: 'Sản phẩm có chu kỳ bán rải rác và tốc độ tiêu thụ ở mức báo động.'
    });

    // Generate remaining 22 HIGH_RISK items (Total 25 HIGH_RISK)
    for (let i = 1; i <= 22; i++) {
      const pad = i.toString().padStart(3, '0');
      const prob = (96.8 - i * 0.4).toFixed(1);
      list.push({
        sku: `CRIT-${pad}`,
        name: `Sản phẩm Nguy Cơ Bán Chậm Rất Cao ${i}`,
        riskClass: 'HIGH_RISK',
        probabilityPct: `${prob}%`,
        probabilityValue: parseFloat(prob) / 100,
        velocity: parseFloat((0.05 + (i % 5) * 0.02).toFixed(2)),
        dslsDays: 95 + i * 4,
        capitalExposure: `${(80 - i * 2.1).toFixed(1)}M`,
        sales30d: 1 + (i % 3),
        sales90d: 4 + (i % 5),
        zeroRatePct: `${(90 + (i % 6)).toFixed(1)}%`,
        demandProb: 0.05,
        demandPattern: i % 2 === 0 ? 'Intermittent' : 'Lumpy',
        shapFactors: [
          { label: 'Tỷ lệ ngày không bán', subDesc: 'Hơn 90% thời gian không bán được đơn nào', impactText: 'Tác động rất mạnh', score: 5, pct: 90, severity: 'red' },
          { label: 'Số ngày chôn hàng (DSLS)', subDesc: `Đã ${95 + i * 4} ngày chưa có giao dịch mới`, impactText: 'Tác động mạnh', score: 4, pct: 80, severity: 'red' },
          { label: 'Tốc độ bán hàng', subDesc: 'Sức bán dưới mốc tối thiểu 0.1 sản phẩm/ngày', impactText: 'Tác động vừa', score: 3, pct: 65, severity: 'amber' },
          { label: 'Xác suất cầu mới', subDesc: 'Thị trường chưa có dấu hiệu phục hồi nhu cầu', impactText: 'Tác động vừa', score: 3, pct: 55, severity: 'amber' }
        ],
        conclusion: 'Sản phẩm có lượng hàng chôn dài ngày, tốc độ bán chậm cần xem xét ưu tiên xử lý vốn.'
      });
    }

    // Generate 6 MEDIUM_RISK (Cần theo dõi) items
    for (let i = 1; i <= 6; i++) {
      const pad = i.toString().padStart(3, '0');
      const prob = (68.5 - i * 1.5).toFixed(1);
      list.push({
        sku: `WATCH-${pad}`,
        name: `Sản phẩm Cần Theo Dõi ${i}`,
        riskClass: 'MEDIUM_RISK',
        probabilityPct: `${prob}%`,
        probabilityValue: parseFloat(prob) / 100,
        velocity: parseFloat((0.25 + i * 0.04).toFixed(2)),
        dslsDays: 35 + i * 4,
        capitalExposure: `${(25 - i * 1.5).toFixed(1)}M`,
        sales30d: 8 + i,
        sales90d: 22 + i * 2,
        zeroRatePct: `${(60 + i * 2).toFixed(1)}%`,
        demandProb: 0.22,
        demandPattern: 'Lumpy',
        shapFactors: [
          { label: 'Tốc độ bán giảm nhẹ', subDesc: 'Sức mua chậm hơn so với trung bình cùng kỳ', impactText: 'Tác động trung bình', score: 3, pct: 50, severity: 'amber' },
          { label: 'Số ngày chôn hàng tăng', subDesc: `Đã ${35 + i * 4} ngày từ lượt bán gần nhất`, impactText: 'Tác động trung bình', score: 3, pct: 45, severity: 'amber' },
          { label: 'Tỷ lệ ngày trống đơn', subDesc: 'Khoảng 60% số ngày không có đơn', impactText: 'Tác động nhẹ', score: 2, pct: 35, severity: 'emerald' }
        ],
        conclusion: 'SKU xuất hiện tín hiệu bán chậm nhẹ trong 30 ngày qua, cần tiếp tục giám sát.'
      });
    }

    // Generate 69 LOW_RISK (An toàn) items
    for (let i = 1; i <= 69; i++) {
      const pad = i.toString().padStart(3, '0');
      const prob = (18.5 - (i % 15) * 0.8).toFixed(1);
      list.push({
        sku: `SAFE-${pad}`,
        name: `Sản phẩm An Toàn ${i}`,
        riskClass: 'LOW_RISK',
        probabilityPct: `${prob}%`,
        probabilityValue: parseFloat(prob) / 100,
        velocity: parseFloat((0.85 + (i % 8) * 0.15).toFixed(2)),
        dslsDays: 2 + (i % 12),
        capitalExposure: `${(12 - (i % 10) * 0.8).toFixed(1)}M`,
        sales30d: 28 + (i % 15),
        sales90d: 85 + (i % 40),
        zeroRatePct: `${(15 + (i % 10)).toFixed(1)}%`,
        demandProb: 0.88,
        demandPattern: 'Smooth',
        shapFactors: [
          { label: 'Tốc độ bán ổn định', subDesc: 'Sức mua đều đặn hàng ngày', impactText: 'Mức an toàn', score: 1, pct: 15, severity: 'emerald' },
          { label: 'Đơn hàng phát sinh liên tục', subDesc: `Giao dịch gần nhất chỉ ${2 + (i % 12)} ngày trước`, impactText: 'Mức an toàn', score: 1, pct: 10, severity: 'emerald' }
        ],
        conclusion: 'Sản phẩm lưu thông tốt, phát sinh giao dịch đều đặn, chỉ số an toàn.'
      });
    }

    this.items = list;
  }

  // Getters for Filter Chip Counts
  get totalCount(): number {
    return this.items.length; // 100
  }

  get highRiskCount(): number {
    return this.items.filter(i => i.riskClass === 'HIGH_RISK').length; // 25
  }

  get watchCount(): number {
    return this.items.filter(i => i.riskClass === 'MEDIUM_RISK').length; // 6
  }

  get safeCount(): number {
    return this.items.filter(i => i.riskClass === 'LOW_RISK').length; // 69
  }

  // Filtered List
  get filteredItems(): SkuRiskItem[] {
    let result = [...this.items];

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

  openDrawer(item: SkuRiskItem): void {
    this.selectedSku = item;
    this.drawerOpen = true;
    document.body.style.overflow = 'hidden';
  }

  closeDrawer(): void {
    this.drawerOpen = false;
    this.selectedSku = null;
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

  navigateToCapitalExposure(): void {
    this.closeDrawer();
    this.navigateTo.emit('capital-exposure');
  }

  navigateToDecisions(): void {
    this.closeDrawer();
    this.navigateTo.emit('decision-support');
  }

  getPatternLabel(pattern: string | undefined): string {
    if (!pattern) return 'Bán lắt nhắt';
    switch (pattern.toLowerCase()) {
      case 'intermittent': return 'Bán lắt nhắt';
      case 'lumpy': return 'Bán không đều';
      case 'smooth': return 'Bán đều đặn';
      default: return pattern;
    }
  }
}
