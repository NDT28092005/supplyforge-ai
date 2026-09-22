import { Component, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';

export interface SkuProfileItem {
  sku: string;
  product_name: string;
  observation_days: number;
  total_sales: number;
  active_sales_days: number;
  zero_sales_days: number;
  zero_sales_rate: number;
  sales_velocity: number;
  days_since_last_sale: number;
  avg_inter_purchase_interval: number;
  transaction_count: number;
  data_quality_status: string;
}

@Component({
  selector: 'app-dataset-profile-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './dataset-profile-dashboard.component.html',
  styleUrls: ['./dataset-profile-dashboard.component.css']
})
export class DatasetProfileDashboardComponent implements OnInit, OnChanges {
  @Input() sessionId: string = '';
  @Input() profileData: any = null;
  @Output() proceedToAnalysis = new EventEmitter<void>();

  skuItems: SkuProfileItem[] = [];
  searchQuery: string = '';
  currentPage: number = 1;
  pageSize: number = 15;
  totalSkus: number = 0;
  totalPages: number = 1;
  loadingSkus: boolean = false;

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    if (this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['sessionId'] && this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  loadProfile(): void {
    if (!this.profileData && this.sessionId) {
      this.apiService.getDatasetProfile(this.sessionId).subscribe({
        next: (res) => {
          this.profileData = res;
        },
        error: (err) => console.error('Failed to load dataset profile:', err)
      });
    }
  }

  loadSkuProfiles(): void {
    if (!this.sessionId) return;
    this.loadingSkus = true;
    this.apiService.getSkuProfiles(this.sessionId, this.currentPage, this.searchQuery).subscribe({
      next: (res) => {
        this.loadingSkus = false;
        this.skuItems = res.items || [];
        this.totalSkus = res.total || 0;
        this.totalPages = res.totalPages || 1;
      },
      error: (err) => {
        this.loadingSkus = false;
        console.error('Failed to load SKU profiles:', err);
      }
    });
  }

  onSearchChange(): void {
    this.currentPage = 1;
    this.loadSkuProfiles();
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
      this.loadSkuProfiles();
    }
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'READY':
        return 'bg-emerald-50 border-emerald-200 text-emerald-800 font-bold';
      case 'READY_WITH_WARNING':
        return 'bg-amber-50 border-amber-200 text-amber-800 font-bold';
      case 'NEEDS_CLEANING':
        return 'bg-amber-50 border-amber-200 text-amber-800 font-bold';
      case 'INSUFFICIENT_DATA':
        return 'bg-rose-50 border-rose-200 text-rose-800 font-bold';
      default:
        return 'bg-indigo-50 border-indigo-200 text-indigo-800 font-bold';
    }
  }

  onProceed(): void {
    this.proceedToAnalysis.emit();
  }
}
