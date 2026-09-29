import { Component, Output, EventEmitter, Input, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
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
  @Input() initialTab: 'login' | 'register' | 'verify' | 'forgot_password' | 'reset_password' = 'login';
  @Output() loginSuccess = new EventEmitter<{ name: string; email: string; storeName?: string }>();
  @Output() demoLogin = new EventEmitter<void>();
  @Output() googleLogin = new EventEmitter<void>();
  @Output() goBack = new EventEmitter<void>();

  activeTab: 'login' | 'register' | 'verify' | 'forgot_password' | 'reset_password' = 'login';
  loading = false;
  showPassword = false;
  successMessage = '';
  errorMessage = '';

  registeredEmail = '';
  verificationCode = '';
  devVerificationCode = '';

  resetEmail = '';
  resetCode = '';
  devResetCode = '';
  newPassword = '';
  confirmNewPassword = '';

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
    private router: Router,
    private route: ActivatedRoute
  ) { }

  ngOnInit(): void {
    const qTab = this.route.snapshot.queryParams['tab'] || this.route.snapshot.queryParams['mode'];
    if (qTab === 'register' || qTab === 'login' || qTab === 'verify' || qTab === 'forgot_password' || qTab === 'reset_password') {
      this.activeTab = qTab;
    } else {
      this.activeTab = this.initialTab;
    }
  }

  switchTab(tab: 'login' | 'register' | 'verify' | 'forgot_password' | 'reset_password'): void {
    this.activeTab = tab;
    this.errorMessage = '';
    this.successMessage = '';
  }

  togglePasswordVisibility(): void {
    this.showPassword = !this.showPassword;
  }

  onLogin(): void {
    this.errorMessage = '';
    this.successMessage = '';
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
        const token = res.access_token || res.token;
        if (token) {
          this.authService.setToken(token);
        }
        const userName = res.user?.name || res.user?.display_name || this.loginForm.email.split('@')[0];
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
        if (err.error?.code === 'EMAIL_NOT_VERIFIED') {
          this.registeredEmail = err.error?.email || this.loginForm.email;
          this.errorMessage = err.error?.error || 'Tài khoản chưa được xác thực. Vui lòng nhập mã xác thực email.';
          this.activeTab = 'verify';
          return;
        }
        this.errorMessage = err.error?.error || 'Email hoặc mật khẩu không chính xác.';
      }
    });
  }

  onRegister(): void {
    this.errorMessage = '';
    this.successMessage = '';

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
        this.registeredEmail = this.registerForm.email;
        this.devVerificationCode = res.verification_code || '';
        this.successMessage = res.message || 'Đăng ký thành công! Vui lòng kiểm tra mã xác thực email.';
        this.activeTab = 'verify';
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Đăng ký thất bại. Email hoặc SĐT có thể đã được sử dụng.';
      }
    });
  }

  onVerifyCode(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (!this.registeredEmail) {
      this.errorMessage = 'Thiếu thông tin email. Vui lòng thử đăng nhập hoặc đăng ký lại.';
      return;
    }

    if (!this.verificationCode || this.verificationCode.trim().length !== 6) {
      this.errorMessage = 'Vui lòng nhập đầy đủ mã xác thực 6 chữ số.';
      return;
    }

    this.loading = true;

    this.apiService.verifyEmail(this.registeredEmail, this.verificationCode.trim()).subscribe({
      next: (res: any) => {
        this.loading = false;
        const token = res.access_token || res.token;
        if (token) {
          this.authService.setToken(token);
        }

        const userName = res.user?.name || res.user?.display_name || this.registerForm.fullName || this.registeredEmail.split('@')[0];
        const userObj = {
          name: userName,
          email: res.user?.email || this.registeredEmail
        };

        this.authService.setCurrentUser(userObj);
        this.successMessage = 'Kích hoạt tài khoản thành công! Đang chuyển hướng...';
        this.loginSuccess.emit(userObj);

        setTimeout(() => {
          this.router.navigate(['/app/dashboard']);
        }, 600);
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Mã xác thực không hợp lệ hoặc đã hết hạn.';
      }
    });
  }

  onResendCode(): void {
    if (!this.registeredEmail) return;
    this.loading = true;
    this.errorMessage = '';
    this.successMessage = '';

    this.apiService.resendVerification(this.registeredEmail).subscribe({
      next: (res: any) => {
        this.loading = false;
        if (res.verification_code) {
          this.devVerificationCode = res.verification_code;
        }
        this.successMessage = res.message || 'Đã gửi lại mã xác thực thành công.';
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Không thể gửi lại mã. Vui lòng thử lại sau.';
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

  onForgotPassword(): void {
    this.errorMessage = '';
    this.successMessage = '';
    if (!this.resetEmail || !this.isValidEmail(this.resetEmail)) {
      this.errorMessage = 'Vui lòng nhập địa chỉ email hợp lệ.';
      return;
    }

    this.loading = true;

    this.apiService.forgotPassword(this.resetEmail).subscribe({
      next: (res: any) => {
        this.loading = false;
        this.devResetCode = res.dev_reset_code || '';
        this.successMessage = res.message || 'Mã khôi phục đã được gửi tới email của bạn.';
        this.activeTab = 'reset_password';
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Không tìm thấy tài khoản với email này.';
      }
    });
  }

  onResetPassword(): void {
    this.errorMessage = '';
    this.successMessage = '';

    if (!this.resetEmail || !this.resetCode || !this.newPassword) {
      this.errorMessage = 'Vui lòng điền đầy đủ email, mã xác nhận và mật khẩu mới.';
      return;
    }

    if (this.newPassword.length < 6) {
      this.errorMessage = 'Mật khẩu mới phải có ít nhất 6 ký tự.';
      return;
    }

    if (this.newPassword !== this.confirmNewPassword) {
      this.errorMessage = 'Mật khẩu xác nhận không khớp. Vui lòng nhập lại.';
      return;
    }

    this.loading = true;

    this.apiService.resetPassword(this.resetEmail, this.resetCode.trim(), this.newPassword).subscribe({
      next: (res: any) => {
        this.loading = false;
        this.successMessage = res.message || 'Đặt lại mật khẩu thành công! Vui lòng đăng nhập bằng mật khẩu mới.';
        this.loginForm.email = this.resetEmail;
        this.loginForm.password = '';
        this.activeTab = 'login';
      },
      error: (err: any) => {
        this.loading = false;
        this.errorMessage = err.error?.error || 'Mã xác nhận khôi phục không chính xác hoặc đã hết hạn.';
      }
    });
  }

  private isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  private isValidPhone(phone: string): boolean {
    return /^[0-9]{9,15}$/.test(phone.replace(/[\s\-\+]/g, ''));
  }
}
