import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';

export interface ProfileResponse {
  sessionId: string;
  status: string;
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
  };
}

@Component({
  selector: 'app-csv-upload',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './csv-upload.component.html',
  styleUrls: ['./csv-upload.component.css']
})
export class CsvUploadComponent {
  @Output() continueToMapping = new EventEmitter<{ file: File; profileData: ProfileResponse }>();

  isDragging = false;
  selectedFile: File | null = null;
  sessionType: 'INITIAL' | 'INCREMENTAL' = 'INITIAL';

  // Status state: 'idle' | 'uploading' | 'profiled' | 'error'
  uploadStatus: 'idle' | 'uploading' | 'profiled' | 'error' = 'idle';
  uploadProgress = 0;
  errorMessage = '';

  profileResult: ProfileResponse | null = null;

  constructor(private apiService: ApiService) {}

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
      },
      error: (err: any) => {
        clearInterval(progressInterval);
        this.uploadStatus = 'error';
        this.errorMessage = err.error?.error || 'Có lỗi xảy ra trong quá trình nạp và phân tích tệp CSV.';
      }
    });
  }

  resetUpload(): void {
    this.selectedFile = null;
    this.uploadStatus = 'idle';
    this.profileResult = null;
    this.errorMessage = '';
    this.uploadProgress = 0;
  }

  proceedMapping(): void {
    if (this.selectedFile && this.profileResult) {
      this.continueToMapping.emit({
        file: this.selectedFile,
        profileData: this.profileResult
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
