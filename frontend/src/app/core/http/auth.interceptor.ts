import { HttpBackend, HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, map, Observable, shareReplay, switchMap, throwError } from 'rxjs';
import { AuthService } from '../../auth.service';
import { environment } from '../../../environments/environment';

let refreshRequest$: Observable<string> | null = null;

const PUBLIC_AUTH_PATHS = new Set([
  '/api/auth/register',
  '/api/v1/auth/register',
  '/api/auth/verify-email',
  '/api/v1/auth/verify-email',
  '/api/auth/resend-verification',
  '/api/v1/auth/resend-verification',
  '/api/auth/login',
  '/api/v1/auth/login',
  '/api/auth/forgot-password',
  '/api/v1/auth/forgot-password',
  '/api/auth/reset-password',
  '/api/v1/auth/reset-password',
  '/api/auth/refresh',
  '/api/v1/auth/refresh'
]);

function isPublicRequest(url: string): boolean {
  const pathname = new URL(url, typeof window === 'undefined' ? 'http://localhost' : window.location.origin).pathname;
  return PUBLIC_AUTH_PATHS.has(pathname)
    || pathname.startsWith('/api/auth/google/')
    || pathname.startsWith('/api/v1/auth/google/')
    || pathname === '/api/v1/ping'
    || pathname === '/api/v1/about_us'
    || pathname === '/api/v1/services'
    || pathname.startsWith('/api/v1/blog');
}

function apiBaseUrl(): string {
  return (typeof window !== 'undefined' && (window as any).__SUPPLYFORGE_API_URL__)
    || environment.apiUrl
    || 'https://supplyforge-ai-backend.onrender.com';
}

/** Adds the active tenant JWT to protected SupplyForge API requests. */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);
  const rawHttp = new HttpClient(inject(HttpBackend));
  const token = authService.getToken();
  const isPublic = isPublicRequest(request.url);

  if (!token || isPublic || !request.url.includes('/api/')) {
    return next(request);
  }

  const authorizedRequest = request.clone({
    setHeaders: { Authorization: `Bearer ${token}` }
  });

  return next(authorizedRequest).pipe(
    catchError((error: HttpErrorResponse) => {
      const code = error?.error?.code;
      const wasRetried = request.headers.has('X-SupplyForge-Session-Retry');
      // A restarted backend can reject an old access token before its client-side
      // expiry. The refresh token remains the authoritative way to recover a session.
      const isRefreshableSession = error.status === 401 && ['EXPIRED_TOKEN', 'INVALID_TOKEN'].includes(code);
      const canRefresh = isRefreshableSession && !wasRetried && !!authService.getRefreshToken();

      if (!isRefreshableSession || wasRetried) {
        return throwError(() => error);
      }

      if (!canRefresh) {
        authService.clearToken();
        router.navigate(['/auth'], {
          queryParams: {
            reason: 'session_expired',
            returnUrl: router.url
          }
        });
        return throwError(() => error);
      }

      if (!refreshRequest$) {
        const refreshToken = authService.getRefreshToken()!;
        refreshRequest$ = rawHttp.post<any>(`${apiBaseUrl()}/api/v1/auth/refresh`, {
          refresh_token: refreshToken
        }).pipe(
          map((response) => {
            const accessToken = response?.access_token || response?.token;
            if (!accessToken) {
              throw new Error('Không nhận được access token mới.');
            }
            authService.setSession(accessToken, response?.refresh_token || refreshToken);
            return accessToken;
          }),
          finalize(() => { refreshRequest$ = null; }),
          shareReplay({ bufferSize: 1, refCount: false })
        );
      }

      return refreshRequest$.pipe(
        catchError((refreshError) => {
          authService.clearToken();
          router.navigate(['/auth'], {
            queryParams: {
              reason: 'session_expired',
              returnUrl: router.url
            }
          });
          return throwError(() => refreshError);
        }),
        switchMap((accessToken) => next(request.clone({
          setHeaders: {
            Authorization: `Bearer ${accessToken}`,
            'X-SupplyForge-Session-Retry': '1'
          }
        })))
      );
    })
  );
};
