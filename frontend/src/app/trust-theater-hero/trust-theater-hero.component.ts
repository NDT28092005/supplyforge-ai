import { Component, EventEmitter, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

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

  localFile: File | null = null;
  showUploadBox = false;

  onContactSupport(): void {
    this.navigateStage.emit('about_us');
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
    if (this.localFile) {
      this.upload.emit({ file: this.localFile });
    }
  }

  getFileSizeKb(file: File | null): string {
    if (!file) return '0.0';
    return (file.size / 1024).toFixed(1);
  }
}
