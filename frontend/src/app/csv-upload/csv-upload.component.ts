import { Component, EventEmitter, Output, Input, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';

export interface ProfileResponse {
  sessionId: string;
  status: string;
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
  imports: [CommonModule, FormsModule],
  templateUrl: './csv-upload.component.html',
  styleUrls: ['./csv-upload.component.css']
})
export class CsvUploadComponent implements OnInit, OnChanges {
  @Input() initialErrorMessage = '';
  @Input() initialFile: File | null = null;
  @Output() continueToMapping = new EventEmitter<{ file: File; profileData: ProfileResponse; sessionType: 'INITIAL' | 'INCREMENTAL' }>();

  isDragging = false;
  selectedFile: File | null = null;
  sessionType: 'INITIAL' | 'INCREMENTAL' = 'INITIAL';

  // Status state: 'idle' | 'uploading' | 'profiled' | 'error'
  uploadStatus: 'idle' | 'uploading' | 'profiled' | 'error' = 'idle';
  uploadProgress = 0;
  errorMessage = '';
  profileResult: ProfileResponse | null = null;

  // Idempotency Duplicate Retry Modal State (IR-020)
  showIdempotentModal = false;

  // Format guide and sample download state
  showFormatGuide = false;

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

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    this.applyInitialInputs();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['initialErrorMessage'] || changes['initialFile']) {
      this.applyInitialInputs();
    }
  }

  private applyInitialInputs(): void {
    if (this.initialFile) {
      this.selectedFile = this.initialFile;
    }
    if (this.initialErrorMessage) {
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
    if (!file.name.toLowerCase().endsWith('.csv')) {
      this.errorMessage = 'Chỉ hỗ trợ tệp định dạng .csv. Vui lòng kiểm tra lại.';
      this.uploadStatus = 'error';
      return;
    }

    this.selectedFile = file;
    this.errorMessage = '';
    this.uploadStatus = 'uploading';
    this.uploadProgress = 15;

    // Simulate progress while uploading and streaming
    const progressInterval = setInterval(() => {
      if (this.uploadProgress < 85) {
        this.uploadProgress += 10;
      }
    }, 200);

    this.apiService.uploadCsvV2(file, 1, this.sessionType).subscribe({
      next: (res: ProfileResponse) => {
        clearInterval(progressInterval);
        this.uploadProgress = 100;
        this.profileResult = res;
        this.uploadStatus = 'profiled';

        if (res.idempotent_retry) {
          this.showIdempotentModal = true;
        }
      },
      error: (err: any) => {
        clearInterval(progressInterval);
        this.uploadStatus = 'error';
        this.errorMessage = err.error?.error || 'Có lỗi xảy ra trong quá trình nạp và phân tích tệp CSV.';
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
    this.selectedFile = null;
    this.uploadStatus = 'idle';
    this.profileResult = null;
    this.errorMessage = '';
    this.uploadProgress = 0;
    this.showIdempotentModal = false;
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
