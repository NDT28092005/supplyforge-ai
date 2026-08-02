import { Component, Input, Output, EventEmitter, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { StepItem } from '../step-item';

@Component({
  selector: 'app-processing-screen',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './processing-screen.component.html',
  styleUrls: ['./processing-screen.component.css']
})
export class ProcessingScreenComponent implements OnInit {
  @Input() file: File | null = null;
  @Output() mappingReady = new EventEmitter<{ data: any }>();

  progress = 10;
  stepIndex = 0;

  steps: StepItem[] = [
    { label: 'Đang tải file lên server...', duration: 500 },
    { label: 'Mapping cột dữ liệu bằng Gemini...', duration: 800 },
    { label: 'Phân tích dòng tiền và tồn kho...', duration: 1000 },
    { label: 'Kiểm tra SKU trùng lặp...', duration: 700 },
    { label: 'Hoàn tất báo cáo...', duration: 500 }
  ];

  ngOnInit(): void {
    this.runAnalysis();
  }

  runAnalysis(): void {
    setTimeout(() => {
      this.progress = 40;
      this.stepIndex = 1;
      setTimeout(() => {
        this.progress = 75;
        this.stepIndex = 2;
        setTimeout(() => {
          this.progress = 100;
          this.stepIndex = 4;
          setTimeout(() => {
            this.mappingReady.emit({ data: null });
          }, 500);
        }, 800);
      }, 1000);
    }, 800);
  }
}
