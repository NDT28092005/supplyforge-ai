import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

type RunType = 'validate' | 'initial-sync' | 'sync' | 'reconcile';
type MappingFilter = 'NEEDS_REVIEW' | 'LINKED' | 'IGNORED';
type MappingAction = 'CONFIRM' | 'IGNORE' | 'REOPEN' | 'UNLINK';

interface CanonicalProduct {
  id: string;
  item_sku: string;
  product_name: string;
  stock?: number | null;
  price?: number | null;
}

interface SkuMapping {
  id: number;
  external_sku: string;
  external_name: string;
  canonical_sku: string;
  canonical_product: CanonicalProduct | null;
  status: 'AUTO_MAPPED' | 'NEEDS_REVIEW' | 'CONFIRMED' | 'IGNORED';
  mapping_method: string;
  updated_at: string;
  selected_product?: CanonicalProduct | null;
  candidate_query?: string;
  candidate_results?: CanonicalProduct[];
  candidate_loading?: boolean;
  is_editing?: boolean;
}

interface MappingDialog {
  action: MappingAction;
  mapping: SkuMapping;
}

interface MappingSummary {
  NEEDS_REVIEW: number;
  LINKED: number;
  AUTO_MAPPED: number;
  CONFIRMED: number;
  IGNORED: number;
}

interface OdooConnection {
  id: string;
  provider: string;
  display_name: string;
  status: string;
  base_url: string;
  company: { id: string; name: string };
  warehouses: Array<{ id: string; name: string }>;
  last_successful_sync_at: string | null;
  last_error: { code: string; message: string } | null;
  unmapped_sku_count: number;
  latest_run: any;
  discovery?: any;
}

@Component({
  selector: 'app-integration-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './integration-settings.component.html',
  styleUrls: ['./integration-settings.component.css'],
})
export class IntegrationSettingsComponent implements OnInit, OnDestroy {
  connections: OdooConnection[] = [];
  activeConnectionId = '';
  overview: any = null;
  mappings: SkuMapping[] = [];
  mappingPagination = { page: 1, pageSize: 25, totalItems: 0, totalPages: 1 };
  mappingSummary: MappingSummary = { NEEDS_REVIEW: 0, LINKED: 0, AUTO_MAPPED: 0, CONFIRMED: 0, IGNORED: 0 };
  mappingFilter: MappingFilter = 'NEEDS_REVIEW';

  isLoading = true;
  isSaving = false;
  isRunning = false;
  entitled = true;
  errorMessage = '';
  successMessage = '';
  showConnectionForm = false;
  showScopeEditor = false;
  webhookSecret = '';
  pollTimer?: ReturnType<typeof setInterval>;
  mappingSearchTimers = new Map<number, ReturnType<typeof setTimeout>>();
  mappingDialog: MappingDialog | null = null;
  mappingNote = '';
  isResolvingMapping = false;

  connectionForm = {
    display_name: '',
    base_url: '',
    database: '',
    username: '',
    api_key: '',
  };
  selectedCompanyId = '';
  selectedWarehouseIds = new Set<string>();

  constructor(private readonly api: ApiService) {}

  ngOnInit(): void {
    this.loadConnections();
    this.pollTimer = setInterval(() => this.refreshWhenRunActive(), 4000);
  }

  ngOnDestroy(): void {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.mappingSearchTimers.forEach(timer => clearTimeout(timer));
  }

  get activeConnection(): OdooConnection | undefined {
    return this.connections.find(item => item.id === this.activeConnectionId) || this.connections[0];
  }

  get discovery(): any {
    return this.activeConnection?.discovery || this.activeConnection?.latest_run?.summary?.discovery || {};
  }

  get companies(): any[] {
    return Array.isArray(this.discovery.companies) ? this.discovery.companies : [];
  }

  get eligibleWarehouses(): any[] {
    return (Array.isArray(this.discovery.warehouses) ? this.discovery.warehouses : []).filter(item => {
      return this.relationId(item.company_id) === this.selectedCompanyId;
    });
  }

