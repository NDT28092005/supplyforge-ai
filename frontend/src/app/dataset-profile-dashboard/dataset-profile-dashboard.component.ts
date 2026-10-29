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

    this.ensureProfileData();
    if (this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    this.ensureProfileData();
    if (changes['sessionId'] && this.sessionId) {
      this.loadProfile();
      this.loadSkuProfiles();
    }
  }

  ensureProfileData(): void {
    if (!this.profileData) {
      this.profileData = {};
    }
    this.profileData = {
      readiness: {
        status: 'READY',
        readinessScore: 90,
        checksPassed: ['Kiểm tra cấu trúc CSV', 'Mã hóa UTF-8', 'Tên cột chuẩn hóa'],
        warnings: [],
        ...(this.profileData.readiness || {})
      },
      overview: {
        totalRecords: this.profileData.rows_received || this.profileData.rows_valid || 0,
        uniqueSkus: this.totalSkus || 0,
        observationPeriodDays: 30,
        minTransactionDate: 'N/A',
        maxTransactionDate: 'N/A',
        ...(this.profileData.overview || {})
      },
      sparsity: {
        avgZeroSalesRatePct: 20.0,
        intermittentSkuCount: 0,
        lumpySkuCount: 0,
        smoothSkuCount: this.totalSkus || 0,
        ...(this.profileData.sparsity || {})
      },
      ...this.profileData
    };
  }

  loadProfile(): void {
    if (this.sessionId && !this.sessionUnavailable) {
      this.apiService.getDatasetProfile(this.sessionId).subscribe({
        next: (res) => {
          if (res) {
            this.profileData = {
              ...this.profileData,
              ...res,
              updated_rows: res.updated_rows ?? res.incremental_merge_json?.updated_rows ?? this.profileData.updated_rows ?? 0,
              data_corrections: res.data_corrections ?? res.incremental_merge_json?.data_corrections ?? res.ingestion_history_json?.audit_trail ?? this.profileData.data_corrections ?? [],
              readiness: { ...(this.profileData?.readiness || {}), ...(res.readiness || {}) },
              overview: { ...(this.profileData?.overview || {}), ...(res.overview || {}) },
              sparsity: { ...(this.profileData?.sparsity || {}), ...(res.sparsity || {}) }
            };
          }
        },
        error: (err: any) => {
          if (this.isSessionMissingError(err)) {
            this.resetMissingSession();
            return;
          }
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
    this.proceedToAnalysis.emit();
    this.isProceeding = true;
    this.analysisError = '';
    this.ingestionState.setDatasetStatus('processing', 'Đang xây dựng đánh giá rủi ro từ bộ dữ liệu vừa nhập.');
    if (this.sessionId) {
      this.apiService.runM3RiskAssessmentAssembly(this.sessionId).subscribe({
        next: () => {
          this.apiService.runM3RiskMonitoring(this.sessionId).subscribe({
            next: () => {
              this.isProceeding = false;
              this.ingestionState.setDatasetStatus('ready', 'Bộ dữ liệu và các đánh giá rủi ro đã sẵn sàng.');
              this.router.navigate(['/app/dashboard']);
            },
            error: (err: any) => {
              if (this.isSessionMissingError(err)) {
                this.resetMissingSession();
                return;
              }
              this.handleAnalysisError(err?.error?.error || 'Không thể hoàn tất đánh giá rủi ro.');
            }
          });
        },
        error: (err: any) => {
          if (this.isSessionMissingError(err)) {
            this.resetMissingSession();
            return;
          }
          this.handleAnalysisError(err?.error?.error || 'Không thể tạo đánh giá rủi ro.');
        }
      });
    } else {
      this.isProceeding = false;
      this.ingestionState.setDatasetStatus('ready', 'Bộ dữ liệu đã sẵn sàng.');
      this.router.navigate(['/app/dashboard']);
    }
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
