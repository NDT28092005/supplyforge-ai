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
    this.loadRealAssessments();
  }

  loadRealAssessments(): void {
    this.apiService.getM3RiskAssessments().subscribe({
      next: (res: any) => {
        if (res && res.assessments && res.assessments.length > 0) {
          this.items = res.assessments.map((a: any) => this.mapAssessmentToSkuRiskItem(a));
          if (this.skuId) {
            const match = this.items.find(i => i.sku === this.skuId);
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
            const match = this.items.find(i => i.sku === this.skuId);
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
      velocity: item.velocities?.weighted || 0.1,
      dslsDays: dslsDays,
      capitalExposure: formatCap(capVal),
      sales30d: item.velocities?.simple ? Math.round(item.velocities.simple * 30) : 0,
      sales90d: item.velocities?.weighted ? Math.round(item.velocities.weighted * 90) : 0,
      zeroRatePct: zeroRatePct,
      demandProb: 0.1,
      demandPattern: dslsDays > 90 ? 'Bán lắt nhắt' : (dslsDays > 30 ? 'Bán không đều' : 'Bán đều đặn'),
      shapFactors: shapFactors,
      conclusion: `Sản phẩm có chu kỳ lưu kho ${dslsDays} ngày, thuộc nhóm rủi ro ${riskClass === 'HIGH_RISK' ? 'cao' : (riskClass === 'MEDIUM_RISK' ? 'cần theo dõi' : 'an toàn')}.`
    };
  }

  mapAssessmentToSkuRiskItem(a: any): SkuRiskItem {
    const ev = a.evidence || {};
    const rawClass = a.risk?.class || a.risk_class || 'LOW_RISK';
    const riskClass = (rawClass === 'CRITICAL' ? 'HIGH_RISK' : rawClass) as 'HIGH_RISK' | 'MEDIUM_RISK' | 'LOW_RISK';
    const probVal = a.risk?.probability !== undefined ? a.risk.probability : (a.risk_probability !== undefined ? a.risk_probability : 0.5);
    const probPct = `${(probVal * 100).toFixed(1)}%`;
    const velocity = ev.sales_velocity_90d || ev.velocity_90d || 0;
    const dslsDays = ev.dsls || 0;
    const zeroRatePct = `${((ev.zero_rate_90d || 0) * 100).toFixed(1)}%`;

    const capVal = ev.totalValue || ((ev.sold_90d || 1) * 50000);
    const capitalExposure = capVal >= 1000000000 ? `${(capVal / 1000000000).toFixed(1)}B` : `${(capVal / 1000000).toFixed(1)}M`;

    const shapFactors: ShapFactorItem[] = [];
    if (ev.zero_rate_90d && ev.zero_rate_90d > 0.5) {
      shapFactors.push({
        label: 'Tỷ lệ ngày không bán (90 ngày qua)',
        subDesc: `${zeroRatePct} thời gian không phát sinh đơn hàng nào`,
        impactText: 'Tác động rất mạnh',
        score: 5,
        pct: Math.round((ev.zero_rate_90d || 0) * 100),
        severity: 'red'
      });
    }
    if (dslsDays > 30) {
      shapFactors.push({
        label: 'Số ngày chưa có đơn hàng mới',
        subDesc: `Đã ${dslsDays} ngày kể từ đơn hàng phát sinh gần nhất`,
        impactText: 'Tác động mạnh',
        score: 4,
        pct: Math.min(100, Math.round(dslsDays / 2)),
        severity: dslsDays > 90 ? 'red' : 'amber'
      });
    }
    if (velocity < 1.0) {
      shapFactors.push({
        label: 'Tốc độ tiêu thụ trung bình (Sales Velocity)',
        subDesc: `Sức bán trung bình ${velocity.toFixed(2)} sản phẩm/ngày`,
        impactText: 'Tác động mạnh',
        score: 4,
        pct: Math.max(20, Math.round((1 - velocity) * 100)),
        severity: 'amber'
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

    const roundTwo = (n: number) => Math.round(n * 100) / 100;

    return {
      sku: a.sku || a.canonical_sku_id || 'SKU_UNSET',
      name: a.product_name || a.sku || 'Sản phẩm',
      riskClass: riskClass,
      probabilityPct: probPct,
      probabilityValue: probVal,
      velocity: velocity,
      dslsDays: dslsDays,
      capitalExposure: capitalExposure,
      sales30d: ev.sold_30d || 0,
      sales90d: ev.sold_90d || 0,
      zeroRatePct: zeroRatePct,
      demandProb: roundTwo(1.0 - (ev.zero_rate_90d || 0)),
      demandPattern: velocity > 1.0 ? 'Smooth' : ((ev.zero_rate_90d || 0) > 0.7 ? 'Intermittent' : 'Lumpy'),
      shapFactors: shapFactors,
      conclusion: Array.isArray(a.primary_signals) ? a.primary_signals.join(', ') : (a.conclusion || 'SKU lưu thông thuộc diện quản lý rủi ro.')
    };
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
