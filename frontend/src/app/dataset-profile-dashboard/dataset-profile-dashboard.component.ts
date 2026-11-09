import { Component, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';

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
  loadingProfile: boolean = false;
  profileLoadError = '';
  isProceeding = false;
  analysisError = '';
  private sessionUnavailable = false;

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    const routeSessionId = this.route.snapshot.paramMap.get('sessionId');
    if (routeSessionId && routeSessionId !== 'default') {
      this.sessionId = routeSessionId;
    } else if (!this.sessionId) {
      this.sessionId = this.ingestionState.state.activeSessionId;
    }

    if (!this.profileData) {
      this.profileData = this.ingestionState.state.datasetProfileData;
    }

    this.normalizeProfileData();
    if (this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    this.normalizeProfileData();
    if (changes['sessionId'] && this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  normalizeProfileData(): void {
    if (!this.profileData || typeof this.profileData !== 'object') {
      this.profileData = null;
    }
  }

  get hasProfileData(): boolean {
    return !!this.profileData && Object.keys(this.profileData).length > 0;
  }

  get readinessStatus(): string | null {
    const value = this.profileData?.readiness?.status;
    return typeof value === 'string' && value.trim() ? value.trim() : null;
  }

  get readinessScore(): number | null {
    const value = this.profileData?.readiness?.readinessScore;
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  get checksPassedCount(): number | null {
    const checks = this.profileData?.readiness?.checksPassed;
    return Array.isArray(checks) ? checks.length : null;
  }

  get canProceedToAnalysis(): boolean {
    return this.hasProfileData && ['READY', 'READY_WITH_WARNING'].includes(this.readinessStatus || '');
  }

  displayValue(value: unknown): string | number {
    return value === null || value === undefined || value === '' ? '—' : value as string | number;
  }

  loadProfile(): void {
    if (this.sessionId && !this.sessionUnavailable) {
      this.loadingProfile = true;
      this.profileLoadError = '';
      this.apiService.getDatasetProfile(this.sessionId).subscribe({
        next: (res) => {
          this.loadingProfile = false;
          if (res) {
            this.profileData = {
              ...res,
              updated_rows: res.updated_rows ?? res.incremental_merge_json?.updated_rows,
              data_corrections: res.data_corrections ?? res.incremental_merge_json?.data_corrections ?? res.ingestion_history_json?.audit_trail,
            };
          }
        },
        error: (err: any) => {
          this.loadingProfile = false;
          if (this.isSessionMissingError(err)) {
            this.resetMissingSession();
            return;
          }
          this.profileLoadError = err?.error?.error || 'Không thể tải kết quả kiểm tra dữ liệu.';
          console.error('Failed to load dataset profile:', err);
        }
      });
    }
  }

  loadSkuProfiles(): void {
    if (!this.sessionId || this.sessionUnavailable) return;
    this.loadingSkus = true;
    this.apiService.getSkuProfiles(this.sessionId, this.currentPage, this.searchQuery).subscribe({
      next: (res) => {
        this.loadingSkus = false;
        this.skuItems = res.items || [];
        this.totalSkus = res.total || 0;
        this.totalPages = res.totalPages || 1;
      },
      error: (err: any) => {
        this.loadingSkus = false;
        if (this.isSessionMissingError(err)) {
          this.resetMissingSession();
          return;
        }
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
    if (this.isProceeding) return;
    if (!this.canProceedToAnalysis) {
      this.analysisError = this.readinessStatus
        ? 'Bộ dữ liệu chưa đạt điều kiện để chạy phân tích. Hãy xử lý các cảnh báo dữ liệu trước.'
        : 'Chưa có kết quả kiểm tra dữ liệu để bắt đầu phân tích.';
      return;
    }
    this.proceedToAnalysis.emit();
    this.isProceeding = true;
    this.analysisError = '';
    // The import worker builds and publishes the sole operational risk run.
    // Running the legacy browser-triggered research assembly here used a
    // different data path and could overwrite/mix the merchant result.
    this.isProceeding = false;
    this.ingestionState.setDatasetStatus('ready', 'Bộ dữ liệu đã sẵn sàng. Đánh giá vận hành dùng đúng phiên bản CSV đang active.');
    this.router.navigate(['/app/dashboard']);
  }

  private handleAnalysisError(message: string): void {
    this.isProceeding = false;
    this.analysisError = message;
    this.ingestionState.setErrorMessage(message);
  }

  private isSessionMissingError(err: any): boolean {
    const code = err?.error?.code;
    const message = String(err?.error?.error || err?.message || '').toLowerCase();
    return err?.status === 404 || code === 'SESSION_NOT_FOUND' || message.includes('ingestionsession');
  }

  private resetMissingSession(): void {
    if (this.sessionUnavailable) return;
    this.sessionUnavailable = true;
    this.isProceeding = false;
    this.loadingSkus = false;
    const message = 'Phiên nạp dữ liệu không còn tồn tại. Vui lòng tải lại tệp CSV để tạo phiên mới.';
    this.ingestionState.invalidateSession(message);
    this.router.navigate(['/app/import']);
  }
}
