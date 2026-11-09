import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

@Component({
  selector: 'app-procurement-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './procurement-dashboard.component.html',
  styleUrls: ['./procurement-dashboard.component.css'],
})
export class ProcurementDashboardComponent implements OnInit {
  sku = '';
  channel = '';
  warehouseCode = '';
  horizonDays = 90;
  isLoading = false;
  errorMessage = '';
  forecast: any = null;
  pricing: any = null;
  cashFlow: any = null;
  portfolio: any = null;
  isPortfolioLoading = false;
  portfolioError = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadPortfolio();
  }

  loadPortfolio(): void {
    this.isPortfolioLoading = true;
    this.portfolioError = '';
    this.api.getProcurementPortfolio(this.horizonDays).subscribe({
      next: (response) => {
        this.portfolio = response;
        this.isPortfolioLoading = false;
      },
      error: (response) => {
        this.portfolio = null;
        this.portfolioError = response?.error?.error?.message || 'Không thể tải danh mục mua hàng. Dữ liệu PO hiện tại không bị thay đổi.';
        this.isPortfolioLoading = false;
      },
    });
  }

  loadPlan(): void {
    const sku = this.sku.trim();
    const channel = this.channel.trim();
    if (!sku) {
      this.errorMessage = 'Nhập SKU để xem nhu cầu mua hàng và ngày dự kiến hết tồn.';
      return;
    }
    this.isLoading = true;
    this.errorMessage = '';
    this.forecast = null;
    this.pricing = null;
    this.api.getProcurementForecast(sku, this.horizonDays, this.warehouseCode.trim()).subscribe({
      next: (response) => {
        this.forecast = response;
        this.isLoading = false;
      },
      error: (response) => {
        this.forecast = response?.error || null;
        this.isLoading = false;
      },
    });
    this.api.getProcurementCashFlow(this.horizonDays).subscribe({
      next: (response) => this.cashFlow = response,
      error: () => this.cashFlow = null,
    });
    if (channel) {
      this.api.getPricingScenario(sku, channel, 14, this.warehouseCode.trim()).subscribe({
        next: (response) => this.pricing = response,
        error: (response) => this.pricing = response?.error || null,
      });
    }
  }

  getMissing(payload: any): string[] {
    return payload?.missing_inputs || [];
  }

  formatCurrency(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'Chưa có';
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 0 }).format(value);
  }

  formatQuantity(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'Chưa có';
    return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(value);
  }

  portfolioStateLabel(state: string): string {
    const labels: Record<string, string> = {
      ORDER_REVIEW: 'Cần review đơn mua',
      REVIEW_STOP_REPLENISHMENT: 'Cần quyết định PO đang mở',
      REVIEW_BUDGET: 'Cần rà soát ngân sách',
      DEFER_REVIEW: 'Có thể hoãn đặt thêm',
      DATA_NEEDED: 'Cần bổ sung dữ liệu',
    };
    return labels[state] || 'Cần rà soát';
  }
}
