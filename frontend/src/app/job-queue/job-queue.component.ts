import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { JobQueueService, BackgroundJobDto } from '../services/job-queue.service';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';

@Component({
  selector: 'app-job-queue',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './job-queue.component.html',
  styleUrls: ['./job-queue.component.css']
})
export class JobQueueComponent implements OnInit, OnDestroy {
  jobs: BackgroundJobDto[] = [];
  activeJobs: BackgroundJobDto[] = [];
  completedJobs: BackgroundJobDto[] = [];
  isLoading = false;
  errorMessage: string | null = null;
  private pollSub?: Subscription;

  stageLabels: { [key: string]: string } = {
    'PARSING': 'Đọc & kiểm tra file',
    'PROFILING': 'Phân tích cấu trúc dữ liệu',
    'MAPPING': 'Nhận diện cột dữ liệu',
    'IMPORTING': 'Nhập dữ liệu vào hệ thống',
    'ML_INFERENCE': 'AI Đánh giá rủi ro tồn kho',
    'FINALIZING': 'Hoàn tất & Cập nhật báo cáo'
  };

  constructor(private jobQueueService: JobQueueService) {}

  ngOnInit(): void {
    this.loadJobs();
    this.startPolling();
  }

  ngOnDestroy(): void {
    if (this.pollSub) {
      this.pollSub.unsubscribe();
    }
  }

  loadJobs(): void {
    this.isLoading = true;
    this.jobQueueService.getJobsList().subscribe({
      next: (res) => {
        this.jobs = res.jobs || [];
        this.categorizeJobs();
        this.isLoading = false;
      },
      error: (err) => {
        this.errorMessage = 'Không thể tải danh sách hàng chờ xử lý.';
        this.isLoading = false;
      }
    });
  }

  categorizeJobs(): void {
    this.activeJobs = this.jobs.filter(j => ['PENDING', 'RUNNING', 'CANCEL_REQUESTED'].includes(j.status));
    this.completedJobs = this.jobs.filter(j => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status));
  }

  startPolling(): void {
    this.pollSub = interval(3000).pipe(
      switchMap(() => this.jobQueueService.getJobsList())
    ).subscribe({
      next: (res) => {
        this.jobs = res.jobs || [];
        this.categorizeJobs();
      }
    });
  }

  onCancelJob(jobId: string): void {
    if (confirm('Bạn có chắc chắn muốn hủy tiến trình xử lý này?')) {
      this.jobQueueService.cancelJob(jobId).subscribe({
        next: () => this.loadJobs(),
        error: (err) => alert('Không thể gửi yêu cầu hủy job: ' + (err.error?.message || err.message))
      });
    }
  }

  onRetryJob(jobId: string): void {
    this.jobQueueService.retryJob(jobId).subscribe({
      next: () => this.loadJobs(),
      error: (err) => alert('Không thể retry job: ' + (err.error?.message || err.message))
    });
  }

  onDeleteJob(jobId: string): void {
    if (confirm('Xóa thông tin công việc này khỏi nhật ký?')) {
      this.jobQueueService.deleteJob(jobId).subscribe({
        next: () => this.loadJobs(),
        error: (err) => alert('Không thể xóa job: ' + (err.error?.message || err.message))
      });
    }
  }

  formatBytes(bytes: number): string {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  get completedCount(): number {
    return this.completedJobs.filter(j => j.status === 'COMPLETED').length;
  }

  get failedCount(): number {
    return this.completedJobs.filter(j => ['FAILED', 'CANCELLED'].includes(j.status)).length;
  }

  getStageLabel(stage: string): string {
    return this.stageLabels[stage] || stage || 'Đang xử lý';
  }
}

