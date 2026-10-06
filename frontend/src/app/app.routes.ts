import { Routes } from '@angular/router';
import { TrustTheaterHeroComponent } from './trust-theater-hero/trust-theater-hero.component';
import { AuthPageComponent } from './auth-page/auth-page.component';
import { AboutUsPageComponent } from './about-us-page/about-us-page.component';
import { ServicesPageComponent } from './services-page/services-page.component';
import { BlogPageComponent } from './blog-page/blog-page.component';
import { CsvUploadComponent } from './csv-upload/csv-upload.component';
import { ProcessingScreenComponent } from './processing-screen/processing-screen.component';
import { DataMappingConfirmComponent } from './data-mapping-confirm/data-mapping-confirm.component';
import { DatasetProfileDashboardComponent } from './dataset-profile-dashboard/dataset-profile-dashboard.component';
import { ExecutiveDashboardComponent } from './executive-dashboard/executive-dashboard.component';
import { SlowMovingRiskDashboardComponent } from './slow-moving-risk-dashboard/slow-moving-risk-dashboard.component';
import { CapitalExposureDashboardComponent } from './capital-exposure-dashboard/capital-exposure-dashboard.component';
import { DecisionSupportDashboardComponent } from './decision-support-dashboard/decision-support-dashboard.component';
import { JobQueueComponent } from './job-queue/job-queue.component';
import { dataReadyGuard } from './core/guards/data-ready.guard';

export const routes: Routes = [
  // ── Public Pages ──
  { path: '', component: TrustTheaterHeroComponent, title: 'SupplyForge AI — Nền tảng Quản lý Rủi ro Tồn kho' },
  { path: 'auth', component: AuthPageComponent, title: 'Đăng nhập — SupplyForge AI' },
  { path: 'about', component: AboutUsPageComponent, title: 'Về chúng tôi — SupplyForge AI' },
  { path: 'services', component: ServicesPageComponent, title: 'Dịch vụ — SupplyForge AI' },
  { path: 'blog', component: BlogPageComponent, title: 'Blog — SupplyForge AI' },

  // ── Ingestion Wizard Routes ──
  { path: 'app/import', component: CsvUploadComponent, title: 'Nạp dữ liệu — SupplyForge AI' },
  { path: 'app/import/processing', component: ProcessingScreenComponent, title: 'Đang xử lý — SupplyForge AI' },
  { path: 'app/import/mapping', component: DataMappingConfirmComponent, title: 'Xác nhận cột — SupplyForge AI' },
  { path: 'app/import/profile/:sessionId', component: DatasetProfileDashboardComponent, title: 'Tổng quan Dataset — SupplyForge AI' },
  { path: 'app/queue', component: JobQueueComponent, title: 'Hàng chờ xử lý ngầm — SupplyForge AI' },

  // ── Dashboard Routes ──
  { path: 'app/dashboard', component: ExecutiveDashboardComponent, canActivate: [dataReadyGuard], title: 'Tổng quan — SupplyForge AI' },
  { path: 'app/risk', component: SlowMovingRiskDashboardComponent, canActivate: [dataReadyGuard], title: 'Phân tích Rủi ro — SupplyForge AI' },
  { path: 'app/capital', component: CapitalExposureDashboardComponent, canActivate: [dataReadyGuard], title: 'Phơi nhiễm Vốn — SupplyForge AI' },
  { path: 'app/decisions', component: DecisionSupportDashboardComponent, canActivate: [dataReadyGuard], title: 'Hỗ trợ Quyết định — SupplyForge AI' },

  // ── Fallback ──
  { path: '**', redirectTo: '' }
];
