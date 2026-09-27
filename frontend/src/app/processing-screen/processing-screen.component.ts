import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { StepItem } from '../step-item';
import { IngestionStateService } from '../core/state/ingestion-state.service';

@Component({
  selector: 'app-processing-screen',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './processing-screen.component.html',
  styleUrls: ['./processing-screen.component.css']
})
export class ProcessingScreenComponent implements OnInit, OnDestroy {
  @Input() file: File | null = null;
  @Input() sessionId: string = '';
  @Output() mappingReady = new EventEmitter<{ data: any }>();
  @Output() cancelImport = new EventEmitter<void>();

  progress = 15;
  stepIndex = 0;
  isCompleted = false;
  private timerId: any = null;
  private safetyTimerId: any = null;
  private stateSub?: Subscription;

  steps: (StepItem & { percentage?: number })[] = [
    { label: 'Tải tệp dữ liệu lên hệ thống', duration: 400, percentage: 100 },
    { label: 'Kiểm tra cấu trúc CSV', duration: 500, percentage: 100 },
    { label: 'Làm sạch & Tách lọc dòng lỗi', duration: 600, percentage: 80 },
    { label: 'Bóc tách trùng lặp', duration: 600, percentage: 60 },
    { label: 'Đồng bộ cơ sở dữ liệu & Tạo phân tích', duration: 500, percentage: 20 }
  ];

  constructor(
    private ingestionState: IngestionStateService,
    private router: Router
  ) {}

  ngOnInit(): void {
    if (!this.file) {
      this.file = this.ingestionState.state.uploadFile;
    }
    if (!this.sessionId) {
      this.sessionId = this.ingestionState.state.activeSessionId;
    }
    this.runAnalysis();
  }

  ngOnDestroy(): void {
    this.stopTimer();
    if (this.stateSub) {
      this.stateSub.unsubscribe();
    }
  }

  stopTimer(): void {
    if (this.timerId) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    if (this.safetyTimerId) {
      clearTimeout(this.safetyTimerId);
      this.safetyTimerId = null;
    }
  }

  runAnalysis(): void {
    this.progress = 15;
    this.stepIndex = 0;
    this.isCompleted = false;

    // Smooth interval-based progress animation
    this.timerId = setInterval(() => {
      if (this.isCompleted) {
        this.stopTimer();
        return;
      }

      if (this.progress < 35) {
        this.progress += 5;
        this.stepIndex = 0;
      } else if (this.progress < 60) {
        this.progress += 5;
        this.stepIndex = 1;
      } else if (this.progress < 80) {
        this.progress += 4;
        this.stepIndex = 2;
      } else if (this.progress < 92) {
        this.progress += 2;
        this.stepIndex = 3;
      } else {
        this.progress = 92;
        this.stepIndex = 4;
      }

      this.checkState();
    }, 200);

    // Subscribe to state updates
    this.stateSub = this.ingestionState.stateObservable.subscribe(state => {
      if (state.uploadErrorMessage) {
        this.stopTimer();
        if (this.router.url === '/app/import/processing') {
          this.router.navigate(['/app/import']);
        }
      } else if (state.mappingData) {
        this.finishSuccess(state.mappingData);
      }
    });

    // Safety timeout: If no state arrives within 10s, fallback to upload route
    this.safetyTimerId = setTimeout(() => {
      if (!this.isCompleted && !this.ingestionState.state.mappingData) {
        this.stopTimer();
        if (this.router.url === '/app/import/processing') {
          this.router.navigate(['/app/import']);
        }
      }
    }, 10000);

    // Immediate check on initialization
    this.checkState();
  }

  private checkState(): void {
    if (this.isCompleted) return;
    const state = this.ingestionState.state;
    if (state.uploadErrorMessage) {
      this.stopTimer();
      if (this.router.url === '/app/import/processing') {
        this.router.navigate(['/app/import']);
      }
    } else if (state.mappingData) {
      this.finishSuccess(state.mappingData);
    }
  }

  private finishSuccess(mappingData: any): void {
    if (this.isCompleted) return;
    this.isCompleted = true;
    this.stopTimer();

    this.progress = 100;
    this.stepIndex = 5;

    setTimeout(() => {
      this.mappingReady.emit({ data: mappingData });
      if (this.router.url === '/app/import/processing') {
        this.router.navigate(['/app/import/mapping']);
      }
    }, 300);
  }

  onCancel(): void {
    this.isCompleted = true;
    this.stopTimer();
    this.cancelImport.emit();
    if (this.router.url === '/app/import/processing') {
      this.router.navigate(['/app/import']);
    }
  }
}
