import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { HeaderComponent } from './header/header.component';
import { SidebarComponent } from './sidebar/sidebar.component';
import { TrustTheaterHeroComponent } from './trust-theater-hero/trust-theater-hero.component';
import { ProcessingScreenComponent } from './processing-screen/processing-screen.component';
import { DataMappingConfirmComponent } from './data-mapping-confirm/data-mapping-confirm.component';
import { LoginModalComponent } from './login-modal/login-modal.component';
import { CsvUploadComponent } from './csv-upload/csv-upload.component';
import { DatasetProfileDashboardComponent } from './dataset-profile-dashboard/dataset-profile-dashboard.component';
import { SlowMovingRiskDashboardComponent } from './slow-moving-risk-dashboard/slow-moving-risk-dashboard.component';
import { CapitalExposureDashboardComponent } from './capital-exposure-dashboard/capital-exposure-dashboard.component';
import { DecisionSupportDashboardComponent } from './decision-support-dashboard/decision-support-dashboard.component';
import { ExecutiveDashboardComponent } from './executive-dashboard/executive-dashboard.component';
import { CopilotWidgetComponent } from './copilot-widget/copilot-widget.component';
import { AboutUsPageComponent } from './about-us-page/about-us-page.component';
import { ServicesPageComponent } from './services-page/services-page.component';
import { BlogPageComponent } from './blog-page/blog-page.component';
import { AuthPageComponent } from './auth-page/auth-page.component';