  loadConnections(initial = true): void {
    if (initial) this.isLoading = true;
    this.errorMessage = '';
    this.api.listIntegrationConnections().subscribe({
      next: (response) => {
        this.isLoading = false;
        this.entitled = true;
        this.connections = Array.isArray(response?.connections) ? response.connections : [];
        if (!this.activeConnectionId || !this.connections.some(item => item.id === this.activeConnectionId)) {
          this.activeConnectionId = this.connections[0]?.id || '';
        }
        this.hydrateScope();
        this.loadActiveData();
      },
      error: (error) => {
        this.isLoading = false;
        const payload = error?.error?.error;
        this.entitled = payload?.code !== 'FEATURE_NOT_ENTITLED';
        this.errorMessage = payload?.message || 'Không thể tải cấu hình kết nối ERP.';
      },
    });
  }

  selectConnection(connectionId: string): void {
    this.activeConnectionId = connectionId;
    this.mappingPagination.page = 1;
    this.mappingFilter = 'NEEDS_REVIEW';
    this.successMessage = '';
    this.hydrateScope();
    this.loadActiveData();
  }

  createConnection(): void {
    if (this.isSaving) return;
    this.isSaving = true;
    this.errorMessage = '';
    this.successMessage = '';
    this.api.createIntegrationConnection({ provider: 'ODOO', ...this.connectionForm }).subscribe({
      next: (connection) => {
        this.isSaving = false;
        this.connections = [connection, ...this.connections];
        this.activeConnectionId = connection.id;
        this.webhookSecret = connection?.webhook?.secret || '';
        this.connectionForm = { display_name: '', base_url: '', database: '', username: '', api_key: '' };
        this.showConnectionForm = false;
        this.successMessage = 'Đã lưu kết nối. Chạy xác thực để đọc company và kho từ Odoo.';
        this.hydrateScope();
      },
      error: (error) => {
        this.isSaving = false;
        this.errorMessage = error?.error?.error?.message || 'Không thể lưu kết nối Odoo.';
      },
    });
  }

  run(runType: RunType): void {
    const connection = this.activeConnection;
    if (!connection || this.isRunning) return;
    this.isRunning = true;
    this.errorMessage = '';
    this.successMessage = '';
    this.api.runIntegration(connection.id, runType).subscribe({
      next: () => {
        this.successMessage = this.runLabel(runType);
        this.loadConnections(false);
      },
      error: (error) => {
        this.isRunning = false;
        this.errorMessage = error?.error?.error?.message || 'Không thể đưa yêu cầu đồng bộ vào hàng chờ.';
      },
    });
  }

  saveScope(): void {
    const connection = this.activeConnection;
    if (!connection || !this.selectedCompanyId || this.selectedWarehouseIds.size === 0) {
      this.errorMessage = 'Chọn một công ty và tối thiểu một kho trước khi nạp dữ liệu.';
      return;
    }
    const company = this.companies.find(item => String(item.id) === this.selectedCompanyId);
    const selectedWarehouses = this.eligibleWarehouses.filter(item => this.selectedWarehouseIds.has(String(item.id)));
    this.isSaving = true;
    this.api.updateIntegrationConnection(connection.id, {
      company_id: this.selectedCompanyId,
      company_name: company?.name || '',
      warehouse_ids: selectedWarehouses.map(item => String(item.id)),
      warehouse_names: selectedWarehouses.map(item => item.name || `Kho ${item.id}`),
    }).subscribe({
      next: (updated) => {
        this.isSaving = false;
        this.connections = this.connections.map(item => item.id === updated.id ? updated : item);
        this.showScopeEditor = false;
        this.successMessage = 'Đã cập nhật phạm vi công ty và kho cho kết nối.';
      },
      error: (error) => {
        this.isSaving = false;
        this.errorMessage = error?.error?.error?.message || 'Không thể cập nhật phạm vi đồng bộ.';
      },
    });
  }

