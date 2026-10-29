import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, interval, of } from 'rxjs';
import { switchMap, takeWhile, catchError } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface StageStatus {
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  progress: number;
}

export interface BackgroundJobDto {
  jobId: string;
  jobType: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCEL_REQUESTED' | 'CANCELLED';
  currentStage: string;
  progressPct: number;
  stages?: { [stageName: string]: StageStatus };
  estimatedTimeRemaining?: number | null;
  retryCount: number;
  file: {
    originalFilename: string;
    fileSizeBytes: number;
  };
  createdAt: string;
  updatedAt?: string;
  completedAt?: string | null;
  errorMessage?: string | null;
  resultSummary?: any;
}

@Injectable({
  providedIn: 'root'
})
export class JobQueueService {
  private apiUrl = (typeof window !== 'undefined' && (window as any).__SUPPLYFORGE_API_URL__)
    || environment.apiUrl
    || 'https://supplyforge-ai-backend.onrender.com';

  constructor(private http: HttpClient) {}

  uploadAndEnqueueJob(file: File, workspaceId: number = 1): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspaceId', workspaceId.toString());

    return this.http.post<any>(`${this.apiUrl}/api/v2/jobs/upload`, formData);
  }

  getJobsList(activeOnly: boolean = false): Observable<{ jobs: BackgroundJobDto[] }> {
    const suffix = activeOnly ? '?active_only=true' : '';
    return this.http.get<{ jobs: BackgroundJobDto[] }>(`${this.apiUrl}/api/v2/jobs/${suffix}`).pipe(
      catchError(err => {
        console.error('Error fetching jobs:', err);
        return of({ jobs: [] });
      })
    );
  }

  getJobStatus(jobId: string): Observable<BackgroundJobDto> {
    return this.http.get<BackgroundJobDto>(`${this.apiUrl}/api/v2/jobs/${jobId}/status`);
  }

  cancelJob(jobId: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/api/v2/jobs/${jobId}/cancel`, {});
  }

  retryJob(jobId: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/api/v2/jobs/${jobId}/retry`, {});
  }

  deleteJob(jobId: string): Observable<any> {
    return this.http.delete<any>(`${this.apiUrl}/api/v2/jobs/${jobId}`);
  }

  pollJobStatus(jobId: string, intervalMs: number = 3000): Observable<BackgroundJobDto> {
    return interval(intervalMs).pipe(
      switchMap(() => this.getJobStatus(jobId)),
      takeWhile(job => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status), true)
    );
  }
}
