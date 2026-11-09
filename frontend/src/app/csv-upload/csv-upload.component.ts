import { Component, EventEmitter, Output, Input, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

export interface ProfileResponse {
  sessionId: string;
  status: string;
  error?: string;
  idempotent_retry?: boolean;
  message?: string;
  file: {
    originalFilename: string;
    fileSizeBytes: number;
    fileSizeHuman: string;
  };
  profile: {
    totalRows: number;
    totalColumns: number;
    headers: string[];
    columnTypes: Record<string, string>;
    dateRange: {
      start: string | null;
      end: string | null;
      spanDays: number | null;
    };
    dateColumnDetected: string | null;
    uniqueSkuCount: number;
    skuColumnDetected: string | null;
    missingValues: Record<string, { count: number; pct: number }>;
    previewRows: string[][];
    validation?: {
      status: 'VALIDATED' | 'WARNING' | 'REJECT';
      encoding: string;
      delimiter: string;
      headers: string[];
      errors: string[];
      warnings: string[];
      corruptedRows: Array<{ line_number: number; raw_content: string; reason: string }>;
      emptyRowsCount: number;
      totalRows: number;
      validRowsCount: number;
    };
  };
}

@Component({
  selector: 'app-csv-upload',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './csv-upload.component.html',
  styleUrls: ['./csv-upload.component.css']
})
export class CsvUploadComponent implements OnInit, OnChanges {
  private readonly multipartThresholdBytes = 5 * 1024 * 1024;
  private readonly multipartResumeStorageKey = 'sf.multipart-upload.resume.v1';
  @Input() initialErrorMessage = '';
  @Input() initialFile: File | null = null;
  @Output() continueToMapping = new EventEmitter<{ file: File; profileData: ProfileResponse; sessionType: 'INITIAL' | 'INCREMENTAL' }>();

  isDragging = false;
  selectedFile: File | null = null;
  sessionType: 'INITIAL' | 'INCREMENTAL' = 'INITIAL';

  // Status state: 'idle' | 'uploading' | 'profiled' | 'error'
  uploadStatus: 'idle' | 'uploading' | 'profiled' | 'error' = 'idle';
  uploadProgress = 0;
  uploadStage = 'Đang chuẩn bị tệp để tải lên';
  errorMessage = '';
  profileResult: ProfileResponse | null = null;

  // Idempotency Duplicate Retry Modal State (IR-020)
  showIdempotentModal = false;

  // Format guide and sample download state
  showFormatGuide = false;

  // Each deliberate file selection is a new import action.  The sequence
  // also prevents a slow response for a previously selected file from
  // replacing the state of the latest selection.
  private uploadAttempt = 0;

  toggleFormatGuide(): void {
    this.showFormatGuide = !this.showFormatGuide;
  }

  downloadSampleCsv(): void {
    const sampleCsvContent = `order_id,item_sku,product_name,quantity,price,cost,stock,order_date
ORD-2026-001,POLO-WHT-XL,Áo thun Polo Cotton Premium (Trắng XL),2,250000,150000,120,2026-06-25
ORD-2026-002,SNK-BLK-42,Giày Sneaker Running V3 (Đen 42),1,750000,450000,45,2026-06-26
ORD-2026-003,BAG-WTP-15,Balo chống nước Laptop 15.6 inch,1,490000,290000,60,2026-06-27
ORD-2026-004,HP-ANC-BT,Tai nghe Bluetooth Noise Cancelling,3,1200000,750000,15,2026-06-28
ORD-2026-005,WLT-MAN-HM,Ví da Nam Dáng Ngang Handmade,2,350000,180000,80,2026-06-29`;

    const blob = new Blob(['\uFEFF' + sampleCsvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', 'file_mau_sales_data_supplyforge.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private dashboardState: DashboardStateService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.applyInitialInputs();
    this.sessionType = this.ingestionState.state.sessionType;
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['initialErrorMessage'] || changes['initialFile']) {
      this.applyInitialInputs();
    }
  }

  private applyInitialInputs(): void {
    const state = this.ingestionState.state;
    if (state.uploadFile) {
      this.selectedFile = state.uploadFile;
    } else if (this.initialFile) {
      this.selectedFile = this.initialFile;
    }

    if (state.uploadErrorMessage) {
      this.errorMessage = state.uploadErrorMessage;
      this.uploadStatus = 'error';
    } else if (this.initialErrorMessage) {
      this.errorMessage = this.initialErrorMessage;
      this.uploadStatus = 'error';
    }
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging = false;

    if (event.dataTransfer && event.dataTransfer.files.length > 0) {
      const file = event.dataTransfer.files[0];
      this.handleFileSelected(file);
    }
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      this.handleFileSelected(file);
    }
  }

  handleFileSelected(file: File): void {
    const attempt = ++this.uploadAttempt;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      this.errorMessage = 'Chỉ hỗ trợ tệp định dạng .csv. Vui lòng kiểm tra lại.';
      this.uploadStatus = 'error';
      this.ingestionState.setErrorMessage(this.errorMessage);
      return;
    }

    const idempotencyKey = this.createImportRequestKey();
    this.selectedFile = file;
    this.profileResult = null;
    this.showIdempotentModal = false;
    // A new initial import replaces the active dataset. Hide cached reports
    // immediately so no previous or example figures are shown during import.
    if (this.sessionType === 'INITIAL') {
      this.dashboardState.reset();
    }
    this.ingestionState.beginImport(file, this.sessionType);
    this.errorMessage = '';
    this.uploadStatus = 'uploading';
    this.uploadProgress = 8;
    this.uploadStage = 'Đang tải tệp lên máy chủ';

    // Large files never transit the API container. The browser uploads parts
    // directly to object storage and the API only coordinates the job.
    if (file.size >= this.multipartThresholdBytes) {
      void this.uploadMultipartToObjectStorage(file, attempt, idempotencyKey);
      return;
    }

    const progressInterval = setInterval(() => {
      if (this.uploadProgress < 88) {
        this.uploadProgress += 4;
        if (this.uploadProgress >= 52) {
          this.uploadStage = 'Đang kiểm tra cấu trúc, cột dữ liệu và bản ghi lỗi';
        }
      }
    }, 200);

    this.apiService.uploadCsvV2(
      file,
      this.apiService.getCurrentWorkspaceId(),
      this.sessionType,
      idempotencyKey,
    ).subscribe({
      next: (res: ProfileResponse) => {
        clearInterval(progressInterval);
        if (attempt !== this.uploadAttempt) return;
        this.uploadProgress = 100;
        if (res?.status === 'REJECT' || res?.profile?.validation?.status === 'REJECT') {
          const message = res?.error || res?.profile?.validation?.errors?.join('; ') || 'Tệp CSV không đạt yêu cầu kiểm tra.';
          this.uploadStatus = 'error';
          this.errorMessage = message;
          this.ingestionState.setErrorMessage(message);
          return;
        }
        this.profileResult = res;
        this.uploadStatus = 'profiled';
        this.ingestionState.setDatasetStatus('profiling', 'Tệp đã được kiểm tra. Cần xác nhận ánh xạ cột trước khi nhập dữ liệu.');

        if (res.sessionId) {
          this.ingestionState.setSessionId(res.sessionId);
        }

        const profile = res.profile;
        if (profile) {
          const mappingData = {
            headers: profile.headers,
            sampleData: profile.previewRows ? profile.previewRows[0] : null,
            aiSuggestions: {
              sku_column_index: profile.headers.indexOf(profile.skuColumnDetected),
              record_date_column_index: profile.headers.indexOf(profile.dateColumnDetected),
              confidence: 'High (Streaming CSV Profiler)'
            }
          };
          this.ingestionState.setMappingData(mappingData);
        }

        if (res.idempotent_retry) {
          this.showIdempotentModal = true;
        }
      },
      error: (err: any) => {
        clearInterval(progressInterval);
        if (attempt !== this.uploadAttempt) return;
        this.uploadStatus = 'error';
        const msg = err.error?.error || 'Có lỗi xảy ra trong quá trình nạp và phân tích tệp CSV.';
        this.errorMessage = msg;
        this.ingestionState.setErrorMessage(msg);
      }
    });
  }

  private async uploadMultipartToObjectStorage(file: File, attempt: number, defaultKey: string): Promise<void> {
    const resume = this.readMultipartResume(file);
    const idempotencyKey = resume?.idempotencyKey || defaultKey;
    this.uploadStage = 'Đang khởi tạo tải trực tiếp tới kho dữ liệu an toàn';

    this.apiService.initiateMultipartUpload(file, this.sessionType, idempotencyKey).subscribe({
      next: async (manifest: any) => {
        try {
          if (attempt !== this.uploadAttempt) return;
          const completedParts = { ...(resume?.completedParts || {}) } as Record<string, string>;
          this.writeMultipartResume(file, idempotencyKey, manifest.sessionId, manifest.uploadId, completedParts);

          for (const part of manifest.parts || []) {
            const partNumber = Number(part.partNumber);
            if (!completedParts[String(partNumber)]) {
              const start = (partNumber - 1) * Number(manifest.partSizeBytes);
              const end = Math.min(start + Number(manifest.partSizeBytes), file.size);
              const result = await fetch(part.url, {
                method: 'PUT',
                body: file.slice(start, end),
              });
              const eTag = result.headers.get('ETag') || result.headers.get('etag');
              if (!result.ok || !eTag) {
                throw new Error('Kho dữ liệu từ chối một phần tệp hoặc không trả về ETag để xác nhận upload.');
              }
              completedParts[String(partNumber)] = eTag;
              this.writeMultipartResume(file, idempotencyKey, manifest.sessionId, manifest.uploadId, completedParts);
            }
            const completedCount = Object.keys(completedParts).length;
            this.uploadProgress = Math.max(8, Math.round((completedCount / manifest.parts.length) * 92));
            this.uploadStage = `Đã tải ${completedCount}/${manifest.parts.length} phần; có thể tiếp tục nếu kết nối bị gián đoạn`;
          }

          const parts = Object.entries(completedParts).map(([partNumber, eTag]) => ({
            partNumber: Number(partNumber),
            eTag,
          })).sort((a, b) => a.partNumber - b.partNumber);
          this.uploadStage = 'Đang xác nhận tệp và đưa vào hàng chờ xử lý';
          this.apiService.completeMultipartUpload(manifest.sessionId, manifest.uploadId, parts).subscribe({
            next: (result: any) => {
              if (attempt !== this.uploadAttempt) return;
              this.clearMultipartResume();
              this.uploadProgress = 100;
              this.ingestionState.setSessionId(result.sessionId || manifest.sessionId);
              this.ingestionState.setDatasetStatus('uploading', 'Tệp đã được xác nhận và đang xử lý trong hàng chờ.');
              this.router.navigate(['/app/queue']);
            },
            error: (err: any) => this.failMultipartUpload(attempt, err.error?.error || 'Không thể xác nhận cloud upload.'),
          });
        } catch (error) {
          this.failMultipartUpload(attempt, error instanceof Error ? error.message : 'Cloud upload thất bại.');
        }
      },
      error: (err: any) => {
        // Local development does not require S3. Production never reaches this
        // fallback because STORAGE_BACKEND=s3 is a deployment invariant.
        if (err.error?.code === 'S3_MULTIPART_INVALID') {
          this.enqueueBackgroundJob();
          return;
        }
        this.failMultipartUpload(attempt, err.error?.error || 'Không thể khởi tạo cloud upload.');
      }
    });
  }

  private failMultipartUpload(attempt: number, message: string): void {
    if (attempt !== this.uploadAttempt) return;
    this.uploadStatus = 'error';
    this.errorMessage = message;
    this.ingestionState.setErrorMessage(message);
  }

  private readMultipartResume(file: File): any | null {
    try {
      const value = JSON.parse(localStorage.getItem(this.multipartResumeStorageKey) || 'null');
      return value?.fileName === file.name
        && value?.fileSize === file.size
        && value?.lastModified === file.lastModified
        && value?.sessionType === this.sessionType
        ? value
        : null;
    } catch {
      return null;
    }
  }

  private writeMultipartResume(
    file: File,
    idempotencyKey: string,
    sessionId: string,
    uploadId: string,
    completedParts: Record<string, string>,
  ): void {
    try {
      // Persist ETags only; presigned URLs are short-lived credentials and are
      // intentionally regenerated by the initiate endpoint after a reload.
      localStorage.setItem(this.multipartResumeStorageKey, JSON.stringify({
        fileName: file.name,
        fileSize: file.size,
        lastModified: file.lastModified,
        sessionType: this.sessionType,
        idempotencyKey,
        sessionId,
        uploadId,
        completedParts,
      }));
    } catch {
      // Resume is best effort; inability to persist browser state must not stop upload.
    }
  }

  private clearMultipartResume(): void {
    try {
      localStorage.removeItem(this.multipartResumeStorageKey);
    } catch {
      // Browser storage is optional.
    }
  }

  enqueueBackgroundJob(): void {
    if (!this.selectedFile) return;
    this.uploadStatus = 'uploading';
    this.uploadStage = 'Đang đưa tệp vào hàng chờ xử lý';
    this.ingestionState.setDatasetStatus('uploading', this.uploadStage);
    this.apiService.enqueueUploadJob(this.selectedFile, this.apiService.getCurrentWorkspaceId(), this.sessionType).subscribe({
      next: (res: any) => {
        this.router.navigate(['/app/queue']);
      },
      error: (err: any) => {
        this.uploadStatus = 'error';
        this.errorMessage = err.error?.error || 'Không thể đưa tệp vào hàng chờ xử lý.';
      }
    });
  }

  isIdempotentRetry(): boolean {
    return !!this.profileResult?.idempotent_retry;
  }

  openIdempotentModal(): void {
    this.showIdempotentModal = true;
  }

  closeIdempotentModal(): void {
    this.showIdempotentModal = false;
  }

  resetUpload(): void {
    this.uploadAttempt++;
    this.selectedFile = null;
    this.uploadStatus = 'idle';
    this.profileResult = null;
    this.errorMessage = '';
    this.uploadProgress = 0;
    this.showIdempotentModal = false;
    this.ingestionState.reset();
    this.ingestionState.setSessionType(this.sessionType);
  }

  private createImportRequestKey(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return `csv-import-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  setSessionType(sessionType: 'INITIAL' | 'INCREMENTAL'): void {
    this.sessionType = sessionType;
    this.resetUpload();
  }

  returnToDashboard(): void {
    this.resetUpload();
    this.router.navigate(['/app/dashboard']);
  }

  proceedMapping(): void {
    if (this.isIdempotentRetry()) {
      this.showIdempotentModal = true;
      return;
    }

    if (this.selectedFile && this.profileResult) {
      this.continueToMapping.emit({
        file: this.selectedFile,
        profileData: this.profileResult,
        sessionType: this.sessionType
      });
      this.router.navigate(['/app/import/mapping']);
    }
  }

  getMissingColumnsList(): { col: string; count: number; pct: number }[] {
    if (!this.profileResult?.profile?.missingValues) return [];
    return Object.entries(this.profileResult.profile.missingValues).map(([col, data]) => ({
      col,
      count: data.count,
      pct: data.pct
    }));
  }
}
