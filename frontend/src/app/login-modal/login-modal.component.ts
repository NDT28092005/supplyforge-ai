import { Component, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../auth.service';
import { ApiService } from '../api.service';

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

  constructor(
    private authService: AuthService,
    private apiService: ApiService,
  ) {}

  closeModal(): void {
    this.close.emit();
  }

  onSubmit(): void {
    if (!this.loginForm.email || !this.loginForm.password) return;

    this.loading = true;
    this.apiService.loginUser(this.loginForm.email, this.loginForm.password).subscribe({
      next: (response: any) => {
        this.loading = false;
        if (!response?.access_token) return;
        this.authService.setSession(response.access_token, response.user);
        this.loginSuccess.emit({
          name: response.user?.name || this.loginForm.email.split('@')[0],
          email: response.user?.email || this.loginForm.email,
        });
        this.closeModal();
      },
      error: () => { this.loading = false; },
    });
  }

  onGoogleLogin(): void {
    window.location.assign(`${this.apiService.getApiUrl()}/api/v1/auth/google/start`);
  }
}
