import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';

import { HeaderComponent } from './header/header.component';
import { SidebarComponent } from './sidebar/sidebar.component';
import { CopilotWidgetComponent } from './copilot-widget/copilot-widget.component';
import { LoginModalComponent } from './login-modal/login-modal.component';

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
    CopilotWidgetComponent,
    LoginModalComponent,
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
  clearDataError = '';
  isSidebarCollapsed = false;

  constructor(
    public apiService: ApiService,
    public authService: AuthService,
    public ingestionState: IngestionStateService,
    public dashboardState: DashboardStateService,
    public router: Router
  ) {}

  ngOnInit(): void {
    try {
      this.isSidebarCollapsed = localStorage.getItem('supplyforge.sidebar-collapsed') === 'true';
    } catch {
      // The application remains usable when browser storage is unavailable.
    }
    // Dashboard cache is tenant-specific. Never trust a browser session cache
    // before the API confirms that it belongs to the authenticated workspace.
    this.dashboardState.reset();
    this.authService.restoreSession().subscribe({
      next: (user) => {
        if (user) this.loadWorkspaceDataState();
      }
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

  get canReturnToDashboard(): boolean {
    return this.authService.isLoggedIn() && !this.ingestionState.isDatasetTransitionActive;
  }

  toggleSidebar(): void {
    this.isSidebarCollapsed = !this.isSidebarCollapsed;
    try {
      localStorage.setItem('supplyforge.sidebar-collapsed', String(this.isSidebarCollapsed));
    } catch {
      // Persisting this display preference is optional.
    }
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
    this.ingestionState.setSessionType('INCREMENTAL');
    this.router.navigate(['/app/import']);
  }

  returnToDashboard(): void {
    this.router.navigate(['/app/dashboard']);
  }

  openClearModal(): void {
    this.clearDataError = '';
    this.isClearModalOpen = true;
  }

  cancelClearModal(): void {
    if (this.isClearingData) return;
    this.clearDataError = '';
    this.isClearModalOpen = false;
  }

  confirmClearData(): void {
    this.isClearingData = true;
    this.clearDataError = '';
    this.ingestionState.setDatasetStatus('clearing', 'Đang xóa bộ dữ liệu hiện tại.');
    this.apiService.clearData().subscribe({
      next: (res: any) => {
        if (res?.status !== 'SUCCESS') {
          this.handleClearDataError(res?.error || 'Hệ thống chưa xác nhận thao tác xóa dữ liệu.');
          return;
        }
        this.isClearingData = false;
        this.isClearModalOpen = false;
        this.ingestionState.reset();
        this.dashboardState.reset();
        this.router.navigate(['/app/import']);
      },
      error: (err: any) => {
        this.handleClearDataError(err?.error?.error || 'Không thể xóa dữ liệu. Dữ liệu hiện tại vẫn được giữ nguyên.');
      }
    });
  }

  private handleClearDataError(message: string): void {
    this.isClearingData = false;
    this.clearDataError = message;
    this.ingestionState.setDatasetStatus('error', message);
  }

  clearAllDataAndRestart(): void {
    this.openClearModal();
  }

  // --- Auth & Modals ---
  openLoginModal(): void {
    this.router.navigate(['/auth']);
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
    this.apiService.logoutUser().subscribe({
      complete: () => this.finishLogout(),
      error: () => this.finishLogout(),
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
        const token = res?.access_token || res?.token;
        if (token) {
          this.authService.setSession(token, res.user);
          this.router.navigate(['/app/dashboard']);
        }
      },
      error: (err: any) => {
        this.phoneLoading = false;
        this.phoneError = err.error?.error || 'Không thể cập nhật số điện thoại. Vui lòng thử lại.';
      }
    });
  }

  private loadWorkspaceDataState(): void {
    this.apiService.checkData().subscribe({
      next: (res) => {
        if (res?.hasData && !this.ingestionState.isDatasetTransitionActive) {
          this.dashboardState.setHasData(true);
        }
      },
    });
  }

  private finishLogout(): void {
    this.authService.clearToken();
    this.dashboardState.reset();
    this.ingestionState.reset();
    this.router.navigate(['/']);
  }
}
