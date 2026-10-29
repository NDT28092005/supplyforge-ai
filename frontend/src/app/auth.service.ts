import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface UserProfile {
  name: string;
  email: string;
  avatar?: string;
  role?: string;
  permissions?: { [key: string]: boolean };
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private tokenKey = 'sf_auth_token';
  private refreshTokenKey = 'sf_refresh_token';
  private currentUserSubject = new BehaviorSubject<UserProfile | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor() {
    this.loadUserFromToken();
  }

  private setCookie(name: string, value: string, days = 1): void {
    let expires = '';
    if (days) {
      const date = new Date();
      date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
      expires = '; expires=' + date.toUTCString();
    }
    const secureFlag = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = name + '=' + (value || '') + expires + `; path=/; SameSite=Lax${secureFlag}`;
  }

  private getCookie(name: string): string | null {
    const nameEQ = name + '=';
    const ca = document.cookie.split(';');
    for (let i = 0; i < ca.length; i++) {
      let c = ca[i];
      while (c.charAt(0) === ' ') c = c.substring(1, c.length);
      if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
    }
    return null;
  }

  private eraseCookie(name: string): void {
    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT; SameSite=Lax;';
  }

  getToken(): string | null {
    return localStorage.getItem(this.tokenKey) || sessionStorage.getItem(this.tokenKey) || this.getCookie(this.tokenKey);
  }

  setToken(token: string): void {
    if (!token) return;
    localStorage.setItem(this.tokenKey, token);
    sessionStorage.setItem(this.tokenKey, token);
    this.setCookie(this.tokenKey, token, 1);
    this.loadUserFromToken();
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(this.refreshTokenKey) || sessionStorage.getItem(this.refreshTokenKey);
  }

  setSession(accessToken: string, refreshToken?: string): void {
    this.setToken(accessToken);
    if (!refreshToken) return;

    localStorage.setItem(this.refreshTokenKey, refreshToken);
    sessionStorage.setItem(this.refreshTokenKey, refreshToken);
  }

  clearToken(): void {
    this.eraseCookie(this.tokenKey);
    sessionStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.tokenKey);
    sessionStorage.removeItem(this.refreshTokenKey);
    localStorage.removeItem(this.refreshTokenKey);
    sessionStorage.removeItem('sf_user_profile');
    localStorage.removeItem('sf_user_profile');
    this.currentUserSubject.next(null);
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  getCurrentUser(): UserProfile | null {
    return this.currentUserSubject.getValue();
  }

  getUserRole(): string {
    const user = this.getCurrentUser();
    return user?.role || 'OWNER';
  }

  getWorkspaceId(): number {
    const payload = this.parseJwt(this.getToken() || '');
    const workspaceId = Number(payload?.workspace_id ?? payload?.workspaceId);
    return Number.isInteger(workspaceId) && workspaceId > 0 ? workspaceId : 1;
  }

  hasPermission(permission: string): boolean {
    const user = this.getCurrentUser();
    if (!user) return false;
    const role = (user.role || 'OWNER').toUpperCase();

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

    const allowed = rolePerms[role] || [];
    return allowed.includes(permission);
  }

  setCurrentUser(user: UserProfile | null): void {
    if (user) {
      localStorage.setItem('sf_user_profile', JSON.stringify(user));
      sessionStorage.setItem('sf_user_profile', JSON.stringify(user));
    } else {
      localStorage.removeItem('sf_user_profile');
      sessionStorage.removeItem('sf_user_profile');
    }
    this.currentUserSubject.next(user);
  }

  parseJwt(token: string): any {
    try {
      if (!token) return null;

      let cleanToken = token.trim();
      if (cleanToken.startsWith("b'") && cleanToken.endsWith("'")) {
        cleanToken = cleanToken.slice(2, -1);
      } else if (cleanToken.startsWith('b"') && cleanToken.endsWith('"')) {
        cleanToken = cleanToken.slice(2, -1);
      }

      if (!cleanToken.includes('.')) return null;
      const base64Url = cleanToken.split('.')[1];
      let base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const pad = base64.length % 4;
      if (pad) {
        if (pad === 1) return null;
        base64 += new Array(5 - pad).join('=');
      }
      const jsonPayload = decodeURIComponent(window.atob(base64).split('').map((c) => {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join(''));
      return JSON.parse(jsonPayload);
    } catch (e) {
      console.error('[Auth Debug] Lỗi giải mã JWT:', e);
      return null;
    }
  }

  loadUserFromToken(): void {
    const token = this.getToken();
    if (token) {
      const savedUserStr = localStorage.getItem('sf_user_profile') || sessionStorage.getItem('sf_user_profile');
      if (savedUserStr) {
        try {
          const userObj = JSON.parse(savedUserStr);
          this.currentUserSubject.next(userObj);
          return;
        } catch (e) {}
      }

      const payload = this.parseJwt(token);
      if (payload) {
        this.currentUserSubject.next({
          name: payload.name || payload.display_name || payload.sub?.split('@')[0] || payload.email?.split('@')[0] || 'User',
          email: payload.email || payload.sub || 'user@supplyforge.ai'
        });
      } else {
        this.currentUserSubject.next({ name: 'Chủ cửa hàng', email: 'user@supplyforge.ai' });
      }
    } else {
      this.currentUserSubject.next(null);
    }
  }
}