  toggleWarehouse(event: Event, warehouseId: string): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (checked) this.selectedWarehouseIds.add(warehouseId);
    else this.selectedWarehouseIds.delete(warehouseId);
    this.selectedWarehouseIds = new Set(this.selectedWarehouseIds);
  }

  onCompanyChange(): void {
    const permitted = new Set(this.eligibleWarehouses.map(item => String(item.id)));
    this.selectedWarehouseIds = new Set([...this.selectedWarehouseIds].filter(id => permitted.has(id)));
  }

  loadMappings(page = this.mappingPagination.page): void {
    const connection = this.activeConnection;
    if (!connection) return;
    this.api.listIntegrationSkuMappings(connection.id, page, this.mappingPagination.pageSize, this.mappingFilter).subscribe({
      next: (response) => {
        this.mappings = Array.isArray(response?.items) ? response.items.map((item: SkuMapping) => ({
          ...item,
          selected_product: null,
          candidate_query: '',
          candidate_results: [],
          candidate_loading: false,
          is_editing: false,
        })) : [];
        this.mappingPagination = response?.pagination || this.mappingPagination;
        this.mappingSummary = { ...this.mappingSummary, ...(response?.summary || {}) };
      },
      error: () => this.mappings = [],
    });
  }

  selectMappingFilter(filter: MappingFilter): void {
    if (this.mappingFilter === filter) return;
    this.mappingFilter = filter;
    this.mappingPagination.page = 1;
    this.loadMappings(1);
  }

  onCandidateQuery(mapping: SkuMapping, query: string): void {
    mapping.candidate_query = query;
    mapping.selected_product = null;
    mapping.candidate_results = [];
    const currentTimer = this.mappingSearchTimers.get(mapping.id);
    if (currentTimer) clearTimeout(currentTimer);
    const normalized = query.trim();
    if (normalized.length < 2) {
      mapping.candidate_loading = false;
      return;
    }
    mapping.candidate_loading = true;
    const timer = setTimeout(() => {
      const connection = this.activeConnection;
      if (!connection || mapping.candidate_query?.trim() !== normalized) return;
      this.api.listIntegrationSkuCandidates(connection.id, normalized).subscribe({
        next: (response) => {
          if (mapping.candidate_query?.trim() === normalized) {
            mapping.candidate_results = Array.isArray(response?.items) ? response.items : [];
            mapping.candidate_loading = false;
          }
        },
        error: () => {
          mapping.candidate_results = [];
          mapping.candidate_loading = false;
        },
      });
    }, 250);
    this.mappingSearchTimers.set(mapping.id, timer);
  }

  selectCanonicalProduct(mapping: SkuMapping, product: CanonicalProduct): void {
    mapping.selected_product = product;
    mapping.candidate_query = `${product.item_sku}${product.product_name ? ' - ' + product.product_name : ''}`;
    mapping.candidate_results = [];
  }

  startMappingEdit(mapping: SkuMapping): void {
    mapping.is_editing = true;
    mapping.selected_product = null;
    mapping.candidate_query = '';
    mapping.candidate_results = [];
  }

  cancelMappingEdit(mapping: SkuMapping): void {
    mapping.is_editing = false;
    mapping.selected_product = null;
    mapping.candidate_query = '';
    mapping.candidate_results = [];
  }

  openMappingDialog(action: MappingAction, mapping: SkuMapping): void {
    if (action === 'CONFIRM' && !mapping.selected_product) {
      this.errorMessage = 'Chọn một SKU chuẩn nội bộ từ danh mục trước khi xác nhận.';
      return;
    }
    this.errorMessage = '';
    this.mappingNote = '';
    this.mappingDialog = { action, mapping };
  }

  closeMappingDialog(): void {
    if (this.isResolvingMapping) return;
    this.mappingDialog = null;
    this.mappingNote = '';
  }

  resolveMapping(): void {
    const connection = this.activeConnection;
    const dialog = this.mappingDialog;
    if (!connection || !dialog || this.isResolvingMapping) return;
    const { action, mapping } = dialog;
    this.isResolvingMapping = true;
    this.errorMessage = '';
    this.api.resolveIntegrationSkuMapping(connection.id, mapping.id, {
      action,
      canonical_product_id: action === 'CONFIRM' ? mapping.selected_product?.id : undefined,
      expected_updated_at: mapping.updated_at,
      note: this.mappingNote.trim(),
    }).subscribe({
      next: (updated) => {
        this.isResolvingMapping = false;
        this.mappingDialog = null;
        this.mappingNote = '';
        const refreshNote = updated?.operational_refresh?.status === 'QUEUED'
          ? ' Danh mục Odoo đang được làm mới.'
          : '';
        this.successMessage = this.mappingActionMessage(action, updated?.canonical_sku || mapping.external_sku) + refreshNote;
        this.loadMappings(this.mappingPagination.page);
        this.loadConnections(false);
      },
      error: (error) => {
        this.isResolvingMapping = false;
        const payload = error?.error;
        this.errorMessage = payload?.error?.message || 'Không thể cập nhật liên kết SKU.';
        if (payload?.error?.code === 'MAPPING_STALE') {
          this.mappingDialog = null;
          this.loadMappings(this.mappingPagination.page);
        }
      },
    });
  }

  mappingActionMessage(action: MappingAction, sku: string): string {
    const messages: Record<MappingAction, string> = {
      CONFIRM: `Đã xác nhận liên kết với SKU chuẩn ${sku}.`,
      IGNORE: 'SKU đã được bỏ qua khỏi hàng chờ mapping.',
      REOPEN: 'SKU đã được đưa lại vào hàng chờ mapping.',
      UNLINK: 'Đã gỡ liên kết và đưa SKU lại vào hàng chờ.',
    };
    return messages[action];
  }

  mappingStatusLabel(status: SkuMapping['status']): string {
    const labels: Record<SkuMapping['status'], string> = {
      AUTO_MAPPED: 'Tự động liên kết',
      NEEDS_REVIEW: 'Cần xử lý',
      CONFIRMED: 'Đã xác nhận',
      IGNORED: 'Đã bỏ qua',
    };
    return labels[status];
  }

  private loadActiveData(): void {
    const connection = this.activeConnection;
    if (!connection) {
      this.overview = null;
      this.mappings = [];
      return;
    }
    this.loadMappings(1);
    this.api.getIntegrationOverview(connection.id).subscribe({
      next: (response) => this.overview = response,
      error: () => this.overview = null,
    });
  }

  private refreshWhenRunActive(): void {
    if (this.isRunning || this.connections.some(item => ['PENDING', 'RUNNING'].includes(item.latest_run?.status))) {
      this.isRunning = true;
      this.loadConnections(false);
      const running = this.connections.some(item => ['PENDING', 'RUNNING'].includes(item.latest_run?.status));
      if (!running) this.isRunning = false;
    }
  }

  private hydrateScope(): void {
    const connection = this.activeConnection;
    this.selectedCompanyId = connection?.company?.id || '';
    this.selectedWarehouseIds = new Set((connection?.warehouses || []).map(item => String(item.id)));
  }

  relationId(value: any): string {
    return Array.isArray(value) ? String(value[0]) : String(value || '');
  }

  runLabel(runType: RunType): string {
    const messages: Record<RunType, string> = {
      validate: 'Đang xác thực quyền đọc và tải danh sách company, kho.',
      'initial-sync': 'Đang nạp lịch sử vận hành trong 12 tháng.',
      sync: 'Đang đồng bộ phần dữ liệu thay đổi gần đây.',
      reconcile: 'Đang đối soát tồn khả dụng giữa Odoo và SupplyForge.',
    };
    return messages[runType];
  }

  formatNumber(value: number | undefined | null): string {
    return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 }).format(Number(value || 0));
  }
}
