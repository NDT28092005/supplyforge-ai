import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';

import { HeaderComponent } from './header/header.component';
import { SidebarComponent } from './sidebar/sidebar.component';
import { LoginModalComponent } from './login-modal/login-modal.component';
import { CopilotWidgetComponent } from './copilot-widget/copilot-widget.component';

import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { IngestionStateService } from './core/state/ingestion-state.service';
import { DashboardStateService } from './core/state/dashboard-state.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    HeaderComponent,
    SidebarComponent,
    LoginModalComponent,
    CopilotWidgetComponent
  ],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent implements OnInit {
  title = 'SupplyForge AI';

  // Auth & Modal State
  isLoginOpen = false;
  requiresPhone = false;
  tempPhoneUser = { tempUserId: '', email: '', name: '', picture: '' };
  phoneNumberInput = '';
  phoneError = '';
  phoneLoading = false;

  // Clear Data Modal State
  isClearModalOpen = false;
  isClearingData = false;

  constructor(
    public apiService: ApiService,
    public authService: AuthService,
    public ingestionState: IngestionStateService,
    public dashboardState: DashboardStateService,
    public router: Router
  ) {}

  ngOnInit(): void {
    console.info('[Auth Debug] Khởi động ứng dụng với Router. URL:', window.location.href);

    const tokenMatch = window.location.href.match(/[?&]token=([^&]+)/);
    const urlToken = tokenMatch ? tokenMatch[1] : null;
    if (urlToken) {
      console.info('[Auth Debug] Phát hiện token trên URL. Tiến hành lưu trữ...');
      this.authService.setToken(urlToken);
    }

    const requiresPhoneMatch = window.location.href.match(/[?&]requires_phone=true/);
    if (requiresPhoneMatch) {
      console.info('[Auth Debug] Tài khoản Google mới, yêu cầu điền số điện thoại...');
      const tempUserIdMatch = window.location.href.match(/[?&]tempUserId=([^&]+)/);
      const emailMatch = window.location.href.match(/[?&]email=([^&]+)/);
      const nameMatch = window.location.href.match(/[?&]name=([^&]+)/);
      const pictureMatch = window.location.href.match(/[?&]picture=([^&]+)/);

      this.tempPhoneUser = {
        tempUserId: tempUserIdMatch ? tempUserIdMatch[1] : '',
        email: emailMatch ? decodeURIComponent(emailMatch[1]) : '',
        name: nameMatch ? decodeURIComponent(nameMatch[1]) : 'User',
        picture: pictureMatch ? decodeURIComponent(pictureMatch[1]) : ''
      };
      this.requiresPhone = true;
    }

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('auth_success') || urlParams.has('error') || urlParams.has('token') || urlParams.has('requires_phone')) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    this.authService.loadUserFromToken();

    // Check if database already has imported data
    this.apiService.checkData().subscribe({
      next: (res) => {
        if (res && res.hasData) {
          this.dashboardState.setHasData(true);
        }
      },
      error: (err) => console.log('Check data error:', err)
    });
  }

  get currentRoute(): string {
    return this.router.url;
  }

  get isAuthRoute(): boolean {
    return this.router.url.startsWith('/auth');
  }

  get showSidebar(): boolean {
    const isApp = this.router.url.startsWith('/app');
    const isImport = this.router.url.startsWith('/app/import');
    return isApp && !isImport;
  }

  get isImportRoute(): boolean {
    return this.router.url.startsWith('/app/import');
  }

  get isProfileRoute(): boolean {
    return this.router.url.startsWith('/app/import/profile');
  }

  // --- Ingestion Pipeline Stepper Indicators ---
  getStepStatus(stepKey: string): 'completed' | 'active' | 'pending' {
    const currentUrl = this.router.url;
    let currentOrder = 1;
    if (currentUrl.startsWith('/app/import/processing')) currentOrder = 2;
    else if (currentUrl.startsWith('/app/import/mapping')) currentOrder = 3;
    else if (currentUrl.startsWith('/app/import/profile')) currentOrder = 4;

    const stageOrder: { [key: string]: number } = {
      'csv-upload': 1,
      'processing': 2,
      'mapping': 3,
      'dataset-profile': 4
    };

    const targetOrder = stageOrder[stepKey] || 1;

    if (currentOrder > targetOrder) return 'completed';
    if (currentOrder === targetOrder) return 'active';
    return 'pending';
  }

  getStepClass(stepKey: string): string {
    const status = this.getStepStatus(stepKey);
    if (status === 'completed') return 'text-emerald-400 font-bold';
    if (status === 'active') return 'text-accent font-black';
    return 'text-secondary opacity-60';
  }

  getStepNumClass(stepKey: string): string {
    const status = this.getStepStatus(stepKey);
    if (status === 'completed') return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40';
    if (status === 'active') return 'bg-accent text-white shadow-material';
    return 'bg-surface-hover text-secondary border border-border-base';
  }

  // --- Navigation Actions ---
  startIncrementalImport(): void {
    this.ingestionState.reset();
    this.router.navigate(['/app/import']);
  }

  openClearModal(): void {
    this.isClearModalOpen = true;
  }

  cancelClearModal(): void {
    this.isClearModalOpen = false;
  }

  confirmClearData(): void {
    this.isClearModalOpen = false;
    this.isClearingData = true;
    this.apiService.clearData().subscribe({
      next: () => {
        this.isClearingData = false;
        this.ingestionState.reset();
        this.dashboardState.reset();
        this.router.navigate(['/app/import']);
      },
      error: () => {
        this.isClearingData = false;
        this.ingestionState.reset();
        this.dashboardState.reset();
        this.router.navigate(['/app/import']);
      }
    });
  }

  clearAllDataAndRestart(): void {
    this.openClearModal();
  }

  // --- Auth & Modals ---
  openLoginModal(): void {
    this.isLoginOpen = true;
  }

  closeLoginModal(): void {
    this.isLoginOpen = false;
  }

  handleLoginSuccess(user: any): void {
    this.authService.setCurrentUser(user);
    this.isLoginOpen = false;
    this.router.navigate(['/app/dashboard']);
  }

  performLogout(): void {
    this.authService.clearToken();
    this.router.navigate(['/']);
  }

  performDemoLogin(): void {
    this.apiService.loginUser('demo@supplyforge.ai', 'demo123').subscribe({
      next: (res: any) => {
        if (res && res.token) {
          this.authService.setToken(res.token);
          this.router.navigate(['/app/dashboard']);
        }
      },
      error: (err) => {
        console.error('Demo login error:', err);
        // Fallback for offline demo
        this.authService.setToken('demo_token_fallback');
        this.router.navigate(['/app/dashboard']);
      }
    });
  }

  submitPhoneNumber(): void {
    if (!this.phoneNumberInput || this.phoneNumberInput.trim().length < 8) {
      this.phoneError = 'Vui lòng nhập số điện thoại hợp lệ (tối thiểu 8 chữ số).';
      return;
    }
    this.phoneLoading = true;
    this.phoneError = '';

    this.apiService.completeGooglePhone(this.tempPhoneUser.tempUserId, this.phoneNumberInput).subscribe({
      next: (res: any) => {
        this.phoneLoading = false;
        this.requiresPhone = false;
        if (res && res.token) {
          this.authService.setToken(res.token);
          this.router.navigate(['/app/dashboard']);
        }
      },
      error: (err: any) => {
        this.phoneLoading = false;
        this.phoneError = err.error?.error || 'Không thể cập nhật số điện thoại. Vui lòng thử lại.';
      }
    });
  }
}
