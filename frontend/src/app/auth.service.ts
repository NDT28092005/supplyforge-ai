import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { BehaviorSubject, catchError, finalize, map, Observable, of, shareReplay } from 'rxjs';
import { environment } from '../environments/environment';

export interface UserProfile {
  name: string;
  email: string;
  avatar?: string;
  role?: string;
  permissions?: { [key: string]: boolean };
  workspace_id?: number;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private accessToken: string | null = null;
  private restoreRequest$: Observable<UserProfile | null> | null = null;
  private currentUserSubject = new BehaviorSubject<UserProfile | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor(private http: HttpClient) {}

  getToken(): string | null {
    return this.accessToken;
  }

  setSession(accessToken: string, user?: UserProfile | null): void {
    if (!accessToken) return;
    this.accessToken = accessToken;
    this.setCurrentUser(user || this.userFromToken(accessToken));
  }

  clearToken(): void {
    this.accessToken = null;
    this.currentUserSubject.next(null);
  }

  isLoggedIn(): boolean {
    return !!this.accessToken;
  }

  getCurrentUser(): UserProfile | null {
    return this.currentUserSubject.getValue();
  }

  getUserRole(): string {
    return this.getCurrentUser()?.role || 'OWNER';
  }

  getWorkspaceId(): number {
    const payload = this.parseJwt(this.accessToken || '');
    const workspaceId = Number(payload?.workspace_id ?? payload?.workspaceId ?? this.getCurrentUser()?.workspace_id);
    return Number.isInteger(workspaceId) && workspaceId > 0 ? workspaceId : 1;
  }

  hasPermission(permission: string): boolean {
    const user = this.getCurrentUser();
    if (!user) return false;
    if (user.permissions && typeof user.permissions[permission] === 'boolean') {
      return user.permissions[permission];
    }
    const rolePerms: { [key: string]: string[] } = {
      OWNER: ['upload_data', 'delete_dataset', 'run_simulation', 'execute_action', 'view_financial'],
      ADMIN: ['upload_data', 'delete_dataset', 'run_simulation', 'execute_action', 'view_financial'],
      ANALYST: ['run_simulation', 'view_financial'],
      OPERATOR: ['upload_data', 'execute_action'],
      VIEWER: []
    };
    return (rolePerms[(user.role || 'OWNER').toUpperCase()] || []).includes(permission);
  }

  setCurrentUser(user: UserProfile | null): void {
    this.currentUserSubject.next(user);
  }

  /** Restore only through the HttpOnly refresh cookie after a page reload. */
  restoreSession(): Observable<UserProfile | null> {
    if (this.accessToken) return of(this.getCurrentUser());
    if (this.restoreRequest$) return this.restoreRequest$;

    const apiUrl = (typeof window !== 'undefined' && (window as any).__SUPPLYFORGE_API_URL__)
      || environment.apiUrl
      || 'https://supplyforge-ai-backend.onrender.com';
    this.restoreRequest$ = this.http.post<any>(`${apiUrl}/api/v1/auth/refresh`, {}, {
      withCredentials: true
    }).pipe(
      map((response) => {
        const token = response?.access_token;
        if (!token) throw new Error('Refresh response missing access token.');
        const user = response?.user || this.userFromToken(token);
        this.setSession(token, user);
        return user;
      }),
      catchError(() => {
        this.clearToken();
        return of(null);
      }),
      finalize(() => { this.restoreRequest$ = null; }),
      shareReplay({ bufferSize: 1, refCount: false })
    );
    return this.restoreRequest$;
  }

  parseJwt(token: string): any {
    try {
      if (!token || !token.includes('.')) return null;
      const base64Url = token.split('.')[1];
      let base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const pad = base64.length % 4;
      if (pad) base64 += '='.repeat(4 - pad);
      return JSON.parse(decodeURIComponent(window.atob(base64).split('').map((c) =>
        '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
      ).join('')));
    } catch {
      return null;
    }
  }

  private userFromToken(token: string): UserProfile | null {
    const payload = this.parseJwt(token);
    if (!payload) return null;
    return {
      name: payload.name || payload.display_name || payload.email?.split('@')[0] || 'User',
      email: payload.email || 'user@supplyforge.ai',
      role: payload.role,
      workspace_id: payload.workspace_id,
    };
  }
}
