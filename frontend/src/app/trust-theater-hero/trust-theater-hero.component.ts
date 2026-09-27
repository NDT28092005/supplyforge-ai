import { Component, EventEmitter, Output, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';

@Component({
  selector: 'app-trust-theater-hero',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './trust-theater-hero.component.html',
  styleUrls: ['./trust-theater-hero.component.css']
})
export class TrustTheaterHeroComponent {
  @Output() upload = new EventEmitter<{ file: File }>();
  @Output() openLogin = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();
  @Input() user: any = null;

  localFile: File | null = null;
  showUploadBox = false;
  isUploading = false;

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private router: Router
  ) {}

  onContactSupport(): void {
    this.navigateStage.emit('about_us');
    this.router.navigate(['/about']);
  }

  enableUpload(): void {
    this.showUploadBox = true;
  }

  fileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.localFile = input.files[0];
    }
  }

  removeFile(): void {
    this.localFile = null;
  }

  onUpload(): void {
    if (!this.localFile) return;

    this.upload.emit({ file: this.localFile });
    this.isUploading = true;
    this.ingestionState.setFile(this.localFile);
    this.ingestionState.setErrorMessage('');

    // Navigate to processing screen immediately so user sees step progress
    this.router.navigate(['/app/import/processing']);

    this.apiService.uploadCsvV2(this.localFile, 1, 'INITIAL').subscribe({
      next: (res: any) => {
        this.isUploading = false;
        if (res?.sessionId) {
          this.ingestionState.setSessionId(res.sessionId);
        }

        if (res?.status === 'REJECT' || res?.profile?.validation?.status === 'REJECT') {
          const errorMsg = res?.error || res?.profile?.validation?.errors?.join('; ') || 'Tệp CSV không hợp lệ hoặc bị hệ thống từ chối.';
          this.ingestionState.setErrorMessage(errorMsg);
          this.router.navigate(['/app/import']);
          return;
        }

        const profile = res?.profile;
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
        } else {
          this.ingestionState.setErrorMessage('Không nhận diện được cấu trúc tệp CSV.');
          this.router.navigate(['/app/import']);
        }
      },
      error: (err: any) => {
        this.isUploading = false;
        const errorMsg = err.error?.error || 'Tệp CSV không hợp lệ (sai mã hóa, trùng cột, thiếu header hoặc rỗng).';
        this.ingestionState.setErrorMessage(errorMsg);
        this.router.navigate(['/app/import']);
      }
    });
  }

  getFileSizeKb(file: File | null): string {
    if (!file) return '0.0';
    return (file.size / 1024).toFixed(1);
  }
}
