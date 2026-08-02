import { Component, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SimulatorState } from '../simulator-state';
import { ApiService } from '../api.service';
import { ShapWaterfallComponent } from '../shap-waterfall/shap-waterfall.component';

@Component({
  selector: 'app-recovery-copilot',
  standalone: true,
  imports: [CommonModule, FormsModule, ShapWaterfallComponent],
  templateUrl: './recovery-copilot.component.html',
  styleUrls: ['./recovery-copilot.component.css']
})
export class RecoveryCopilotComponent implements OnInit, OnChanges {
  @Input() cluster: any = null;

  simulator: SimulatorState = {
    discountPct: 35,
    accounting: 'FIFO'
  };

  simLoading = false;
  simResult: any = null;

  // xAI State
  selectedSkuId = '';
  xaiLoading = false;
  xaiData: any = null;

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    if (this.cluster && this.cluster.recommendedDiscountPct !== undefined) {
      this.simulator.discountPct = this.cluster.recommendedDiscountPct;
    }
    this.initSkuSelector();
    this.runSimulation();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['cluster'] && changes['cluster'].currentValue) {
      if (changes['cluster'].currentValue.recommendedDiscountPct !== undefined) {
        this.simulator.discountPct = changes['cluster'].currentValue.recommendedDiscountPct;
      }
      this.initSkuSelector();
      this.runSimulation();
    }
  }

  initSkuSelector(): void {
    if (this.cluster && this.cluster.skus && this.cluster.skus.length > 0) {
      this.selectedSkuId = this.cluster.skus[0].id;
      this.loadSkuXai();
    } else {
      this.selectedSkuId = '';
      this.xaiData = null;
    }
  }

  loadSkuXai(): void {
    if (!this.selectedSkuId) return;
    this.xaiLoading = true;
    this.apiService.getSkuXai(1, this.selectedSkuId).subscribe({
      next: (res) => {
        this.xaiData = res;
        this.xaiLoading = false;
      },
      error: (err) => {
        console.error('Fetch XAI error:', err);
        this.xaiLoading = false;
        this.xaiData = null;
      }
    });
  }

  runSimulation(): void {
    this.simLoading = true;
    setTimeout(() => {
      const discountRatio = this.simulator.discountPct / 100.0;
      const totalCost = this.cluster?.totalFrozenValue || 10000000;
      const expectedRevenue = totalCost * (1 - discountRatio);
      const mktCost = expectedRevenue * 0.1;
      const netRev = expectedRevenue - mktCost;
      const writeOffLoss = Math.max(0, totalCost - netRev);
      const taxShield = writeOffLoss * 0.2;

      this.simResult = {
        expectedRevenue,
        marketingAndShippingCost: mktCost,
        netRecoveryRate: Math.round(((netRev) / totalCost) * 100),
        taxShieldValueVnd: taxShield,
        taxShieldRecommended: writeOffLoss > 0,
        aiRecommendation: `Mức giảm giá ${this.simulator.discountPct}% giúp tối ưu hóa khả năng thanh lý trong vòng 14 ngày.`,
        writeOffStrategy: `Áp dụng phương pháp ${this.simulator.accounting} giúp tối ưu khấu trừ thuế TNDN.`
      };
      this.simLoading = false;
    }, 400);
  }

  formatVND(value: number): string {
    if (!value) return '0 ₫';
    return Math.round(value).toLocaleString('vi-VN') + ' ₫';
  }
}
