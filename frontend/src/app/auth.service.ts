import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private tokenKey = 'sf_auth_token';

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
    // Ưu tiên lấy từ cookie bảo mật, fallback về sessionStorage cho phiên hiện tại
    return this.getCookie(this.tokenKey) || sessionStorage.getItem(this.tokenKey);
  }

  setToken(token: string): void {
    this.setCookie(this.tokenKey, token, 1); // Lưu cookie 1 ngày
    sessionStorage.setItem(this.tokenKey, token); // Lưu vào session storage bảo mật
  }

  clearToken(): void {
    this.eraseCookie(this.tokenKey);
    sessionStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.tokenKey);
  }
}
