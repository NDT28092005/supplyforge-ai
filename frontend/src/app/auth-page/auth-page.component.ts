import { Component, Output, EventEmitter, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { AuthService } from '../auth.service';

@Component({
  selector: 'app-auth-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './auth-page.component.html',
  styleUrls: ['./auth-page.component.css']
})
export class AuthPageComponent implements OnInit {
  @Input() initialTab: 'login' | 'register' = 'login';
  @Output() loginSuccess = new EventEmitter<{ name: string; email: string; storeName?: string }>();
  @Output() demoLogin = new EventEmitter<void>();
  @Output() googleLogin = new EventEmitter<void>();
  @Output() goBack = new EventEmitter<void>();

  activeTab: 'login' | 'register' = 'login';
  loading = false;
  showPassword = false;
  successMessage = '';
  errorMessage = '';

  loginForm = {
    email: '',
    password: '',
    rememberMe: true
  };

  registerForm = {
    fullName: '',
    storeName: '',
    email: '',
    phone: '',
    password: '',
    confirmPassword: ''
  };

  constructor(
    private apiService: ApiService,
    private authService: AuthService,
    private router: Router
  ) { }

  ngOnInit(): void {
    this.activeTab = this.initialTab;
  }

  switchTab(tab: 'login' | 'register'): void {
    this.activeTab = tab;
    this.errorMessage = '';
    this.successMessage = '';
  }

  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  onLogin(): void {
    this.errorMessage = '';
    if (!this.loginForm.email || !this.loginForm.password) {
      this.errorMessage = 'Vui lòng nhập đầy đủ email và mật khẩu.';
      return;
    }

    if (!this.isValidEmail(this.loginForm.email)) {
      this.errorMessage = 'Email không đúng định dạng. Vui lòng kiểm tra lại.';
      return;
    }

    this.loading = true;

    this.apiService.loginUser(this.loginForm.email, this.loginForm.password).subscribe({
      next: (res: any) => {
        this.loading = false;
        if (res.token) {
          this.authService.setToken(res.token);
        }
        const userName = res.user?.name || this.loginForm.email.split('@')[0];
        const userObj = {
          name: userName,
          email: res.user?.email || this.loginForm.email
        };
        this.authService.setCurrentUser(userObj);
        this.loginSuccess.emit(userObj);
        this.router.navigate(['/app/dashboard']);
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Email hoặc mật khẩu không chính xác.';
      }
    });
  }

  onRegister(): void {
    this.errorMessage = '';

    if (!this.registerForm.fullName || !this.registerForm.email || !this.registerForm.password) {
      this.errorMessage = 'Vui lòng điền đầy đủ họ tên, email và mật khẩu.';
      return;
    }

    if (!this.isValidEmail(this.registerForm.email)) {
      this.errorMessage = 'Email không đúng định dạng. Vui lòng kiểm tra lại.';
      return;
    }

    if (this.registerForm.password.length < 6) {
      this.errorMessage = 'Mật khẩu phải có ít nhất 6 ký tự.';
      return;
    }

    if (this.registerForm.password !== this.registerForm.confirmPassword) {
      this.errorMessage = 'Mật khẩu xác nhận không khớp. Vui lòng nhập lại.';
      return;
    }

    if (this.registerForm.phone && !this.isValidPhone(this.registerForm.phone)) {
      this.errorMessage = 'Số điện thoại không hợp lệ (tối thiểu 9 số).';
      return;
    }

    this.loading = true;
    const shopName = this.registerForm.storeName || this.registerForm.fullName;

    this.apiService.registerUser(
      this.registerForm.email,
      this.registerForm.password,
      shopName,
      this.registerForm.phone
    ).subscribe({
      next: (res: any) => {
        this.loading = false;
        this.successMessage = 'Tạo tài khoản thành công! Đang đăng nhập...';

        setTimeout(() => {
          this.apiService.loginUser(this.registerForm.email, this.registerForm.password).subscribe({
            next: (loginRes: any) => {
              if (loginRes.token) {
                this.authService.setToken(loginRes.token);
              }
              const userObj = {
                name: this.registerForm.fullName,
                email: this.registerForm.email,
                storeName: this.registerForm.storeName || undefined
              };
              this.authService.setCurrentUser(userObj);
              this.loginSuccess.emit(userObj);
              this.router.navigate(['/app/dashboard']);
            },
            error: () => {
              this.router.navigate(['/app/dashboard']);
            }
          });
        }, 800);
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Đăng ký thất bại. Email hoặc SĐT có thể đã được sử dụng.';
      }
    });
  }

  onDemoLogin(): void {
    this.apiService.loginUser('demo@supplyforge.ai', 'demo123').subscribe({
      next: (res: any) => {
        if (res.token) {
          this.authService.setToken(res.token);
        }
        this.demoLogin.emit();
        this.router.navigate(['/app/dashboard']);
      },
      error: () => {
        this.demoLogin.emit();
        this.router.navigate(['/app/dashboard']);
      }
    });
  }

  onGoogleLogin(): void {
    const googleWin = window as any;
    if (typeof googleWin !== 'undefined' && googleWin.google?.accounts?.id) {
      googleWin.google.accounts.id.initialize({
        client_id: '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com',
        callback: (response: any) => this.handleGoogleCredentialResponse(response)
      });
      googleWin.google.accounts.id.prompt((notification: any) => {
        if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
          this.triggerGoogleRedirectFallback();
        }
      });
    } else {
      this.triggerGoogleRedirectFallback();
    }
  }

  private triggerGoogleRedirectFallback(): void {
    const clientId = '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com';
    const redirectUri = 'http://localhost:8080/api/auth/google/callback';
    const scope = 'openid email profile';
    const nonce = 'supplyforge_' + Date.now();

    const googleAuthUrl = `https://accounts.google.com/o/oauth2/v2/auth?` +
      `client_id=${encodeURIComponent(clientId)}&` +
      `redirect_uri=${encodeURIComponent(redirectUri)}&` +
      `response_type=id_token&` +
      `scope=${encodeURIComponent(scope)}&` +
      `nonce=${encodeURIComponent(nonce)}&` +
      `response_mode=form_post&` +
      `prompt=select_account`;

    console.info(`[Google OAuth] Redirecting browser to Google OAuth: ${googleAuthUrl}`);
    window.location.href = googleAuthUrl;
  }

  private handleGoogleCredentialResponse(response: any): void {
    if (!response || !response.credential) return;
    this.loading = true;
    this.apiService.completeGoogleLogin(response.credential).subscribe({
      next: (res: any) => {
        this.loading = false;
        if (res.token) {
          this.authService.setToken(res.token);
        }
        const userName = res.user?.name || res.user?.email?.split('@')[0] || 'Google User';
        const userObj = {
          name: userName,
          email: res.user?.email
        };
        this.authService.setCurrentUser(userObj);
        this.loginSuccess.emit(userObj);
        this.router.navigate(['/app/dashboard']);
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Xác thực Google không thành công.';
      }
    });
  }

  onFacebookLogin(): void {
    this.onGoogleLogin();
  }

  onGoBack(): void {
    this.goBack.emit();
    this.router.navigate(['/']);
  }

  private isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  private isValidPhone(phone: string): boolean {
    return /^[0-9]{9,15}$/.test(phone.replace(/[\s\-\+]/g, ''));
  }
}
