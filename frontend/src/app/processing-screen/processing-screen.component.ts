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
    { label: 'Đang tải file dữ liệu lên hệ thống...', duration: 500 },
    { label: 'Đang kiểm tra và nhận diện các cột...', duration: 800 },
    { label: 'Đang tính toán số liệu tồn kho & doanh số...', duration: 1000 },
    { label: 'Đang chuẩn hóa danh sách sản phẩm...', duration: 700 },
    { label: 'Hoàn tất kiểm tra dữ liệu...', duration: 500 }
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