import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { FieldConfig } from './field-config';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    HeaderComponent,
    SidebarComponent,
    TrustTheaterHeroComponent,
    ProcessingScreenComponent,
    DataMappingConfirmComponent,
    LoginModalComponent,
    CsvUploadComponent,
    DatasetProfileDashboardComponent,
    SlowMovingRiskDashboardComponent,
    CapitalExposureDashboardComponent,
    DecisionSupportDashboardComponent,
    ExecutiveDashboardComponent,
    CopilotWidgetComponent,
    AboutUsPageComponent,
    ServicesPageComponent,
    BlogPageComponent,
    AuthPageComponent
  ],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent implements OnInit {
  title = 'SupplyForge AI';
  selectedSkuId: string | null = null;

  // App Stages: hero | auth | about_us | services | blog | csv-upload | processing | mapping | dataset-profile | executive-dashboard | slow-moving-risk | capital-exposure | decision-support
  stage: string = 'hero';
  authInitialTab: 'login' | 'register' = 'login';

  uploadFile: File | null = null;
  uploadErrorMessage: string = '';
  mappingData: any = null;
  activeSessionId: string = '';
  datasetProfileData: any = null;
  isProcessingBatch = false;

  dashboardData: any = null;

  // Info Modal State (About Us, Services, Blog)
  isInfoModalOpen = false;
  activeInfoTab: 'about' | 'services' | 'blog' = 'about';

  // Auth & Modal State
  isLoginOpen = false;
  currentUser: any = null;
  requiresPhone = false;
  tempPhoneUser = { tempUserId: '', email: '', name: '', picture: '' };
  phoneNumberInput = '';
  phoneError = '';
  phoneLoading = false;

  mappingFields: FieldConfig[] = [
    { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc nhãn hiệu của SKU' },
    { key: 'itemSku', label: 'Mã SKU', desc: 'Mã vạch hoặc mã ký tự SKU định danh' },
    { key: 'price', label: 'Giá bán', desc: 'Giá niêm yết bán lẻ cho người tiêu dùng' },
    { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng' },
    { key: 'stock', label: 'Tồn kho', desc: 'Số lượng đơn vị còn tồn kho' },
    { key: 'orderDate', label: 'Ngày ghi nhận', desc: 'Ngày nhập kho hoặc ngày giao dịch gần nhất' }
  ];

  finalMapping: Record<string, string> = {};

  constructor(
    private apiService: ApiService,
    private authService: AuthService
  ) { }

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

  ngOnInit(): void {
    console.info('[Auth Debug] Khởi động ứng dụng. URL:', window.location.href);

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

    const token = this.authService.getToken();
    console.info('[Auth Debug] Token hiện có:', token);

    if (token) {
      const payload = this.parseJwt(token);
      console.info('[Auth Debug] Payload giải mã:', payload);
      if (payload) {
        this.currentUser = {
          name: payload.name || payload.email?.split('@')[0] || 'User',
          email: payload.email || 'user@supplyforge.ai'
        };
      } else {
        this.currentUser = { name: 'Demo Admin', email: 'admin@supplyforge.ai' };
      }
      console.info('[Auth Debug] Đã gán currentUser:', this.currentUser);
    } else {
      console.info('[Auth Debug] Không có token. Người dùng là khách vãng lai.');
    }

    // Check if database already has imported data
    this.apiService.checkData().subscribe({
      next: (res) => {
        if (res && res.hasData) {
          this.loadDashboardData();
          this.stage = 'executive-dashboard';
        }
      },
      error: (err) => console.log('Check data error:', err)
    });
  }

  // --- File Import Flow ---
  startProcessing(event: { file: File }): void {
    this.uploadFile = event.file;
    this.uploadErrorMessage = '';
    this.stage = 'processing';

    this.apiService.uploadCsvV2(event.file, 1, 'INITIAL').subscribe({
      next: (res: any) => {
        if (res?.sessionId) {
          this.activeSessionId = res.sessionId;
        }

        if (res?.status === 'REJECT' || res?.profile?.validation?.status === 'REJECT') {
          this.uploadErrorMessage = res?.error || res?.profile?.validation?.errors?.join('; ') || 'Tệp CSV không hợp lệ hoặc bị hệ thống từ chối.';
          this.stage = 'csv-upload';
          return;
        }

        const profile = res?.profile;
        if (profile) {
          this.mappingData = {
            headers: profile.headers,
            sampleData: profile.previewRows ? profile.previewRows[0] : null,
            aiSuggestions: {
              sku_column_index: profile.headers.indexOf(profile.skuColumnDetected),
              record_date_column_index: profile.headers.indexOf(profile.dateColumnDetected),
              confidence: 'High (Streaming CSV Profiler)'
            }
          };
          this.autoMapFields(this.mappingData);
          this.stage = 'mapping';
        } else {
          this.uploadErrorMessage = 'Không nhận diện được cấu trúc tệp CSV.';
          this.stage = 'csv-upload';
        }
      },
      error: (err: any) => {
        console.error('Hero upload error:', err);
        this.uploadErrorMessage = err.error?.error || 'Tệp CSV không hợp lệ (sai mã hóa, trùng cột, thiếu header hoặc rỗng).';
        this.stage = 'csv-upload';
      }
    });
  }

  handleCancelImport(): void {
    if (this.activeSessionId) {
      this.apiService.cancelIngestionSession(this.activeSessionId).subscribe({
        next: () => {
          console.log('Ingestion session cancelled on backend');
        },
        error: (err) => console.error('Cancel session error:', err)
      });
    }
    this.uploadFile = null;
    this.mappingData = null;
    this.activeSessionId = '';
    this.uploadErrorMessage = 'Đã hủy nạp tệp theo yêu cầu của bạn.';
    this.isProcessingBatch = false;
    this.stage = 'csv-upload';
  }

  handleCsvProfileComplete(event: { file: File; profileData: any; sessionType?: 'INITIAL' | 'INCREMENTAL' }): void {
    this.uploadFile = event.file;
    if (event.sessionType) {
      this.importMode = event.sessionType === 'INCREMENTAL' ? 'incremental' : 'fresh';
    }
    if (event.profileData?.sessionId) {
      this.activeSessionId = event.profileData.sessionId;
    }
    const profile = event.profileData?.profile;

    if (profile) {
      this.mappingData = {
        headers: profile.headers,
        sampleData: profile.previewRows ? profile.previewRows[0] : null,
        aiSuggestions: {
          sku_column_index: profile.headers.indexOf(profile.skuColumnDetected),
          record_date_column_index: profile.headers.indexOf(profile.dateColumnDetected),
          confidence: 'High (Streaming CSV Profiler)'
        }
      };
      this.autoMapFields(this.mappingData);
    }
    this.stage = 'mapping';
  }

  autoMapFields(res: any): void {
    if (!res || !res.headers || res.headers.length === 0) return;
    const headers = res.headers;
    const suggestions = res.aiSuggestions || {};

    if (suggestions.sku_column_index !== undefined && suggestions.sku_column_index !== null && headers[suggestions.sku_column_index]) {
      this.finalMapping['itemSku'] = headers[suggestions.sku_column_index];
    }
    if (suggestions.quantity_column_index !== undefined && suggestions.quantity_column_index !== null && headers[suggestions.quantity_column_index]) {
      this.finalMapping['stock'] = headers[suggestions.quantity_column_index];
    }
    if (suggestions.selling_price_column_index !== undefined && suggestions.selling_price_column_index !== null && headers[suggestions.selling_price_column_index]) {
      this.finalMapping['price'] = headers[suggestions.selling_price_column_index];
    }
    if (suggestions.cost_price_column_index !== undefined && suggestions.cost_price_column_index !== null && headers[suggestions.cost_price_column_index]) {
      this.finalMapping['cost'] = headers[suggestions.cost_price_column_index];
    }
    if (suggestions.record_date_column_index !== undefined && suggestions.record_date_column_index !== null && headers[suggestions.record_date_column_index]) {
      this.finalMapping['orderDate'] = headers[suggestions.record_date_column_index];
    }

    const findHeader = (regex: RegExp, fallbackIdx: number) => {
      const matched = headers.find((h: string) => regex.test(h));
      return matched || (fallbackIdx < headers.length ? headers[fallbackIdx] : headers[0]);
    };

    if (!this.finalMapping['productName']) {
      this.finalMapping['productName'] = suggestions.product_name || findHeader(/name|tên|sản phẩm|product/i, 0);
    }
    if (!this.finalMapping['itemSku']) {
      this.finalMapping['itemSku'] = suggestions.item_sku || findHeader(/sku|mã|code/i, 0);
    }
    if (!this.finalMapping['price']) {
      this.finalMapping['price'] = suggestions.price || findHeader(/price|giá bán|giá/i, 2);
    }
    if (!this.finalMapping['cost']) {
      this.finalMapping['cost'] = suggestions.cost || findHeader(/cost|giá vốn|vốn/i, 3);
    }
    if (!this.finalMapping['stock']) {
      this.finalMapping['stock'] = suggestions.stock || findHeader(/stock_on_hand|tồn_kho|tồn|stock/i, 1);
    }
    if (!this.finalMapping['orderDate']) {
      this.finalMapping['orderDate'] = suggestions.date || findHeader(/date|ngày/i, 4);
    }
  }

  handleMappingReady(data: any): void {
    if (this.stage === 'processing' && !this.mappingData) {
      this.stage = 'mapping';
    }
  }

  handleConfirmMapping(finalMapping: Record<string, string>): void {
    this.isProcessingBatch = true;
    const targetFile = this.uploadFile;
    const sessionType = this.importMode === 'fresh' ? 'INITIAL' : 'INCREMENTAL';

    const onProfilingComplete = (profileRes: any, processRes?: any) => {
      this.isProcessingBatch = false;
      const baseProfile = profileRes?.profile || profileRes || {};
      const proc = processRes || {};
      this.datasetProfileData = {
        ...baseProfile,
        ...proc,
        import_type: proc.import_type || sessionType,
        duplicate_rows: proc.duplicate_rows ?? baseProfile.duplicate_rows ?? 0,
        updated_rows: proc.updated_rows ?? proc.details?.updated_rows ?? baseProfile.updated_rows ?? 0,
        data_corrections: proc.data_corrections ?? proc.details?.data_corrections ?? baseProfile.data_corrections ?? [],
        rows_rejected: proc.rows_rejected ?? baseProfile.rows_rejected ?? 0,
        rejected_rows: proc.rejected_rows ?? proc.details?.rejected_rows ?? baseProfile.rejected_rows ?? [],
        overlap_detected: proc.overlap_detected ?? baseProfile.overlap_detected ?? false,
        rows_received: proc.rows_received ?? baseProfile.rows_received ?? 0,
        new_rows: proc.new_rows ?? baseProfile.new_rows ?? 0,
        temporal_range: proc.temporal_range ?? baseProfile.temporal_range ?? null
      };
      this.stage = 'dataset-profile';
    };

    if (this.activeSessionId) {
      this.apiService.triggerDatasetProfiling(this.activeSessionId, finalMapping).subscribe({
        next: (profileRes) => {
          if (targetFile) {
            this.apiService.processFile(targetFile, finalMapping, 'user_default_001', sessionType).subscribe({
              next: (processRes) => onProfilingComplete(profileRes, processRes),
              error: () => onProfilingComplete(profileRes)
            });
          } else {
            onProfilingComplete(profileRes);
          }
        },
        error: () => {
          if (targetFile) {
            this.apiService.processFile(targetFile, finalMapping, 'user_default_001', sessionType).subscribe({
              next: (processRes) => onProfilingComplete(null, processRes),
              error: () => {
                this.isProcessingBatch = false;
                this.loadDashboardData();
                this.stage = 'executive-dashboard';
              }
            });
          } else {
            this.isProcessingBatch = false;
            this.loadDashboardData();
            this.stage = 'executive-dashboard';
          }
        }
      });
    } else if (targetFile) {
      this.apiService.processFile(targetFile, finalMapping, 'user_default_001', sessionType).subscribe({
        next: (processRes) => onProfilingComplete(null, processRes),
        error: () => {
          this.isProcessingBatch = false;
          this.loadDashboardData();
          this.stage = 'executive-dashboard';
        }
      });
    } else {
      this.isProcessingBatch = false;
      this.loadDashboardData();
      this.stage = 'executive-dashboard';
    }
  }

  handleProceedFromProfile(): void {
    if (this.activeSessionId) {
      this.apiService.runM3RiskAssessmentAssembly(this.activeSessionId).subscribe({
        next: () => {
          this.apiService.runM3RiskMonitoring(this.activeSessionId).subscribe();
          this.loadDashboardData();
        },
        error: (err) => {
          console.warn('M3 assembly trigger error:', err);
          this.loadDashboardData();
        }
      });
    } else {
      this.loadDashboardData();
    }
    this.stage = 'executive-dashboard';
  }

  // --- Data Loaders ---
  loadDashboardData(): void {
    this.apiService.getDashboard(1).subscribe({
      next: (res) => {
        if (res) {
          const healthyVal = res.totalHealthyValue || 0;
          const watchlistVal = res.totalWatchlistValue || 0;
          const slowVal = res.totalSlowMovingValue || 0;
          const deadVal = res.totalDeadStockValue || 0;
          const totalInvVal = healthyVal + watchlistVal + slowVal + deadVal;

          const healthyList = res.healthySkus || [];
          const watchlistList = res.watchlistSkus || [];
          const slowList = res.slowMovingSkus || [];
          const deadList = res.deadStockSkus || [];
          const allSkus = [...deadList, ...slowList, ...watchlistList, ...healthyList];

          if (allSkus.length === 0) {
            this.setEmptyDashboardData();
            return;
          }

          let topStale = [...deadList, ...slowList].map((item: any) => ({
            sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
            name: item.name || item.product_name || 'SKU Sản phẩm',
            frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
            lastRecordDate: item.lastRecordDate || 'N/A'
          })).slice(0, 5);

          if (topStale.length === 0 && allSkus.length > 0) {
            topStale = allSkus.map((item: any) => ({
              sku: item.sku || item.item_sku || item.name || 'SKU Sản phẩm',
              name: item.name || item.product_name || 'SKU Sản phẩm',
              frozenValueVnd: item.totalValue || item.frozenValueVnd || ((item.quantity || 1) * (item.costPrice || 50000)) || 0,
              lastRecordDate: item.lastRecordDate || 'N/A'
            })).slice(0, 5);
          }

          const finalDeadStockValue = deadVal + slowVal;
          const finalStaleCount = deadList.length + slowList.length;
          const finalBleedingRate = res.totalBleedingRateMonthly || Math.round(finalDeadStockValue * 0.08);

          this.dashboardData = {
            hasData: true,
            ...res,
            totalDeadStockValueVnd: finalDeadStockValue,
            staleSkuCount: finalStaleCount,
            estimatedLoss30DaysVnd: finalBleedingRate,
            totalInventoryValueVnd: totalInvVal,
            totalRootSkuCount: allSkus.length,
            topStaleSkus: topStale
          };
        } else {
          this.setEmptyDashboardData();
        }
      },
      error: () => {
        this.setEmptyDashboardData();
      }
    });
  }

  setEmptyDashboardData(): void {
    this.dashboardData = {
      hasData: false,
      totalDeadStockValueVnd: 0,
      staleSkuCount: 0,
      estimatedLoss30DaysVnd: 0,
      totalInventoryValueVnd: 0,
      totalRootSkuCount: 0,
      healthySkus: [],
      watchlistSkus: [],
      slowMovingSkus: [],
      deadStockSkus: [],
      topStaleSkus: []
    };
  }

  // --- Navigation & State Switcher ---
  handleStageSelect(targetStage: string): void {
    this.stage = targetStage;
    if (targetStage === 'executive-dashboard') {
      this.loadDashboardData();
    } else if (targetStage === 'slow-moving-risk') {
      this.ensureSessionId();
    }
  }

  handleViewSkuDetail(skuId: string): void {
    this.selectedSkuId = skuId;
    this.handleStageSelect('slow-moving-risk');
  }

  ensureSessionId(): void {
    if (!this.activeSessionId) {
      this.apiService.listIngestionSessions(1).subscribe({
        next: (res: any) => {
          if (res?.sessions?.length > 0) {
            this.activeSessionId = res.sessions[0].sessionId || res.sessions[0].session_id || '';
          }
        },
        error: (err: any) => console.warn('Could not fetch sessions:', err)
      });
    }
  }

  // --- Ingestion Pipeline Stepper Indicators ---
  getStepStatus(stepKey: string): 'completed' | 'active' | 'pending' {
    const stageOrder: { [key: string]: number } = {
      'csv-upload': 1,
      'processing': 2,
      'mapping': 3,
      'dataset-profile': 4
    };

    const currentOrder = stageOrder[this.stage] || 0;
    const targetOrder = stageOrder[stepKey] || 0;

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

  // Import mode flag: 'incremental' = add data on top, 'fresh' = clear old + import new
  importMode: 'incremental' | 'fresh' = 'incremental';
  isClearingData = false;

  startIncrementalImport(): void {
    this.importMode = 'incremental';
    this.uploadFile = null;
    this.mappingData = null;
    this.activeSessionId = '';
    this.stage = 'csv-upload';
  }

  // Clear Data Modal State
  isClearModalOpen = false;

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
        this.resetAllStatesAndGoToUpload();
      },
      error: () => {
        this.isClearingData = false;
        this.resetAllStatesAndGoToUpload();
      }
    });
  }

  clearAllDataAndRestart(): void {
    this.importMode = 'fresh';
    this.openClearModal();
  }

  resetAllStates(): void {
    this.uploadFile = null;
    this.mappingData = null;
    this.dashboardData = null;
    this.activeSessionId = '';
    this.selectedSkuId = null;
    this.datasetProfileData = null;
    this.stage = 'hero';
  }

  resetAllStatesAndGoToUpload(): void {
    this.uploadFile = null;
    this.mappingData = null;
    this.dashboardData = null;
    this.activeSessionId = '';
    this.selectedSkuId = null;
    this.datasetProfileData = null;
    this.stage = 'csv-upload';
  }

  // --- Auth Page Navigation ---
  openLoginModal(): void {
    this.authInitialTab = 'login';
    this.stage = 'auth';
  }

  openRegisterPage(): void {
    this.authInitialTab = 'register';
    this.stage = 'auth';
  }

  closeLoginModal(): void {
    this.isLoginOpen = false;
  }

  handleLoginSuccess(user: { name: string; email: string }): void {
    this.currentUser = user;
    this.isLoginOpen = false;
  }

  handleAuthLogin(user: { name: string; email: string; storeName?: string }): void {
    // Tạo mock JWT Token
    const mockPayload = {
      sub: user.email,
      name: user.name,
      email: user.email,
      role: 'enterprise_admin',
      iss: 'supplyforge.ai',
      iat: Math.floor(Date.now() / 1000)
    };
    const mockJwt = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' + btoa(JSON.stringify(mockPayload)) + '.signature';
    this.authService.setToken(mockJwt);

    this.currentUser = {
      name: user.name,
      email: user.email,
      role: user.storeName ? 'Chủ cửa hàng' : 'Quản trị viên',
      storeName: user.storeName
    };

    // Kiểm tra đã có dữ liệu chưa → nếu có thì vào dashboard, chưa thì về hero
    this.apiService.checkData().subscribe({
      next: (res) => {
        if (res && res.hasData) {
          this.loadDashboardData();
          this.stage = 'executive-dashboard';
        } else {
          this.stage = 'hero';
        }
      },
      error: () => {
        this.stage = 'hero';
      }
    });
  }

  handleAuthGoBack(): void {
    this.stage = 'hero';
  }

  submitPhoneNumber(): void {
    if (!this.phoneNumberInput || this.phoneNumberInput.length < 9) {
      this.phoneError = 'Vui lòng nhập số điện thoại hợp lệ (tối thiểu 9 số).';
      return;
    }
    this.phoneLoading = true;
    this.phoneError = '';

    console.info('[Auth Debug] Gửi yêu cầu lưu số điện thoại:', this.phoneNumberInput);
    this.apiService.completeGooglePhone(
      this.tempPhoneUser.tempUserId,
      this.phoneNumberInput,
      this.tempPhoneUser.picture
    ).subscribe({
      next: (res) => {
        this.phoneLoading = false;
        console.info('[Auth Debug] Kết quả bổ sung số điện thoại:', res);
        if (res && res.token) {
          this.authService.setToken(res.token);
          this.currentUser = {
            name: res.user?.name || this.tempPhoneUser.name || 'User',
            email: res.user?.email || this.tempPhoneUser.email
          };
          this.requiresPhone = false;
          this.phoneNumberInput = '';
          console.info('[Auth Debug] Đăng nhập Google thành công hoàn toàn!', this.currentUser);
        } else {
          this.phoneError = 'Phản hồi từ máy chủ không hợp lệ.';
        }
      },
      error: (err) => {
        this.phoneLoading = false;
        console.error('[Auth Debug] Lỗi bổ sung số điện thoại:', err);
        this.phoneError = err.error?.error || 'Có lỗi xảy ra khi lưu số điện thoại. Vui lòng thử lại.';
      }
    });
  }

  performDemoLogin(): void {
    const demoUser = {
      name: 'Chủ cửa hàng (Demo)',
      email: 'store.owner@supplyforge.ai',
      role: 'Chủ cửa hàng'
    };
    this.currentUser = demoUser;
    this.authService.setToken('demo_token');

    // Kiểm tra đã có dữ liệu → nếu có vào dashboard, chưa thì về hero để upload CSV
    this.apiService.checkData().subscribe({
      next: (res) => {
        if (res && res.hasData) {
          this.loadDashboardData();
          this.stage = 'executive-dashboard';
        } else {
          this.stage = 'hero';
        }
      },
      error: () => {
        this.stage = 'hero';
      }
    });
  }

  openInfoModal(tab: 'about' | 'services' | 'blog'): void {
    this.activeInfoTab = tab;
    this.isInfoModalOpen = true;
  }

  closeInfoModal(): void {
    this.isInfoModalOpen = false;
  }

  handleInfoAction(action: string): void {
    if (action === 'csv-upload') {
      this.handleStageSelect('csv-upload');
    }
  }

  performLogout(): void {
    this.authService.clearToken();
    this.currentUser = null;
    this.dashboardData = null;
    this.stage = 'hero';
  }
}
