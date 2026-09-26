import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { StepItem } from '../step-item';

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

  progress = 10;
  stepIndex = 0;
  private timerIds: any[] = [];

  steps: (StepItem & { percentage?: number })[] = [
    { label: 'Tải tệp dữ liệu lên hệ thống', duration: 400, percentage: 100 },
    { label: 'Kiểm tra cấu trúc CSV', duration: 500, percentage: 100 },
    { label: 'Làm sạch & Tách lọc dòng lỗi', duration: 600, percentage: 80 },
    { label: 'Bóc tách trùng lặp', duration: 600, percentage: 60 },
    { label: 'Đồng bộ cơ sở dữ liệu & Tạo phân tích', duration: 500, percentage: 20 }
  ];

  ngOnInit(): void {
    this.runAnalysis();
  }

  ngOnDestroy(): void {
    this.clearTimers();
  }

  clearTimers(): void {
    this.timerIds.forEach(id => clearTimeout(id));
    this.timerIds = [];
  }

  runAnalysis(): void {
    const t1 = setTimeout(() => {
      this.progress = 30;
      this.stepIndex = 1;
      const t2 = setTimeout(() => {
        this.progress = 60;
        this.stepIndex = 2;
        const t3 = setTimeout(() => {
          this.progress = 85;
          this.stepIndex = 3;
          const t4 = setTimeout(() => {
            this.progress = 100;
            this.stepIndex = 4;
            const t5 = setTimeout(() => {
              this.mappingReady.emit({ data: null });
            }, 400);
            this.timerIds.push(t5);
          }, 500);
          this.timerIds.push(t4);
        }, 600);
        this.timerIds.push(t3);
      }, 600);
      this.timerIds.push(t2);
    }, 400);
    this.timerIds.push(t1);
  }

  onCancel(): void {
    this.clearTimers();
    this.cancelImport.emit();
  }
}
