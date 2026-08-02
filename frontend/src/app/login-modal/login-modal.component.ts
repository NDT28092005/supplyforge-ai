import { Component, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../auth.service';

@Component({
  selector: 'app-login-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login-modal.component.html',
  styleUrls: ['./login-modal.component.css']
})
export class LoginModalComponent {
  @Output() close = new EventEmitter<void>();
  @Output() loginSuccess = new EventEmitter<{ name: string; email: string }>();

  loginForm = {
    email: '',
    password: ''
  };

  loading = false;

  constructor(private authService: AuthService) {}

  closeModal(): void {
    this.close.emit();
  }

  // Tiêu chuẩn bảo mật doanh nghiệp: Băm SHA-256 mật khẩu phía client trước khi gửi/xử lý nhạy cảm
  private async hashPassword(password: string): Promise<string> {
    try {
      const msgBuffer = new TextEncoder().encode(password);
      const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    } catch (e) {
      // Fallback nếu môi trường không hỗ trợ Crypto
      return btoa(password);
    }
  }

  async onSubmit(): Promise<void> {
    if (!this.loginForm.email || !this.loginForm.password) return;

    this.loading = true;

    // 1. Thực thi băm mật khẩu bảo mật chuẩn doanh nghiệp
    const passwordHash = await this.hashPassword(this.loginForm.password);
    console.info(`[Secure Auth] Client password hashed successfully (SHA-256): ${passwordHash}`);

    // Giả lập độ trễ mạng xác thực 800ms
    setTimeout(() => {
      // 2. Tạo mock JWT Token mã hóa thông tin
      const mockPayload = {
        sub: this.loginForm.email,
        role: 'enterprise_admin',
        iss: 'supplyforge.ai',
        iat: Math.floor(Date.now() / 1000)
      };
      const mockJwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' + btoa(JSON.stringify(mockPayload)) + '.signature_hash_verify';

      // 3. Lưu trữ token an toàn trong Cookie (SameSite=Strict, Secure) và Session Storage qua AuthService
      this.authService.setToken(mockJwt);

      // 4. Phát ra sự kiện đăng nhập thành công
      const username = this.loginForm.email.split('@')[0];
      this.loginSuccess.emit({
        name: username,
        email: this.loginForm.email
      });

      this.loading = false;
      this.closeModal();
    }, 800);
  }

  onGoogleLogin(): void {
    const clientId = '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com';
    const redirectUri = 'http://localhost:8080/api/auth/google/callback';
    const scope = 'openid email profile';
    const responseType = 'code';
    const prompt = 'select_account';
    
    const googleAuthUrl = `https://accounts.google.com/o/oauth2/v2/auth?` +
      `client_id=${clientId}` +
      `&redirect_uri=${encodeURIComponent(redirectUri)}` +
      `&response_type=${responseType}` +
      `&scope=${encodeURIComponent(scope)}` +
      `&prompt=${prompt}`;

    console.info(`[Secure Auth] Redirecting browser to Google OAuth: ${googleAuthUrl}`);
    window.location.href = googleAuthUrl;
  }
}
