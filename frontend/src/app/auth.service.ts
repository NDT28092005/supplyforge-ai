import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface UserProfile {
  name: string;
  email: string;
  avatar?: string;
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private tokenKey = 'sf_auth_token';
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
    document.cookie = name + '=' + (value || '') + expires + `; path=/; domain=localhost; SameSite=Lax${secureFlag}`;
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
    document.cookie = name + '=; Path=/; domain=localhost; Expires=Thu, 01 Jan 1970 00:00:01 GMT; SameSite=Lax;';
  }

  getToken(): string | null {
    return this.getCookie(this.tokenKey) || sessionStorage.getItem(this.tokenKey);
  }

  setToken(token: string): void {
    this.setCookie(this.tokenKey, token, 1);
    sessionStorage.setItem(this.tokenKey, token);
    this.loadUserFromToken();
  }

  clearToken(): void {
    this.eraseCookie(this.tokenKey);
    sessionStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.tokenKey);
    this.currentUserSubject.next(null);
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  getCurrentUser(): UserProfile | null {
    return this.currentUserSubject.getValue();
  }

  setCurrentUser(user: UserProfile | null): void {
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
      const payload = this.parseJwt(token);
      if (payload) {
        this.currentUserSubject.next({
          name: payload.name || payload.email?.split('@')[0] || 'User',
          email: payload.email || 'user@supplyforge.ai'
        });
      } else {
        this.currentUserSubject.next({ name: 'Demo Admin', email: 'admin@supplyforge.ai' });
      }
    } else {
      this.currentUserSubject.next(null);
    }
  }
}
