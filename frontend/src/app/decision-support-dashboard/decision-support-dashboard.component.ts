import { Component, OnInit, OnDestroy, Output, EventEmitter, ElementRef, HostListener, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { ApiService } from '../api.service';
import { DashboardStateService } from '../core/state/dashboard-state.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

export interface DecisionItem {
  decision_id: string;
  sku: string;
  risk: {
    class: string;
    score: number;
  };
  decision: {
    action: string;
    discount_rate: number | null;
    action_parameters: any;
    options?: MerchantOptionSet | null;
    priority: string;
    priority_score: number;
    priority_rank: number;
    urgency: string;
    confidence: string;
    status: string;
  };
  financial_impact: {
    capital_exposure: number;
    expected_recovery_value: number;
    recovery_rate: number;
    residual_exposure: number;
    projected_inventory_cost_rotation?: number;
    inventory_cost_rotation_rate?: number;
    remaining_inventory_cost_exposure?: number;
    projection_status?: string;
  };
  explanation?: {
    explanation_id: string;
    reason_codes: string[];
  };
  metadata: {
    dataset_version: string;
    policy_version: string;
    engine_version: string;
  };
  created_at: string;
  updated_at: string;
}

type QueueSegment = 'TODAY' | 'NEEDS_APPROVAL' | 'ACCEPTED' | 'MISSING_DATA' | 'ALL';

interface MerchantOptionSet {
  version?: string;
  scope?: {
    source_type?: string | null;
    source_key?: string | null;
    analysis_as_of?: string | null;
    warehouse_scope?: string | string[] | null;
    channel_scope?: string | string[] | null;
    fact_state?: string;
  };
  options?: MerchantOption[];
  financial_boundary?: string;
}

interface MerchantOption {
  option_key?: string;
  label: string;
  tradeoff: string;
  status?: string;
  status_label?: string;
  is_recommended?: boolean;
  reasons?: string[];
  financial_scenario?: {
    status?: string;
    message?: string;
    projected_inventory_cost_rotation?: number | null;
    projected_net_contribution?: number | null;
    projected_gross_sales?: number | null;
  };
}

interface RecommendationOption {
  key: string;
  label: string;
  tradeoff: string;
  status: string;
  statusLabel: string;
  reasons: string[];
  isPrimary: boolean;
  financialScenario?: MerchantOption['financial_scenario'];
}

interface DecisionNextAction {
  kind: 'evidence' | 'approve' | 'revalidate' | 'plan' | 'resolved';
  label: string;
  helper: string;
}

@Component({
  selector: 'app-decision-support-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, PageMotionDirective],
  templateUrl: './decision-support-dashboard.component.html',
  styleUrls: ['./decision-support-dashboard.component.css']
})
export class DecisionSupportDashboardComponent implements OnInit, OnDestroy {
  @Output() navigateTo = new EventEmitter<string>();

  isLoading = false;
  errorMessage = '';
  dataState: 'loading' | 'ready' | 'empty' | 'error' = 'loading';

  decisions: DecisionItem[] = [];
  filteredDecisions: DecisionItem[] = [];

  // Summary KPIs
  totalAtRiskSkus = 0;
  criticalSkus = 0;
  totalCapitalExposure = 0;
  totalExpectedRecovery = 0;
  highPriorityCount = 0;
  pendingDecisionsCount = 0;
  decisionSummary = {
    total_decisions: 0,
    at_risk_skus: 0,
    high_priority_count: 0,
    needs_review_count: 0,
    capital_exposure: 0,
    projected_recovery_value: 0,
    projected_sku_count: 0,
    unprojected_at_risk_sku_count: 0,
  };
  isDecisionSummaryLoading = false;
  isRefreshingRecommendations = false;
  decisionDataStatus: any = null;
  isDecisionDataStatusLoading = false;
  decisionLearningReport: any = null;
  portfolioQueue: any = null;
  portfolioCapacity: number | null = null;
  portfolioBudget: number | null = null;
  portfolioWindowDays = 7;
  isPortfolioQueueLoading = false;
  portfolioQueueError = '';
  weeklyActionPlan: any = null;
  weeklyActionPlanError = '';
  isWeeklyActionPlanLoading = false;
  weeklyAssigneeUserId: number | null = null;

  // Filter & Sort State
  selectedRiskClass = 'ALL';
  selectedPriority = 'P1,P2';
  selectedActionType = 'ALL';
  selectedStatus = 'GENERATED,RECOMMENDED,NEEDS_REVIEW,REVIEWED';
  selectedProjectionStatus = 'ALL';
  selectedSortField = 'priority'; // priority, capital, recovery, risk
  activeQueueSegment: QueueSegment = 'TODAY';
  searchQuery = '';
  decisionPagination = { page: 1, page_size: 20, has_previous: false, has_next: false, next_cursor: null as string | null };
  private decisionCursor: string | null = null;
  private decisionCursorHistory: Array<string | null> = [null];
  private decisionSearchTimer: ReturnType<typeof setTimeout> | null = null;
  targetSkuParam: string | null = null;
  autoOpenedSku = false;

  // Drawer & Detail State
  selectedDecision: DecisionItem | null = null;
  selectedExplanation: any = null;
  selectedHistory: any[] = [];
  decisionRevalidation: any = null;
  isDecisionRevalidating = false;
  isDrawerOpen = false;
  activeTab: 'OVERVIEW' | 'EXPLANATION' | 'EVIDENCE' | 'HISTORY' = 'OVERVIEW';
  isEvidenceOpen = false;
  isSimulationOpen = false;
  isReviewingEvidence = false;
  private lastFocusedElement: HTMLElement | null = null;
  private simulationRequestSequence = 0;
  @ViewChild('drawerPanel') private drawerPanel?: ElementRef<HTMLElement>;

  // Simulation Engine State (SIM-001 & SIM-002)
  simDiscountRate = 15;
  simDurationDays = 14;
  isSimulating = false;
  sim001Result: any = null;
  sim002Result: any = null;
  simulationError = '';

  // ACT-001 & ACT-002 Action Plan State
  actionPlans: any[] = [];
  actionPlanSummary = {
    open_plans: 0,
    overdue_plans: 0,
    in_progress_plans: 0,
    completed_plans: 0,
    completed_sku_count: 0,
    expected_recovery_value: 0,
    actual_recovery_value: 0,
    projected_inventory_cost_rotation: 0,
    merchant_reported_inventory_cost_rotation: 0,
    expected_sales_value: 0,
    actual_sales_value: 0,
  };
  isActionPlansLoading = false;
  actionPlanStatusFilter = 'ALL';
  actionPlanSearch = '';
  actionPlanPagination = { page: 1, page_size: 10, total_items: 0, total_pages: 1, has_previous: false, has_next: false };
  private actionPlanSearchTimer: ReturnType<typeof setTimeout> | null = null;
  actionPlanAssignees: Array<{ user_id: number; display_name: string; email: string; role: string }> = [];
  selectedChecklistPlan: any = null;
  checklistData: any = null;
  checklistLoading = false;
  checklistError = '';
  checklistEvidenceDrafts: Record<number, { title: string; reference_url: string; note: string }> = {};
  decisionEffectiveness: any = { status: 'PENDING_GROUND_TRUTH', k: 100, evaluated_k: 0 };
  isDecisionEffectivenessLoading = false;
  isCreatePlanModalOpen = false;
  planCampaign = '';
  planSku = '';
  planDuration = 14;
  planStrategy = 'MONITOR';
  planDiscountPercent: number | null = null;
  planStrategyOverrideReasonCode = '';
  planStrategyOverrideReason = '';
  planDataEvidenceOverrideReason = '';
  planEvidenceOverrideRequired = false;
  planOwner = '';
  planStartDate = '';
  planDueDate = '';
  planExpectedRecovery = 0;
  planExpectedSales = 0;
  planExpectedUnits = 0;
  planWarehouseCode = '';
  planChannel = '';
  planAssigneeUserId: number | null = null;
  planDecisionId: string | null = null;
  planNotes = '';

  // Outcome Tracking Modal State (ACT-004)
  isOutcomeModalOpen = false;
  selectedPlanForOutcome: any = null;
  outcomeExpectedRecovery = 0;
  outcomeActualRecovery = 0;
  outcomeExpectedSales = 0;
  outcomeActualSales = 0;
  outcomeExpectedUnits = 0;
  outcomeActualUnits = 0;
  outcomeNotes = '';
  outcomeAccuracyRecoveryPct = 0;
  outcomeAccuracyUnitsPct = 0;
  outcomeUsefulnessRating = 'Chưa đủ dữ liệu kết quả';
  outcomeNextStep = 'MONITOR';
  outcomeBusinessContext = '';

  // Rejection Modal State
  isRejectModalOpen = false;
  rejectionReason = 'TIMING_NOT_RIGHT';
  customRejectionNote = '';

  // Copilot Assistant State (COP-001 Context Awareness & COP-002 Grounded Answers)
  isCopilotOpen = false;
  activeCopilotSku = '';
  copilotQuery = '';
  copilotMessages: Array<{ sender: 'user' | 'copilot', text: string, pillars?: string[] }> = [];
  isCopilotLoading = false;

  constructor(
    private apiService: ApiService,
    private http: HttpClient,
    private route: ActivatedRoute,
    private router: Router,
    private dashboardState: DashboardStateService
  ) {}

  ngOnInit(): void {
    const paramSku = this.route.snapshot.queryParamMap.get('sku');
    if (paramSku) {
      this.targetSkuParam = paramSku;
      this.searchQuery = paramSku;
      // A deep link must not be hidden by the operational inbox's default
      // P1/P2 focus.
      this.selectedPriority = 'ALL';
      this.selectedStatus = 'ALL';
      this.activeQueueSegment = 'ALL';
    } else {
      this.targetSkuParam = null;
      this.searchQuery = '';
    }
    this.loadDecisions();
    this.loadDecisionSummary();
    this.loadDecisionDataStatus();
    this.loadDecisionLearningReport();
    this.loadActionPlans();
    this.loadActionPlanAssignees();
    this.loadDecisionEffectiveness();
    this.loadDecisionPortfolioQueue();
    this.loadWeeklyActionPlan();
  }

  ngOnDestroy(): void {
    if (this.actionPlanSearchTimer) clearTimeout(this.actionPlanSearchTimer);
    if (this.decisionSearchTimer) clearTimeout(this.decisionSearchTimer);
    document.body.style.overflow = '';
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.isOutcomeModalOpen) {
      this.closeOutcomeModal();
      return;
    }
    if (this.isCreatePlanModalOpen) {
      this.closeCreatePlanModal();
      return;
    }
    if (this.isRejectModalOpen) {
      this.closeRejectModal();
      return;
    }
    if (this.isDrawerOpen) this.closeDrawer();
  }

  loadDecisions(cursor: string | null = this.decisionCursor, page: number = this.decisionPagination.page): void {
    this.isLoading = true;
    this.dataState = 'loading';
    this.errorMessage = '';
    this.decisions = [];
    this.filteredDecisions = [];

    const filters: any = {};
    if (this.selectedRiskClass !== 'ALL') filters.risk_class = this.selectedRiskClass;
    if (this.selectedPriority !== 'ALL') filters.priority = this.selectedPriority;
    if (this.selectedActionType !== 'ALL') filters.action_type = this.selectedActionType;
    if (this.selectedStatus !== 'ALL') filters.status = this.selectedStatus;
    if (this.selectedProjectionStatus !== 'ALL') filters.projection_status = this.selectedProjectionStatus;
    filters.page_size = this.decisionPagination.page_size;
    filters.pagination = 'cursor';
    if (cursor) filters.cursor = cursor;
    filters.q = this.searchQuery.trim();
    filters.sort = this.selectedSortField;

    this.apiService.listDecisions(filters).subscribe({
      next: (response: DecisionItem[] | { items?: DecisionItem[]; pagination?: any }) => {
        const data = Array.isArray(response) ? response : (response?.items || []);
        this.decisionPagination = {
          ...this.decisionPagination,
          ...(Array.isArray(response)
            ? { page: 1, has_previous: false, has_next: false, next_cursor: null }
            : { ...(response?.pagination || {}), page, has_previous: page > 1 }),
        };
        this.decisionCursor = cursor;
        if (data && data.length > 0) {
          this.decisions = this.normalizeDecisionsData(data);
          this.applySearchFilter();
          this.calculateKpis();
          this.isLoading = false;
          this.dataState = 'ready';
        } else {
          this.isLoading = false;
          this.dataState = 'empty';
        }
      },
      error: (err: any) => {
        this.isLoading = false;
        this.dataState = 'error';
        this.errorMessage = err?.error?.error || 'Không thể tải các khuyến nghị đã được tạo. Vui lòng thử lại.';
      }
    });
  }

  loadDecisionSummary(): void {
    this.isDecisionSummaryLoading = true;
    this.apiService.getDecisionSummary().subscribe({
      next: (summary: any) => {
        this.decisionSummary = { ...this.decisionSummary, ...(summary || {}) };
        this.applyDecisionSummary();
        this.isDecisionSummaryLoading = false;
      },
      error: () => {
        // The paginated table remains usable if the optional portfolio summary
        // cannot be loaded. We intentionally do not present page totals as a
        // portfolio total in that case.
        this.isDecisionSummaryLoading = false;
      }
    });
  }

  loadDecisionDataStatus(): void {
    this.isDecisionDataStatusLoading = true;
    this.apiService.getDecisionDataStatus().subscribe({
      next: (payload: any) => {
        this.decisionDataStatus = payload;
        this.isDecisionDataStatusLoading = false;
      },
      error: () => {
        // The queue remains usable if this optional summary is unavailable.
        // Do not manufacture a browser-side assessment of merchant data.
        this.isDecisionDataStatusLoading = false;
      },
    });
  }

  loadDecisionLearningReport(): void {
    this.apiService.getDecisionLearningReport(7).subscribe({
      next: (payload: any) => this.decisionLearningReport = payload,
      error: () => this.decisionLearningReport = null,
    });
  }

  refreshRecommendations(): void {
    if (this.isRefreshingRecommendations) return;
    this.isRefreshingRecommendations = true;
    this.errorMessage = '';
    this.apiService.refreshDecisionRecommendations().subscribe({
      next: () => {
        this.isRefreshingRecommendations = false;
        if (this.isDrawerOpen) this.closeDrawer();
        this.resetDecisionCursor();
        this.loadDecisionSummary();
        this.loadDecisionDataStatus();
        this.loadDecisionPortfolioQueue();
        this.loadWeeklyActionPlan();
      },
      error: (err: any) => {
        this.isRefreshingRecommendations = false;
        this.errorMessage = err?.error?.error?.message
          || err?.error?.error
          || 'Không thể cập nhật khuyến nghị. Dữ liệu hiện tại vẫn được giữ nguyên.';
      }
    });
  }

  loadDecisionPortfolioQueue(): void {
    this.apiService.getDecisionPortfolioQueue().subscribe({
      next: (response) => this.portfolioQueue = response,
      error: (err: any) => {
        // A first-time merchant has no portfolio run yet; that is an empty
        // state, not a broken decision queue.
        if (err?.status !== 404) this.portfolioQueueError = err?.error?.error?.message || 'Không thể tải danh mục hành động.';
      },
    });
  }

  loadWeeklyActionPlan(): void {
    this.isWeeklyActionPlanLoading = true;
    this.weeklyActionPlanError = '';
    this.apiService.getWeeklyActionPlan().subscribe({
      next: (response: any) => {
        this.weeklyActionPlan = response;
        this.isWeeklyActionPlanLoading = false;
      },
      error: (err: any) => {
        this.weeklyActionPlan = null;
        this.isWeeklyActionPlanLoading = false;
        if (err?.status !== 404) this.weeklyActionPlanError = err?.error?.error?.message || 'Không thể tải kế hoạch tuần.';
      },
    });
  }

  createWeeklyActionPlan(): void {
    if (!this.portfolioQueue?.run_id || this.isWeeklyActionPlanLoading) return;
    this.isWeeklyActionPlanLoading = true;
    this.weeklyActionPlanError = '';
    const assignments: Record<string, number> = {};
    if (this.weeklyAssigneeUserId) {
      (this.portfolioQueue?.sections?.selected || []).forEach((item: any) => {
        assignments[item.decision_id] = this.weeklyAssigneeUserId as number;
      });
    }
    this.apiService.createWeeklyActionPlan({
      portfolio_run_id: this.portfolioQueue.run_id,
      assignments,
    }).subscribe({
      next: (response: any) => {
        this.weeklyActionPlan = response;
        this.isWeeklyActionPlanLoading = false;
      },
      error: (err: any) => {
        this.weeklyActionPlanError = err?.error?.error?.message || 'Không thể lập kế hoạch tuần.';
        this.isWeeklyActionPlanLoading = false;
      },
    });
  }

  buildDecisionPortfolioQueue(): void {
    if (this.isPortfolioQueueLoading) return;
    this.isPortfolioQueueLoading = true;
    this.portfolioQueueError = '';
    const capacity: any = {};
    if (this.portfolioCapacity !== null && this.portfolioCapacity !== undefined) capacity.max_actions = this.portfolioCapacity;
    const constraints: any = { capacity, window_days: this.portfolioWindowDays };
    if (this.portfolioBudget !== null && this.portfolioBudget !== undefined) {
      constraints.campaign_budget = { amount: this.portfolioBudget, currency: 'VND' };
    }
    this.apiService.buildDecisionPortfolioQueue(constraints).subscribe({
      next: (response) => {
        this.portfolioQueue = response;
        this.isPortfolioQueueLoading = false;
      },
      error: (err: any) => {
        this.portfolioQueueError = err?.error?.error?.message || 'Không thể lập danh mục hành động.';
        this.isPortfolioQueueLoading = false;
      },
    });
  }

  portfolioQueueStateLabel(state: string): string {
    const labels: Record<string, string> = {
      SELECTED: 'Được chọn trong kỳ này',
      DEFERRED_CAPACITY: 'Hoãn do hết năng lực',
      DEFERRED_BUDGET: 'Hoãn do ngân sách',
      BLOCKED_CONFLICT: 'Bị chặn do xung đột kế hoạch',
      BLOCKED_STALE: 'Không còn là khuyến nghị hiện hành',
      REVIEW_REQUIRED: 'Cần rà soát',
      DATA_NEEDED: 'Cần bổ sung dữ liệu',
    };
    return labels[state] || 'Cần rà soát';
  }

  goToImport(): void {
    this.router.navigate(['/app/import']);
  }

  normalizeDecisionsData(data: DecisionItem[]): DecisionItem[] {
    return data.map((item) => {
      const cap = Number(item.financial_impact?.capital_exposure ?? 0);
      const discountRate = item.decision?.discount_rate ?? null;
      const rec = Number(item.financial_impact?.expected_recovery_value ?? 0);
      const residual = Number(item.financial_impact?.residual_exposure ?? Math.max(0, cap - rec));
      const recRate = Number(item.financial_impact?.recovery_rate ?? (cap > 0 ? rec / cap : 0));

      return {
        ...item,
        decision: {
          ...item.decision,
          discount_rate: discountRate
        },
        financial_impact: {
          capital_exposure: cap,
          expected_recovery_value: rec,
          recovery_rate: recRate,
          residual_exposure: residual
        }
      };
    });
  }

  getDiscountPercent(item: DecisionItem): number {
    if (!item.decision.discount_rate && item.decision.discount_rate !== 0) return 0;
    return Math.round(item.decision.discount_rate * 100);
  }

  applySearchFilter(): void {
    let result = [...this.decisions];

    if (this.selectedRiskClass !== 'ALL') {
      result = result.filter(d => d.risk.class === this.selectedRiskClass);
    }
    if (this.selectedPriority !== 'ALL') {
      const priorities = this.selectedPriority.split(',').map(value => value.trim()).filter(Boolean);
      result = result.filter(d => priorities.includes(d.decision.priority));
    }
    if (this.selectedActionType !== 'ALL') {
      result = result.filter(d => {
        const act = (d.decision.action || '').toUpperCase();
        const sel = this.selectedActionType.toUpperCase();
        if (sel === 'MONITOR' || sel === 'MONITOR_INVENTORY') {
          return act.includes('MONITOR');
        }
        if (sel === 'CLEARANCE') {
          return act.includes('CLEARANCE');
        }
        if (sel === 'DISCOUNT') {
          return act.includes('DISCOUNT');
        }
        if (sel === 'BUNDLE') {
          return act.includes('BUNDLE');
        }
        if (sel === 'PROMOTION') {
          return act.includes('PROMOTION') || act.includes('FLASH');
        }
        if (sel === 'REPOSITION') {
          return act.includes('REPOSITION');
        }
        if (sel === 'HOLD') {
          return act.includes('HOLD');
        }
        return act === sel;
      });
    }
    if (this.selectedStatus !== 'ALL') {
      const statuses = this.selectedStatus.split(',').map(value => value.trim()).filter(Boolean);
      result = result.filter(d => statuses.includes(d.decision.status));
    }

    if (this.searchQuery && this.searchQuery.trim() !== '') {
      const query = this.searchQuery.toLowerCase().trim();
      result = result.filter(d =>
        d.sku.toLowerCase().includes(query) ||
        d.decision_id.toLowerCase().includes(query) ||
        d.decision.action.toLowerCase().includes(query)
      );
    }

    result.sort((a, b) => {
      let valA: number = 0;
      let valB: number = 0;

      if (this.selectedSortField === 'capital') {
        valA = a.financial_impact?.capital_exposure || 0;
        valB = b.financial_impact?.capital_exposure || 0;
      } else if (this.selectedSortField === 'recovery') {
        valA = a.financial_impact?.expected_recovery_value || 0;
        valB = b.financial_impact?.expected_recovery_value || 0;
      } else if (this.selectedSortField === 'risk') {
        valA = a.risk?.score || 0;
        valB = b.risk?.score || 0;
      } else {
        valA = a.decision?.priority_score || 0;
        valB = b.decision?.priority_score || 0;
      }

      return valB - valA;
    });

    this.filteredDecisions = result;

    if (this.targetSkuParam && !this.autoOpenedSku && this.filteredDecisions.length > 0) {
      const match = this.filteredDecisions.find(d => d.sku.toLowerCase() === this.targetSkuParam?.toLowerCase() || d.sku.toLowerCase().includes(this.targetSkuParam?.toLowerCase() || ''));
      if (match) {
        this.autoOpenedSku = true;
        this.openDecisionDetail(match);
      }
    }
  }

  exportDecisionReport(format: 'csv' | 'excel' = 'csv'): void {
    const headers = ['Mã đề xuất', 'Mã sản phẩm', 'Mức rủi ro', 'Phương án AI đề xuất', 'Mức giảm giá (%/giá)', 'Mức độ ưu tiên', 'Vốn tồn đọng (VND)', 'Dự kiến thu hồi (VND)', 'Tỉ lệ thu hồi (%)', 'Trạng thái phê duyệt'];
    const rows = this.filteredDecisions.map(d => [
      d.decision_id,
      d.sku,
      d.risk?.class === 'CRITICAL' ? 'Rủi ro rất cao' : (d.risk?.class === 'HIGH_RISK' ? 'Rủi ro cao' : (d.risk?.class === 'MEDIUM_RISK' ? 'Cần theo dõi' : 'Rủi ro thấp')),
      `"${this.translateAction(d.decision?.action)}"`,
      `${this.getDiscountPercent(d)}%`,
      d.decision?.priority || 'P2',
      d.financial_impact?.capital_exposure || 0,
      d.financial_impact?.expected_recovery_value || 0,
      `${Math.round((d.financial_impact?.recovery_rate || 0.6) * 100)}%`,
      `"${this.translateStatus(d.decision?.status)}"`
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const fileName = `bao_cao_de_xuat_phuong_an_${new Date().toISOString().split('T')[0]}.${format === 'excel' ? 'csv' : 'csv'}`;
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  exportActionPlanReport(format: 'csv' | 'excel' = 'csv'): void {
    const headers = ['Mã kế hoạch', 'Tên chiến dịch', 'Mã sản phẩm', 'Thời gian thực hiện (ngày)', 'Chiến lược áp dụng', 'Người phụ trách', 'Ngày bắt đầu', 'Hạn xử lý', 'Trạng thái thực hiện', 'Vốn thu hồi dự kiến (VND)', 'Vốn thu hồi thực tế (VND)', 'Doanh số dự kiến (VND)', 'Doanh số thực tế (VND)', 'Tỷ lệ đạt (%)'];
    const rows = this.filteredActionPlans.map(p => [
      p.plan_id,
      `"${(p.campaign_name || '').replace(/"/g, '""')}"`,
      p.sku,
      p.duration_days || 14,
      `"${(p.strategy || '').replace(/"/g, '""')}"`,
      `"${(p.owner || 'Chủ cửa hàng').replace(/"/g, '""')}"`,
      p.start_date || '',
      p.due_date || '',
      `"${this.translateActionPlanStatus(p.status)}"`,
      p.expected_recovery_value || 0,
      p.actual_recovery_value !== null && p.actual_recovery_value !== undefined ? p.actual_recovery_value : 0,
      p.expected_sales_value || 0,
      p.actual_sales_value !== null && p.actual_sales_value !== undefined ? p.actual_sales_value : 0,
      p.recovery_accuracy_pct ? `${p.recovery_accuracy_pct}%` : 'Chưa đánh giá'
    ]);

    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const fileName = `bao_cao_ke_hoach_xa_hang_${new Date().toISOString().split('T')[0]}.${format === 'excel' ? 'csv' : 'csv'}`;
    link.href = URL.createObjectURL(blob);
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  onFilterChange(): void {
    this.activeQueueSegment = 'ALL';
    this.resetDecisionCursor();
  }

  setQueueSegment(segment: QueueSegment): void {
    this.activeQueueSegment = segment;
    this.selectedRiskClass = 'ALL';
    this.selectedActionType = 'ALL';
    this.selectedProjectionStatus = 'ALL';
    this.selectedSortField = 'priority';

    switch (segment) {
      case 'TODAY':
        this.selectedPriority = 'P1,P2';
        this.selectedStatus = 'GENERATED,RECOMMENDED,NEEDS_REVIEW,REVIEWED';
        break;
      case 'NEEDS_APPROVAL':
        this.selectedPriority = 'ALL';
        this.selectedStatus = 'GENERATED,RECOMMENDED,NEEDS_REVIEW,REVIEWED';
        break;
      case 'ACCEPTED':
        this.selectedPriority = 'ALL';
        this.selectedStatus = 'ACCEPTED';
        break;
      case 'MISSING_DATA':
        this.selectedPriority = 'ALL';
        this.selectedStatus = 'GENERATED,RECOMMENDED,NEEDS_REVIEW,REVIEWED';
        this.selectedProjectionStatus = 'UNAVAILABLE';
        break;
      default:
        this.selectedPriority = 'ALL';
        this.selectedStatus = 'ALL';
    }

    this.resetDecisionCursor();
  }

  onDecisionSearchChanged(): void {
    if (this.decisionSearchTimer) clearTimeout(this.decisionSearchTimer);
    this.decisionSearchTimer = setTimeout(() => this.onFilterChange(), 300);
  }

  changeDecisionPage(page: number): void {
    if (page === this.decisionPagination.page || page < 1) return;
    if (page < this.decisionPagination.page) {
      const cursor = this.decisionCursorHistory[page - 1];
      if (cursor === undefined) return;
      this.loadDecisions(cursor, page);
      return;
    }
    const next = this.decisionPagination.next_cursor;
    if (!next || !this.decisionPagination.has_next) return;
    this.decisionCursorHistory = this.decisionCursorHistory.slice(0, this.decisionPagination.page);
    this.decisionCursorHistory.push(next);
    this.loadDecisions(next, page);
  }

  private resetDecisionCursor(): void {
    this.decisionCursor = null;
    this.decisionCursorHistory = [null];
    this.decisionPagination = { ...this.decisionPagination, page: 1, has_previous: false, has_next: false, next_cursor: null };
    this.loadDecisions(null, 1);
  }

  calculateKpis(): void {
    this.applyDecisionSummary();
  }

  private applyDecisionSummary(): void {
    this.totalAtRiskSkus = Number(this.decisionSummary.at_risk_skus || 0);
    this.criticalSkus = this.totalAtRiskSkus;
    this.totalCapitalExposure = Number(this.decisionSummary.capital_exposure || 0);
    this.totalExpectedRecovery = Number(this.decisionSummary.projected_recovery_value || 0);
    this.highPriorityCount = Number(this.decisionSummary.high_priority_count || 0);
    this.pendingDecisionsCount = Number(this.decisionSummary.needs_review_count || 0);
  }

  openDecisionDetail(decision: DecisionItem): void {
    this.simulationRequestSequence += 1;
    this.lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.selectedDecision = decision;
    this.activeCopilotSku = decision.sku; // COP-001 Context Awareness
    this.decisionRevalidation = null;
    this.isDrawerOpen = true;
    this.activeTab = 'OVERVIEW';
    this.isEvidenceOpen = false;
    this.isSimulationOpen = false;
    this.isReviewingEvidence = false;
    this.sim001Result = null;
    this.sim002Result = null;
    this.simulationError = '';
    this.isSimulating = false;
    // Keep an explicit 0% recommendation intact. It is a valid baseline,
    // not a missing value that should silently become a 15% experiment.
    this.simDiscountRate = Math.round((decision.decision.discount_rate ?? 0.15) * 100);
    this.simDurationDays = 14;
    document.body.style.overflow = 'hidden';
    setTimeout(() => this.drawerPanel?.nativeElement.focus());

    this.apiService.getDecisionExplanation(decision.decision_id).subscribe({
      next: (exp: any) => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.selectedExplanation = exp;
      },
      error: () => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.selectedExplanation = null;
      }
    });

    this.apiService.getDecisionHistory(decision.decision_id).subscribe({
      next: (hist: any) => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.selectedHistory = hist.history || [];
      },
      error: () => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.selectedHistory = [];
      }
    });

    this.apiService.getDecisionRevalidation(decision.decision_id).subscribe({
      next: (passport: any) => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.decisionRevalidation = passport;
      },
      error: () => {
        if (this.selectedDecision?.decision_id === decision.decision_id) this.decisionRevalidation = null;
      },
    });

  }

  openEvidence(): void {
    if (!this.selectedDecision) return;
    const decisionId = this.selectedDecision.decision_id;
    this.isEvidenceOpen = true;

    if (!this.canMarkReviewed(this.selectedDecision) || this.isReviewingEvidence) return;
    this.isReviewingEvidence = true;
    this.apiService.updateDecisionStatus(
      decisionId,
      'REVIEWED',
      'merchant',
      'Merchant explicitly opened recommendation evidence.'
    ).subscribe({
      next: (updated: DecisionItem) => {
        const localDecision = this.decisions.find(item => item.decision_id === decisionId);
        if (localDecision) localDecision.decision.status = updated.decision.status;
        this.calculateKpis();
        this.loadDecisionSummary();
        if (this.selectedDecision?.decision_id !== decisionId) return;
        this.selectedDecision.decision.status = updated.decision.status;
        this.isReviewingEvidence = false;
      },
      error: () => {
        if (this.selectedDecision?.decision_id !== decisionId) return;
        this.isReviewingEvidence = false;
        this.errorMessage = 'Không thể ghi nhận bước rà soát căn cứ. Bạn vẫn có thể xem thông tin chi tiết.';
      }
    });
  }

  openSimulation(): void {
    if (!this.selectedDecision) return;
    this.isSimulationOpen = true;
    if (this.canSimulateDecision(this.selectedDecision) && !this.isSimulating && !this.sim001Result) {
      this.runSimulation();
    } else if (!this.canSimulateDecision(this.selectedDecision)) {
      this.simulationError = this.getSimulationUnavailableMessage(this.selectedDecision);
    }
  }

  runSimulation(): void {
    if (!this.selectedDecision) return;
    if (!this.canSimulateDecision(this.selectedDecision)) {
      this.sim001Result = null;
      this.sim002Result = null;
      this.simulationError = this.getSimulationUnavailableMessage(this.selectedDecision);
      return;
    }
    const discountRate = this.simDiscountRate / 100.0;
    const durationDays = this.simDurationDays;
    const decisionId = this.selectedDecision.decision_id;
    const requestSequence = ++this.simulationRequestSequence;

    const payload = {
      decision_id: this.selectedDecision.decision_id,
      discount_rate: discountRate,
      duration_days: durationDays,
      discount_rates: [0.10, 0.15, 0.20]
    };

    this.isSimulating = true;
    this.simulationError = '';
    this.sim001Result = null;
    this.sim002Result = null;
    this.apiService.simulateDecision(payload).subscribe({
      next: (res: any) => {
        if (this.selectedDecision?.decision_id !== decisionId || requestSequence !== this.simulationRequestSequence) return;
        if (res && res.success) {
          this.sim001Result = res.sim_001;
          this.sim002Result = res.sim_002;
        } else {
          this.simulationError = 'Chưa đủ dữ liệu đầu vào để chạy mô phỏng cho SKU này.';
        }
        this.isSimulating = false;
      },
      error: (err: any) => {
        if (this.selectedDecision?.decision_id !== decisionId || requestSequence !== this.simulationRequestSequence) return;
        this.simulationError = err?.error?.error || err?.error?.detail || 'Chưa đủ dữ liệu đầu vào để chạy mô phỏng cho SKU này.';
        this.isSimulating = false;
      }
    });
  }

  updateSimDiscount(pct: number): void {
    this.simDiscountRate = pct;
    this.runSimulation();
  }

  updateSimDuration(days: number): void {
    this.simDurationDays = days;
    this.runSimulation();
  }

  closeDrawer(): void {
    this.simulationRequestSequence += 1;
    this.isDrawerOpen = false;
    this.selectedDecision = null;
    this.selectedExplanation = null;
    this.selectedHistory = [];
    this.decisionRevalidation = null;
    this.isEvidenceOpen = false;
    this.isSimulationOpen = false;
    this.isSimulating = false;
    document.body.style.overflow = '';
    const previousFocus = this.lastFocusedElement;
    this.lastFocusedElement = null;
    setTimeout(() => previousFocus?.focus());
  }

  trapDrawerFocus(event: Event): void {
    const keyboardEvent = event as KeyboardEvent;
    if (keyboardEvent.key !== 'Tab' || !this.drawerPanel) return;
    const focusable = Array.from(this.drawerPanel.nativeElement.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(element => !element.hasAttribute('hidden'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (keyboardEvent.shiftKey && document.activeElement === first) {
      keyboardEvent.preventDefault();
      last.focus();
    } else if (!keyboardEvent.shiftKey && document.activeElement === last) {
      keyboardEvent.preventDefault();
      first.focus();
    }
  }

  acceptDecision(decision: DecisionItem): void {
    if (this.canMarkReviewed(decision)) {
      this.errorMessage = 'Mở căn cứ quyết định trước khi phê duyệt phương án.';
      this.openEvidence();
      return;
    }
    this.apiService.updateDecisionStatus(decision.decision_id, 'ACCEPTED', 'merchant', 'Merchant accepted recommendation.').subscribe({
      next: (updated: DecisionItem) => {
        decision.decision.status = updated.decision.status;
        this.calculateKpis();
        this.loadDecisionSummary();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể phê duyệt đề xuất. Vui lòng thử lại.';
      }
    });
  }

  openRejectModal(): void {
    this.isRejectModalOpen = true;
  }

  closeRejectModal(): void {
    this.isRejectModalOpen = false;
  }

  confirmRejectDecision(): void {
    if (!this.selectedDecision) return;

    this.apiService.updateDecisionStatus(
      this.selectedDecision.decision_id,
      'REJECTED',
      'merchant',
      'Merchant chưa chọn phương án này.',
      { reason: this.rejectionReason, note: this.customRejectionNote.trim() },
    ).subscribe({
      next: (updated: DecisionItem) => {
        if (this.selectedDecision) {
          this.selectedDecision.decision.status = updated.decision.status;
        }
        this.closeRejectModal();
        this.calculateKpis();
        this.loadDecisionSummary();
        this.loadDecisionDataStatus();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể từ chối đề xuất. Vui lòng thử lại.';
      }
    });
  }

  markExecuted(decision: DecisionItem): void {
    this.apiService.updateDecisionStatus(decision.decision_id, 'EXECUTED', 'merchant', 'Merchant marked action as executed.').subscribe({
      next: (updated: DecisionItem) => {
        decision.decision.status = updated.decision.status;
        this.calculateKpis();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể cập nhật trạng thái thực hiện. Vui lòng thử lại.';
      }
    });
  }

  formatCurrency(value: number): string {
    if (!value && value !== 0) return '0M';
    if (value >= 1000000000) {
      return (value / 1000000000).toFixed(2) + 'B';
    } else if (value >= 1000000) {
      return (value / 1000000).toFixed(1) + 'M';
    } else if (value >= 1000) {
      return (value / 1000).toFixed(0) + 'K';
    }
    return value.toString();
  }

  formatPercent(rate: number): string {
    if (!rate && rate !== 0) return '0%';
    return (rate * 100).toFixed(1) + '%';
  }

  getPriorityBadgeClass(priority: string): string {
    switch (priority) {
      case 'P1': return 'bg-rose-50 text-rose-800 border-rose-200';
      case 'P2': return 'bg-amber-50 text-amber-800 border-amber-200';
      case 'P3': return 'bg-blue-50 text-blue-800 border-blue-200';
      case 'P4': return 'bg-slate-50 text-slate-700 border-slate-200';
      default: return 'bg-slate-50 text-slate-700 border-slate-200';
    }
  }

  getRiskBadgeClass(riskClass: string): string {
    switch (riskClass) {
      case 'CRITICAL':
      case 'HIGH_RISK': return 'bg-rose-50 text-rose-800 border-rose-200';
      case 'MEDIUM_RISK': return 'bg-amber-50 text-amber-800 border-amber-200';
      case 'LOW_RISK': return 'bg-emerald-50 text-emerald-800 border-emerald-200';
      default: return 'bg-slate-50 text-slate-700 border-slate-200';
    }
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'RECOMMENDED': return 'bg-blue-50 text-blue-800 border-blue-200';
      case 'REVIEWED': return 'bg-indigo-50 text-indigo-800 border-indigo-200';
      case 'ACCEPTED': return 'bg-emerald-50 text-emerald-800 border-emerald-200';
      case 'REJECTED': return 'bg-rose-50 text-rose-800 border-rose-200';
      case 'EXECUTED': return 'bg-purple-50 text-purple-800 border-purple-200';
      default: return 'bg-slate-50 text-slate-700 border-slate-200';
    }
  }

  translateAction(action: string): string {
    if (!action) return 'Theo dõi';
    const upper = action.toUpperCase().trim();
    switch (upper) {
      case 'MONITOR_INVENTORY':
      case 'MONITOR':
        return 'Theo dõi';
      case 'DISCOUNT_CLEARANCE':
      case 'CLEARANCE':
        return 'Giảm tồn kho ưu tiên';
      case 'DISCOUNT':
        return 'Điều chỉnh giá';
      case 'BUNDLE_PROMOTION':
      case 'BUNDLE':
        return 'Bán theo gói';
      case 'FLASH_SALE':
      case 'PROMOTION':
        return 'Tăng cường xúc tiến';
      case 'HOLD':
        return 'Duy trì giá';
      case 'REPOSITION':
        return 'Tái định vị';
      case 'RETURN_TO_SUPPLIER':
      case 'SUPPLIER_RETURN':
        return 'Hoàn trả nhà cung cấp';
      case 'STOP_REPLENISHMENT':
        return 'Ngừng nhập';
      case 'REVIEW':
      case 'NEEDS_REVIEW':
        return 'Rà soát';
      case 'NO_ACTION':
      case 'NOT_APPLICABLE':
        return 'Chưa xử lý';
      default:
        // Internal strategy identifiers are useful in logs, not in merchant UI.
        return /^[A-Z0-9_]+$/.test(upper) ? 'Rà soát phương án' : action;
    }
  }

  translateStatus(status: string): string {
    switch (status) {
      case 'RECOMMENDED': return 'Chờ duyệt';
      case 'NEEDS_REVIEW': return 'Cần rà soát điều kiện';
      case 'MONITOR': return 'Theo dõi';
      case 'NOT_APPLICABLE': return 'Chưa đủ điều kiện';
      case 'REVIEWED': return 'Đã xem chi tiết';
      case 'ACCEPTED': return 'Đã phê duyệt';
      case 'REJECTED': return 'Đã từ chối';
      case 'EXECUTED': return 'Đã thực thi';
      default: return /^[A-Z0-9_]+$/.test(String(status || '').trim()) ? 'Đang cập nhật' : status;
    }
  }

  // ── ACT-001 & ACT-002 Action Plan Management ──────────────────────────────
  loadActionPlans(page: number = this.actionPlanPagination.page): void {
    this.isActionPlansLoading = true;
    this.apiService.getActionPlans({
      page,
      page_size: this.actionPlanPagination.page_size,
      status: this.actionPlanStatusFilter,
      q: this.actionPlanSearch.trim(),
    }).subscribe({
      next: (res: any) => {
        this.actionPlans = Array.isArray(res) ? res : (res?.items || []);
        this.actionPlanPagination = {
          ...this.actionPlanPagination,
          ...(res?.pagination || { page: 1, total_items: this.actionPlans.length, total_pages: 1, has_previous: false, has_next: false }),
        };
        this.isActionPlansLoading = false;
      },
      error: () => {
        this.actionPlans = [];
        this.isActionPlansLoading = false;
      }
    });
    this.apiService.getActionPlanSummary().subscribe({
      next: (summary: any) => {
        this.actionPlanSummary = { ...this.actionPlanSummary, ...(summary || {}) };
      }
    });
  }

  get filteredActionPlans(): any[] {
    return this.actionPlans;
  }

  onActionPlanFiltersChanged(): void {
    this.actionPlanPagination.page = 1;
    this.loadActionPlans(1);
  }

  onActionPlanSearchChanged(): void {
    if (this.actionPlanSearchTimer) clearTimeout(this.actionPlanSearchTimer);
    this.actionPlanSearchTimer = setTimeout(() => this.onActionPlanFiltersChanged(), 300);
  }

  changeActionPlanPage(page: number): void {
    if (page < 1 || page > this.actionPlanPagination.total_pages || page === this.actionPlanPagination.page) return;
    this.loadActionPlans(page);
  }

  loadActionPlanAssignees(): void {
    this.apiService.getActionPlanAssignees().subscribe({
      next: (res: any) => this.actionPlanAssignees = res?.assignees || [],
      error: () => this.actionPlanAssignees = [],
    });
  }

  selectPlanAssignee(): void {
    const assignee = this.actionPlanAssignees.find(item => item.user_id === this.planAssigneeUserId);
    if (assignee) this.planOwner = assignee.display_name;
  }

  loadDecisionEffectiveness(): void {
    this.isDecisionEffectivenessLoading = true;
    this.apiService.getDecisionEffectiveness(this.decisionEffectiveness.k || 100).subscribe({
      next: (res: any) => {
        this.decisionEffectiveness = res || this.decisionEffectiveness;
        this.isDecisionEffectivenessLoading = false;
      },
      error: () => {
        this.decisionEffectiveness = { ...this.decisionEffectiveness, status: 'UNAVAILABLE' };
        this.isDecisionEffectivenessLoading = false;
      }
    });
  }

  confirmMerchantPlan(plan: any): void {
    this.updateActionPlanStatus(plan, 'CONFIRMED');
  }

  startExecutingPlan(plan: any): void {
    this.updateActionPlanStatus(plan, 'IN_PROGRESS');
  }

  openOutcomeModal(plan: any): void {
    this.selectedPlanForOutcome = plan;
    this.outcomeExpectedRecovery = plan.expected_recovery_value || 0;
    this.outcomeActualRecovery = plan.actual_recovery_value ?? 0;
    this.outcomeExpectedSales = plan.expected_sales_value || 0;
    this.outcomeActualSales = plan.actual_sales_value ?? 0;
    this.outcomeExpectedUnits = plan.expected_units_sold || 0;
    this.outcomeActualUnits = plan.actual_units_sold ?? 0;
    this.outcomeNotes = plan.outcome_notes || '';
    this.outcomeNextStep = plan.outcome_review?.next_step || 'MONITOR';
    this.outcomeBusinessContext = plan.outcome_review?.business_context || '';
    this.calculateOutcomeMetrics();
    this.isOutcomeModalOpen = true;
  }

  openChecklist(plan: any): void {
    this.selectedChecklistPlan = plan;
    this.checklistData = plan.checklist || null;
    this.checklistError = '';
    this.checklistLoading = true;
    this.apiService.getActionPlanTasks(plan.plan_id).subscribe({
      next: (response: any) => {
        this.checklistData = response?.checklist || null;
        this.checklistLoading = false;
      },
      error: () => {
        this.checklistError = 'Chưa thể tải checklist. Hãy thử lại.';
        this.checklistLoading = false;
      },
    });
  }

  closeChecklist(): void {
    this.selectedChecklistPlan = null;
    this.checklistData = null;
    this.checklistEvidenceDrafts = {};
  }

  evidenceDraft(taskId: number): { title: string; reference_url: string; note: string } {
    if (!this.checklistEvidenceDrafts[taskId]) {
      this.checklistEvidenceDrafts[taskId] = { title: '', reference_url: '', note: '' };
    }
    return this.checklistEvidenceDrafts[taskId];
  }

  addChecklistEvidence(task: any): void {
    if (!this.selectedChecklistPlan) return;
    const draft = this.evidenceDraft(task.id);
    this.apiService.addActionPlanEvidence(this.selectedChecklistPlan.plan_id, task.id, draft).subscribe({
      next: (response: any) => {
        this.checklistData = response?.checklist || this.checklistData;
        this.checklistEvidenceDrafts[task.id] = { title: '', reference_url: '', note: '' };
        this.loadActionPlans();
      },
      error: (error: any) => this.checklistError = error?.error?.error?.message || 'Không thể lưu bằng chứng.',
    });
  }

  updateChecklistTask(task: any, nextStatus: 'COMPLETED' | 'SKIPPED'): void {
    if (!this.selectedChecklistPlan) return;
    const skippedReason = nextStatus === 'SKIPPED' ? window.prompt('Nêu lý do không thực hiện (ít nhất 8 ký tự):') || '' : '';
    if (nextStatus === 'SKIPPED' && skippedReason.length < 8) return;
    this.apiService.updateActionPlanTask(this.selectedChecklistPlan.plan_id, task.id, {
      status: nextStatus,
      skipped_reason: skippedReason,
    }).subscribe({
      next: (response: any) => {
        this.checklistData = response?.checklist || this.checklistData;
        this.loadActionPlans();
      },
      error: (error: any) => this.checklistError = error?.error?.error?.message || 'Không thể cập nhật công việc.',
    });
  }

  closeOutcomeModal(): void {
    this.isOutcomeModalOpen = false;
    this.selectedPlanForOutcome = null;
  }

  calculateOutcomeMetrics(): void {
    if (this.outcomeExpectedRecovery > 0) {
      this.outcomeAccuracyRecoveryPct = Math.round((this.outcomeActualRecovery / this.outcomeExpectedRecovery) * 1000) / 10.0;
    } else {
      this.outcomeAccuracyRecoveryPct = 0;
    }

    if (this.outcomeExpectedUnits > 0) {
      this.outcomeAccuracyUnitsPct = Math.round((this.outcomeActualUnits / this.outcomeExpectedUnits) * 1000) / 10.0;
    } else {
      this.outcomeAccuracyUnitsPct = 0;
    }

    const avgPct = (this.outcomeAccuracyRecoveryPct + this.outcomeAccuracyUnitsPct) / 2.0;
    if (avgPct >= 80) {
      this.outcomeUsefulnessRating = 'Kết quả đạt gần mức kịch bản đã lập';
    } else if (avgPct >= 60) {
      this.outcomeUsefulnessRating = 'Kết quả đạt một phần mức kịch bản đã lập';
    } else {
      this.outcomeUsefulnessRating = 'Cần rà soát bối cảnh thực hiện và giả định kịch bản';
    }
  }

  submitOutcomeTracking(): void {
    if (!this.selectedPlanForOutcome) return;

    const outcomeData = {
      merchant_reported_inventory_cost_rotation: this.outcomeActualRecovery,
      actual_sales_value: this.outcomeActualSales,
      actual_units_sold: this.outcomeActualUnits,
      outcome_notes: this.outcomeNotes,
      outcome_next_step: this.outcomeNextStep,
      outcome_business_context: this.outcomeBusinessContext,
    };

    this.apiService.recordActionPlanOutcome(this.selectedPlanForOutcome.plan_id, outcomeData).subscribe({
      next: (res: any) => {
        if (this.selectedPlanForOutcome) {
          this.selectedPlanForOutcome.actual_recovery_value = this.outcomeActualRecovery;
          this.selectedPlanForOutcome.merchant_reported_inventory_cost_rotation = this.outcomeActualRecovery;
          this.selectedPlanForOutcome.actual_units_sold = this.outcomeActualUnits;
          Object.assign(this.selectedPlanForOutcome, res);
        }
        this.closeOutcomeModal();
        this.loadActionPlans();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể lưu kết quả thực hiện. Vui lòng thử lại.';
      }
    });
  }

  openCreatePlanModal(decision?: DecisionItem): void {
    this.errorMessage = '';
    this.planDecisionId = decision?.decision_id || null;
    if (decision) {
      if (!this.canCreatePlanForDecision(decision)) {
        this.errorMessage = 'Cần phê duyệt khuyến nghị và hoàn tất bước rà soát trước khi lập kế hoạch triển khai.';
        return;
      }
      this.planSku = decision.sku;
      this.planCampaign = `Kế hoạch xử lý ${decision.sku}`;
      this.planStrategy = this.normalizedAction(decision.decision.action);
      this.planDiscountPercent = this.isPriceAction(this.planStrategy) && decision.decision.discount_rate !== null
        ? Math.round(decision.decision.discount_rate * 100)
        : null;
      this.planDuration = 14;
      this.planExpectedRecovery = this.hasProjection(decision) ? decision.financial_impact.expected_recovery_value || 0 : 0;
      this.planExpectedSales = 0;
      this.planExpectedUnits = 0;
    } else {
      this.planSku = '';
      this.planCampaign = '';
      this.planStrategy = 'MONITOR';
      this.planDiscountPercent = null;
      this.planDuration = 14;
      this.planExpectedRecovery = 0;
      this.planExpectedSales = 0;
      this.planExpectedUnits = 0;
    }
    this.planOwner = '';
    this.planAssigneeUserId = null;
    this.planStartDate = new Date().toISOString().split('T')[0];
    this.planDueDate = this.calculateDueDate(this.planStartDate, this.planDuration);
    this.planNotes = '';
    this.planWarehouseCode = '';
    this.planChannel = '';
    this.planStrategyOverrideReasonCode = '';
    this.planStrategyOverrideReason = '';
    this.planDataEvidenceOverrideReason = '';
    this.planEvidenceOverrideRequired = false;
    this.isCreatePlanModalOpen = true;
  }

  closeCreatePlanModal(): void {
    this.isCreatePlanModalOpen = false;
  }

  submitCreateActionPlan(): void {
    if (!this.planCampaign.trim() || !this.planSku.trim() || !this.planOwner.trim() || !this.planStrategy) {
      this.errorMessage = 'Cần nhập tên kế hoạch, SKU và người phụ trách trước khi tạo hàng chờ.';
      return;
    }
    const selectedDecision = this.planDecisionId ? this.decisions.find(item => item.decision_id === this.planDecisionId) : null;
    if (selectedDecision && this.isPlanOverride(selectedDecision)) {
      if (!this.planStrategyOverrideReasonCode) {
        this.errorMessage = 'Chọn lý do điều chỉnh để lưu lại bối cảnh thay đổi phương án.';
        return;
      }
      if (this.planStrategyOverrideReason.trim().length < 8) {
        this.errorMessage = 'Cần nêu thêm căn cứ khi dùng phương án hoặc mức giá khác với khuyến nghị.';
        return;
      }
    }
    if (this.planEvidenceOverrideRequired && this.planDataEvidenceOverrideReason.trim().length < 16) {
      this.errorMessage = 'Cần nêu lý do ngoại lệ tối thiểu 16 ký tự khi dữ liệu Odoo đã thay đổi.';
      return;
    }
    const payload = {
      campaign: this.planCampaign,
      sku: this.planSku,
      duration: this.planDuration,
      strategy: this.planStrategy,
      owner: this.planOwner,
      start: this.planStartDate,
      due_date: this.planDueDate,
      expected_recovery_value: this.planExpectedRecovery,
      expected_sales_value: this.planExpectedSales,
      expected_units_sold: this.planExpectedUnits,
      assignee_user_id: this.planAssigneeUserId,
      notes: this.planNotes,
      decision_id: this.planDecisionId,
      strategy_override_reason_code: this.planStrategyOverrideReasonCode,
      strategy_override_reason: this.planStrategyOverrideReason.trim(),
      data_evidence_override_reason: this.planDataEvidenceOverrideReason.trim(),
      execution_scope: {
        warehouse_code: this.planWarehouseCode.trim(),
        channel: this.planChannel.trim(),
      },
      execution_parameters: this.isPriceAction(this.planStrategy) && this.planDiscountPercent !== null
        ? { discount_rate: this.planDiscountPercent / 100 }
        : {},
    };

    this.apiService.createActionPlan(payload).subscribe({
      next: (res: any) => {
        if (res && res.success) {
          this.actionPlanPagination.page = 1;
        }
        this.closeCreatePlanModal();
        this.loadActionPlans();
      },
      error: (err: any) => {
        const payload = err?.error;
        this.planEvidenceOverrideRequired = Boolean(
          payload?.data_evidence?.override_allowed && payload?.error?.code === 'DECISION_REVALIDATION_REQUIRED'
        );
        this.errorMessage = payload?.error?.message || 'Không thể tạo kế hoạch xử lý. Vui lòng thử lại.';
      }
    });
  }

  updateActionPlanStatus(plan: any, newStatus: string): void {
    this.apiService.updateActionPlanStatus(plan.plan_id, newStatus).subscribe({
      next: (res: any) => {
        Object.assign(plan, res);
        this.loadDecisions();
        this.loadActionPlans();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error?.message || 'Không thể cập nhật trạng thái kế hoạch. Vui lòng thử lại.';
      }
    });
  }

  cancelActionPlan(plan: any): void {
    this.updateActionPlanStatus(plan, 'CANCELLED');
  }

  updatePlanDueDate(): void {
    this.planDueDate = this.calculateDueDate(this.planStartDate, this.planDuration);
  }

  private calculateDueDate(startDate: string, durationDays: number): string {
    const start = new Date(`${startDate}T00:00:00`);
    if (Number.isNaN(start.getTime())) return '';
    start.setDate(start.getDate() + Math.max(1, Number(durationDays) || 1));
    return start.toISOString().split('T')[0];
  }

  onPlanStrategyChanged(): void {
    const decision = this.planDecisionId ? this.decisions.find(item => item.decision_id === this.planDecisionId) : null;
    const selectedStrategy = this.normalizedAction(this.planStrategy);
    if (!this.isPriceAction(selectedStrategy)) {
      this.planDiscountPercent = null;
      this.syncPlanScenarioValue();
      return;
    }
    if (decision && selectedStrategy === this.normalizedAction(decision.decision.action) && decision.decision.discount_rate !== null) {
      this.planDiscountPercent = Math.round(decision.decision.discount_rate * 100);
    } else if (this.planDiscountPercent === null) {
      this.planDiscountPercent = 15;
    }
    this.syncPlanScenarioValue();
  }

  onPlanDiscountChanged(): void {
    this.syncPlanScenarioValue();
  }

  private syncPlanScenarioValue(): void {
    const decision = this.planDecisionId ? this.decisions.find(item => item.decision_id === this.planDecisionId) : null;
    if (!decision) return;
    this.planExpectedRecovery = this.hasProjection(decision) && !this.isPlanOverride(decision)
      ? decision.financial_impact.expected_recovery_value || 0
      : 0;
  }

  canCreatePlanForDecision(decision: DecisionItem): boolean {
    const action = this.normalizedAction(decision.decision.action);
    const requiresCurrentPriceCheck = this.isPriceAction(action);
    return decision.decision.status === 'ACCEPTED'
      && !['REVIEW', 'NO_ACTION', 'HOLD'].includes(action)
      && (!requiresCurrentPriceCheck || this.decisionRevalidation?.state === 'READY');
  }

  canSimulateDecision(decision: DecisionItem): boolean {
    return this.isPriceAction(this.normalizedAction(decision.decision.action))
      && !this.hasUnavailableProjection(decision);
  }

  hasProjection(decision: DecisionItem): boolean {
    return decision.decision.action_parameters?.projection?.status === 'SCENARIO_ESTIMATE';
  }

  hasUnavailableProjection(decision: DecisionItem): boolean {
    return decision.decision.action_parameters?.projection?.status === 'UNAVAILABLE';
  }

  getRecommendedDiscountLabel(decision: DecisionItem): string {
    const rate = decision.decision.discount_rate;
    if (rate === null || rate === undefined) return 'Chưa đề xuất';
    return `${Math.round(rate * 100)}%`;
  }

  getProjectionReadinessLabel(decision: DecisionItem): string {
    const readiness = decision.decision.action_parameters?.input_readiness || {};
    if (!this.isPriceAction(this.normalizedAction(decision.decision.action))) {
      return 'Không áp dụng';
    }
    if (this.hasProjection(decision)) {
      return 'Có kịch bản theo nhu cầu quan sát';
    }
    if (readiness.demand_observed && readiness.demand_positive === false) {
      return 'Đã có dữ liệu, chưa có nhu cầu bán';
    }
    if (this.hasUnavailableProjection(decision)) {
      if (readiness.inventory_observed === false) return 'Thiếu bản ghi tồn kho xác nhận';
      if (readiness.financial_inputs_complete === false) return 'Thiếu giá bán hoặc giá vốn';
      if (readiness.demand_observed === false) return 'Thiếu dữ liệu nhu cầu bán';
      return 'Cần cập nhật dữ liệu nguồn';
    }
    return 'Có thể kiểm tra theo dữ liệu hiện tại';
  }

  getSimulationUnavailableMessage(decision: DecisionItem): string {
    const readiness = decision.decision.action_parameters?.input_readiness || {};
    if (!this.isPriceAction(this.normalizedAction(decision.decision.action))) {
      return 'Kịch bản điều chỉnh giá không áp dụng cho phương án này.';
    }
    if (readiness.demand_observed && readiness.demand_positive === false) {
      return 'SKU có giá bán, giá vốn và tồn kho đầy đủ, nhưng chưa ghi nhận nhu cầu bán trong kỳ quan sát. Không tạo dự báo doanh số từ giảm giá.';
    }
    if (this.hasUnavailableProjection(decision)) {
      if (readiness.inventory_observed === false) {
        return 'Chưa có bản ghi tồn kho đã xác nhận tại thời điểm đánh giá. Cập nhật tồn kho rồi tạo lại khuyến nghị để lập kịch bản.';
      }
      if (readiness.financial_inputs_complete === false) {
        return 'Chưa có đủ giá bán hoặc giá vốn tại thời điểm đánh giá. Cập nhật dữ liệu tài chính rồi tạo lại khuyến nghị để lập kịch bản.';
      }
      if (readiness.demand_observed === false) {
        return 'Chưa có dữ liệu nhu cầu bán được quan sát tại thời điểm đánh giá. Hệ thống không dùng tồn kho để tự giả định doanh số.';
      }
      return 'Kịch bản chưa được lập tại thời điểm đánh giá. Cập nhật dữ liệu nguồn rồi tạo lại khuyến nghị để kiểm tra lại.';
    }
    return 'Có thể kiểm tra kịch bản bằng dữ liệu hiện tại của SKU.';
  }

  canMarkReviewed(decision: DecisionItem): boolean {
    return ['GENERATED', 'RECOMMENDED', 'NEEDS_REVIEW'].includes(decision.decision.status);
  }

  getDecisionNextAction(decision: DecisionItem): DecisionNextAction {
    if (this.canMarkReviewed(decision)) {
      return {
        kind: 'evidence',
        label: 'Xem căn cứ',
        helper: 'Đối chiếu dữ liệu và điều kiện trước khi phê duyệt.',
      };
    }
    if (decision.decision.status === 'REVIEWED') {
      return {
        kind: 'approve',
        label: 'Phê duyệt phương án',
        helper: 'Phê duyệt không tự thay đổi giá hay dữ liệu ERP.',
      };
    }
    if (decision.decision.status === 'ACCEPTED'
      && this.isPriceAction(this.normalizedAction(decision.decision.action))
      && this.decisionRevalidation?.state !== 'READY') {
      return {
        kind: 'revalidate',
        label: this.isDecisionRevalidating ? 'Đang kiểm tra dữ liệu...' : 'Kiểm tra dữ liệu trước khi lập kế hoạch',
        helper: this.decisionRevalidation?.message || 'Xác nhận tồn kho, giá vốn và giá bán hiện tại trước khi thực thi.',
      };
    }
    if (this.canCreatePlanForDecision(decision)) {
      return {
        kind: 'plan',
        label: 'Lập kế hoạch triển khai',
        helper: 'Kế hoạch mới được lưu ở dạng bản nháp để giao việc.',
      };
    }
    return {
      kind: 'resolved',
      label: 'Đã hoàn tất bước quyết định',
      helper: this.translateStatus(decision.decision.status),
    };
  }

  runNextDecisionAction(): void {
    if (!this.selectedDecision) return;
    const nextAction = this.getDecisionNextAction(this.selectedDecision);
    if (nextAction.kind === 'evidence') {
      this.openEvidence();
    } else if (nextAction.kind === 'approve') {
      this.acceptDecision(this.selectedDecision);
    } else if (nextAction.kind === 'revalidate') {
      this.approveDecisionRevalidation();
    } else if (nextAction.kind === 'plan') {
      this.openCreatePlanModal(this.selectedDecision);
    }
  }

  approveDecisionRevalidation(): void {
    if (!this.selectedDecision || this.isDecisionRevalidating) return;
    let note = '';
    if (this.decisionRevalidation?.state === 'NEEDS_RECHECK') {
      note = window.prompt('Dữ liệu đã thay đổi. Bạn đã kiểm tra điều gì trước khi tiếp tục?')?.trim() || '';
      if (note.length < 8) {
        this.errorMessage = 'Cần nêu ngắn gọn điều đã kiểm tra trước khi xác nhận theo dữ liệu mới.';
        return;
      }
    }
    this.isDecisionRevalidating = true;
    this.apiService.approveDecisionRevalidation(this.selectedDecision.decision_id, note).subscribe({
      next: (passport: any) => {
        this.decisionRevalidation = passport;
        this.isDecisionRevalidating = false;
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error?.message || 'Chưa thể xác nhận dữ liệu hiện tại. Hãy làm mới dữ liệu rồi kiểm tra lại.';
        this.isDecisionRevalidating = false;
      },
    });
  }

  getRecommendationOptions(decision: DecisionItem): RecommendationOption[] {
    const optionSet = decision.decision.options;
    if (Array.isArray(optionSet?.options) && optionSet.options.length > 0) {
      return optionSet.options
        .map((option, index) => ({
          key: String(option.option_key || `OPTION_${index + 1}`),
          label: option.label || 'Phương án cần rà soát',
          tradeoff: option.tradeoff || 'Cần đối chiếu điều kiện vận hành trước khi lập kế hoạch.',
          status: option.status || 'DATA_NEEDED',
          statusLabel: option.status_label || 'Cần bổ sung dữ liệu',
          reasons: Array.isArray(option.reasons) ? option.reasons : [],
          isPrimary: Boolean(option.is_recommended),
          financialScenario: option.financial_scenario,
        }))
        .sort((left, right) => Number(right.isPrimary) - Number(left.isPrimary));
    }

    // Decisions generated before the option-set contract retain a safe UI
    // fallback. It intentionally shows no suitability score or invented
    // financial value for an alternative.
    const primaryStrategy = this.normalizedAction(decision.decision.action);
    const ranked = Array.isArray(decision.decision.action_parameters?.alternative_strategies)
      ? decision.decision.action_parameters.alternative_strategies
      : [];
    const seen = new Set<string>([primaryStrategy]);
    const alternatives = ranked
      .map((candidate: any) => ({
        strategy: this.normalizedAction(candidate?.strategy || candidate),
      }))
      .filter(candidate => candidate.strategy && !seen.has(candidate.strategy))
      .filter(candidate => {
        seen.add(candidate.strategy);
        return true;
      })
      .slice(0, 2);
    const requiresReview = (decision.decision.action_parameters?.eligibility?.requires_review_actions || [])
      .map((action: string) => this.normalizedAction(action));

    return [
      {
        strategy: primaryStrategy,
        key: primaryStrategy,
        label: this.translateAction(primaryStrategy),
        tradeoff: this.getActionTradeoff(primaryStrategy),
        status: requiresReview.includes(primaryStrategy) || Boolean(decision.decision.action_parameters?.approval_required)
          ? 'APPROVAL_REQUIRED' : 'READY',
        statusLabel: requiresReview.includes(primaryStrategy) || Boolean(decision.decision.action_parameters?.approval_required)
          ? 'Cần phê duyệt' : 'Sẵn sàng lập kế hoạch',
        reasons: [],
        isPrimary: true,
      },
      ...alternatives.map(candidate => ({
        key: candidate.strategy,
        label: this.translateAction(candidate.strategy),
        tradeoff: this.getActionTradeoff(candidate.strategy),
        status: requiresReview.includes(candidate.strategy) ? 'APPROVAL_REQUIRED' : 'AVAILABLE',
        statusLabel: requiresReview.includes(candidate.strategy) ? 'Cần phê duyệt' : 'Có thể cân nhắc',
        reasons: [],
        isPrimary: false,
      }))
    ];
  }

  getOptionStatusClass(option: RecommendationOption): string {
    switch (option.status) {
      case 'READY': return 'bg-emerald-50 text-emerald-800 border-emerald-200';
      case 'AVAILABLE': return 'bg-sky-50 text-sky-800 border-sky-200';
      case 'APPROVAL_REQUIRED': return 'bg-amber-50 text-amber-800 border-amber-200';
      case 'NOT_RECOMMENDED': return 'bg-slate-100 text-slate-700 border-slate-200';
      case 'BLOCKED': return 'bg-rose-50 text-rose-800 border-rose-200';
      default: return 'bg-violet-50 text-violet-800 border-violet-200';
    }
  }

  getDecisionScopeText(decision: DecisionItem): string {
    const scope = decision.decision.options?.scope;
    if (!scope) return 'Phạm vi nguồn của bản quyết định cũ chưa được lưu theo định dạng hiển thị mới.';
    const asList = (value: string | string[] | null | undefined): string =>
      Array.isArray(value) ? value.filter(Boolean).join(', ') : String(value || '').trim();
    const parts = [
      scope.source_type === 'ODOO' ? 'Odoo' : scope.source_type === 'CSV' ? 'CSV' : scope.source_type,
      scope.analysis_as_of ? `dữ liệu đến ${new Date(scope.analysis_as_of).toLocaleDateString('vi-VN')}` : '',
      asList(scope.warehouse_scope) ? `kho: ${asList(scope.warehouse_scope)}` : '',
      asList(scope.channel_scope) ? `kênh: ${asList(scope.channel_scope)}` : '',
    ].filter(Boolean);
    return parts.length ? parts.join(' · ') : 'Chưa đủ thông tin phạm vi nguồn.';
  }

  getDecisionDataContract(decision: DecisionItem): {
    state: 'READY' | 'NEEDS_DATA' | 'CHECK_SOURCE';
    label: string; message: string; asOf: string;
    rows: Array<{ label: string; value: string; ready: boolean }>;
    reasons: string[]; refreshRule: string;
  } {
    const parameters = decision.decision.action_parameters || {};
    const facts = parameters.commercial_fact_snapshot || {};
    const readiness = parameters.input_readiness || facts.readiness || {};
    const hasFacts = Object.keys(facts).length > 0;
    const isReady = facts.state === 'READY';
    const has = (value: any) => value === true;
    const rows = [
      { label: 'Tồn kho', value: has(readiness.inventory_observed) ? 'Đã có số tồn đã xác nhận' : 'Chưa có số tồn đã xác nhận', ready: has(readiness.inventory_observed) },
      { label: 'Nhu cầu bán', value: has(readiness.demand_observed) ? 'Đã có dữ liệu bán quan sát' : 'Chưa có dữ liệu bán quan sát', ready: has(readiness.demand_observed) },
      { label: 'Giá bán và giá vốn', value: has(readiness.financial_inputs_complete) ? 'Đủ để kiểm tra phương án giá' : 'Chưa đủ để kiểm tra phương án giá', ready: has(readiness.financial_inputs_complete) },
      { label: 'Phạm vi dữ liệu', value: facts.source_scope_fingerprint ? 'Đã chốt kho, kênh và nguồn dữ liệu' : 'Chưa chốt rõ kho, kênh hoặc nguồn dữ liệu', ready: Boolean(facts.source_scope_fingerprint) },
    ];
    const reasons = Array.isArray(facts.reasons)
      ? facts.reasons.map((item: any) => String(item?.message || '')).filter(Boolean)
      : [];
    const asOf = facts.analysis_as_of
      ? `Dữ liệu được chốt ngày ${new Date(facts.analysis_as_of).toLocaleDateString('vi-VN')}`
      : 'Bản quyết định cũ chưa lưu đủ mốc dữ liệu.';
    const refreshRule = this.isPriceAction(this.normalizedAction(decision.decision.action))
      ? 'Nếu tồn kho, giá vốn hoặc giá bán đã đổi, hãy cập nhật lại trước khi áp dụng giá mới.'
      : 'Nếu tồn kho, nhu cầu bán hoặc phạm vi kho/kênh đã đổi, hãy cập nhật lại trước khi triển khai.';
    if (isReady) {
      return {
        state: 'READY', label: 'Đủ dữ liệu để xem xét',
        message: 'Các dữ liệu cần cho phương án này đã được lưu tại thời điểm đánh giá. Người phụ trách vẫn cần kiểm tra thực tế trước khi triển khai.',
        asOf, rows, reasons: [], refreshRule,
      };
    }
    if (!hasFacts) {
      return {
        state: 'CHECK_SOURCE', label: 'Cần kiểm tra nguồn dữ liệu',
        message: 'Bản quyết định này chưa có đầy đủ thông tin nguồn theo định dạng mới.',
        asOf, rows, reasons: ['Tạo lại khuyến nghị từ lần đánh giá hiện hành để có đầy đủ căn cứ.'], refreshRule,
      };
    }
    return {
      state: 'NEEDS_DATA', label: 'Cần bổ sung dữ liệu',
      message: 'Hệ thống chỉ giữ phương án ở bước rà soát và không dùng số kịch bản khi dữ liệu đầu vào chưa đủ.',
      asOf, rows, reasons: reasons.length ? reasons : ['Cần kiểm tra lại dữ liệu nguồn trước khi tiếp tục.'], refreshRule,
    };
  }

  getDecisionDataContractClass(state: string): string {
    if (state === 'READY') return 'decision-data-contract--ready';
    if (state === 'NEEDS_DATA') return 'decision-data-contract--needs-data';
    return 'decision-data-contract--check-source';
  }

  getDecisionDataStatusLabel(state: string): string {
    const labels: Record<string, string> = {
      READY_FOR_REVIEW: 'Có thể rà soát',
      CHECK_DATA: 'Cần kiểm tra dữ liệu',
      NO_CURRENT_DATA: 'Chưa có dữ liệu hiện hành',
    };
    return labels[state] || 'Đang kiểm tra dữ liệu';
  }

  getDecisionDataStatusClass(state: string): string {
    if (state === 'READY_FOR_REVIEW') return 'bg-emerald-50 border-emerald-200 text-emerald-900';
    if (state === 'CHECK_DATA') return 'bg-amber-50 border-amber-200 text-amber-900';
    return 'bg-slate-50 border-slate-200 text-slate-800';
  }

  getEvidenceSummary(decision: DecisionItem): string {
    return this.selectedExplanation?.risk_explanation?.summary
      || this.selectedExplanation?.decision_summary?.recommendation
      || decision.explanation?.reason_codes?.map(code => this.translateReasonCode(code)).join('. ')
      || 'Căn cứ chi tiết đang được tải từ hồ sơ quyết định.';
  }

  getEvidenceItems(): any[] {
    return Array.isArray(this.selectedExplanation?.evidences) ? this.selectedExplanation.evidences : [];
  }

  translateReasonCode(code: string): string {
    const labels: Record<string, string> = {
      CRITICAL_RISK: 'Rủi ro bán chậm rất cao',
      HIGH_RISK: 'Rủi ro bán chậm cao',
      HIGH_CAPITAL_EXPOSURE: 'Giá vốn đang chịu rủi ro lớn',
      HIGH_CAPITAL: 'Giá vốn đang chịu rủi ro lớn',
      LOW_SALES_VELOCITY: 'Tốc độ bán thấp',
      LOW_VELOCITY: 'Tốc độ bán thấp',
      NO_SALES_LAST_30D: 'Chưa phát sinh bán hàng trong 30 ngày gần nhất',
      NO_OBSERVED_SALE: 'Chưa có dữ liệu bán hàng quan sát được',
      LONG_TIME_SINCE_LAST_SALE: 'Đã lâu chưa phát sinh bán hàng',
      CRITICAL_AGING: 'Hàng tồn kho lâu ngày',
      SEVERE_AGING: 'Hàng tồn kho lâu ngày',
      ZERO_RECENT_DEMAND_NO_PRICE_PROJECTION: 'Chưa ghi nhận nhu cầu bán trong kỳ quan sát',
      PROJECTION_UNAVAILABLE_MISSING_OBSERVED_INPUT: 'Chưa đủ dữ liệu quan sát để lập kịch bản tài chính',
      DISCOUNT_REQUIRES_POSITIVE_DEMAND: 'Cần có nhu cầu bán quan sát được trước khi điều chỉnh giá',
      REQUIRES_MERCHANT_APPROVAL: 'Cần phê duyệt trước khi triển khai',
    };
    return labels[String(code || '').trim().toUpperCase()] || 'Điều kiện vận hành cần được rà soát';
  }

  translateEvidenceMetric(metric: string): string {
    const labels: Record<string, string> = {
      risk_class: 'Mức rủi ro',
      capital_exposure: 'Giá vốn có rủi ro',
      aging_days: 'Số ngày tồn kho',
      expected_recovery_value: 'Giá vốn tồn quay vòng theo kịch bản',
      projected_inventory_cost_rotation: 'Giá vốn tồn quay vòng theo kịch bản',
      priority_score: 'Điểm ưu tiên',
      top_shap_feature: 'Tín hiệu ảnh hưởng chính',
      sales_velocity_30d: 'Tốc độ bán trung bình 30 ngày',
      sales_velocity_90d: 'Tốc độ bán trung bình 90 ngày',
    };
    return labels[String(metric || '').trim().toLowerCase()] || 'Chỉ số đánh giá';
  }

  formatEvidenceValue(evidence: any): string {
    const metric = String(evidence?.metric || '').trim().toLowerCase();
    const value = evidence?.value;
    const numericValue = Number(value);
    if (metric === 'risk_class') return this.translateRiskClass(String(value || ''));
    if (['capital_exposure', 'expected_recovery_value', 'projected_inventory_cost_rotation'].includes(metric) && Number.isFinite(numericValue)) {
      return this.formatCurrency(numericValue);
    }
    if (metric === 'aging_days' && Number.isFinite(numericValue)) return `${numericValue} ngày`;
    if (metric === 'priority_score' && Number.isFinite(numericValue)) return numericValue.toFixed(2);
    if (metric === 'top_shap_feature') return this.translateFeatureName(String(value || ''));
    if (typeof value === 'string' && /^[A-Z0-9_]+$/.test(value.trim())) return this.translateReasonCode(value);
    return String(value ?? 'Chưa có dữ liệu');
  }

  translateRiskClass(riskClass: string): string {
    const labels: Record<string, string> = {
      CRITICAL: 'Rủi ro rất cao',
      HIGH_RISK: 'Rủi ro cao',
      MEDIUM_RISK: 'Cần theo dõi',
      LOW_RISK: 'Rủi ro thấp',
    };
    return labels[String(riskClass || '').trim().toUpperCase()] || 'Chưa phân loại';
  }

  private translateFeatureName(feature: string): string {
    const labels: Record<string, string> = {
      dsls: 'Số ngày kể từ lần bán gần nhất',
      sales_velocity_30d: 'Tốc độ bán trung bình 30 ngày',
      sales_velocity_90d: 'Tốc độ bán trung bình 90 ngày',
      inventory_age_days: 'Số ngày tồn kho',
      capital_exposure: 'Giá vốn có rủi ro',
    };
    return labels[String(feature || '').trim().toLowerCase()] || 'Tín hiệu dữ liệu nguồn';
  }

  getActionTradeoff(action: string): string {
    const tradeoffs: Record<string, string> = {
      DISCOUNT: 'Tăng tốc độ bán, đổi lại biên lợi nhuận thấp hơn.',
      CLEARANCE: 'Ưu tiên giảm lượng tồn, cần kiểm soát mức giá và phạm vi áp dụng.',
      PROMOTION: 'Tạo lực đẩy theo chiến dịch, cần kiểm soát chi phí ưu đãi.',
      BUNDLE: 'Bảo vệ giá niêm yết, phụ thuộc sản phẩm ghép phù hợp.',
      REPOSITION: 'Giữ giá, cần thêm công sức điều chuyển hoặc đổi kênh.',
      RETURN_TO_SUPPLIER: 'Giảm tồn thông qua nhà cung cấp, cần xác nhận điều khoản và chứng từ hoàn trả.',
      STOP_REPLENISHMENT: 'Hạn chế vốn đọng thêm, không giải phóng tồn hiện có ngay.',
      MONITOR: 'Ít rủi ro thay đổi, nhưng vốn có thể tiếp tục bị giữ lại.',
      HOLD: 'Giữ nguyên trạng thái, chưa tạo tác động giảm tồn ngay.',
    };
    return tradeoffs[this.normalizedAction(action)] || 'Cần đối chiếu điều kiện vận hành trước khi triển khai.';
  }

  isPriceAction(action: string): boolean {
    return ['DISCOUNT', 'CLEARANCE', 'PROMOTION'].includes(this.normalizedAction(action));
  }

  normalizedAction(action: string): string {
    const normalized = String(action || '').trim().toUpperCase().replace(/\s+/g, '_');
    const aliases: Record<string, string> = {
      DISCOUNT_CLEARANCE: 'CLEARANCE',
      BUNDLE_PROMOTION: 'BUNDLE',
      FLASH_SALE: 'PROMOTION',
      MONITOR_INVENTORY: 'MONITOR',
    };
    return aliases[normalized] || normalized;
  }

  get planStrategyOptions(): Array<{ value: string; label: string; requiresReview: boolean }> {
    const decision = this.planDecisionId ? this.decisions.find(item => item.decision_id === this.planDecisionId) : null;
    const labels: Record<string, string> = {
      HOLD: 'Giữ nguyên và theo dõi định kỳ',
      MONITOR: 'Theo dõi tín hiệu bán hàng',
      PROMOTION: 'Khuyến mại có kiểm soát',
      BUNDLE: 'Bán theo gói',
      DISCOUNT: 'Điều chỉnh giá có kiểm soát',
      CLEARANCE: 'Giải phóng tồn kho có phê duyệt',
      REPOSITION: 'Điều chuyển hoặc tái định vị',
      RETURN_TO_SUPPLIER: 'Hoàn trả nhà cung cấp',
      STOP_REPLENISHMENT: 'Tạm dừng tái nhập',
    };
    if (!decision) {
      return Object.entries(labels).map(([value, label]) => ({ value, label, requiresReview: false }));
    }
    const eligibility = decision.decision.action_parameters?.eligibility || {};
    const eligible = (eligibility.eligible_actions || []).map((action: string) => this.normalizedAction(action));
    const requiresReview = (eligibility.requires_review_actions || []).map((action: string) => this.normalizedAction(action));
    const options = Array.from(new Set([this.normalizedAction(decision.decision.action), ...eligible, ...requiresReview]))
      .filter(action => Boolean(labels[action]))
      .map(action => ({ value: action, label: labels[action], requiresReview: requiresReview.includes(action) }));
    return options.length ? options : [{
      value: this.normalizedAction(decision.decision.action),
      label: this.translateAction(decision.decision.action),
      requiresReview: false,
    }];
  }

  isPlanOverride(decision: DecisionItem): boolean {
    const actionChanged = this.normalizedAction(this.planStrategy) !== this.normalizedAction(decision.decision.action);
    const originalRate = decision.decision.discount_rate;
    const rateChanged = this.isPriceAction(this.planStrategy)
      && originalRate !== null
      && this.planDiscountPercent !== null
      && Math.abs(this.planDiscountPercent / 100 - originalRate) > 0.000001;
    return actionChanged || rateChanged;
  }

  isPlanOverrideForSelectedDecision(): boolean {
    const decision = this.planDecisionId
      ? this.decisions.find(item => item.decision_id === this.planDecisionId)
      : null;
    return Boolean(decision && this.isPlanOverride(decision));
  }

  getAlternatives(decision: DecisionItem): any[] {
    return decision.decision.action_parameters?.alternative_strategies || [];
  }

  getProjectedRecoveryPercent(): number {
    if (this.totalCapitalExposure <= 0) return 0;
    return Math.min(100, Math.max(0, (this.totalExpectedRecovery / this.totalCapitalExposure) * 100));
  }

  translateActionPlanStatus(status: string): string {
    switch (status) {
      case 'DRAFT': return 'Bản nháp (AI Đề xuất)';
      case 'CONFIRMED': return 'Đã xác nhận duyệt';
      case 'IN_PROGRESS': return 'Đang thực hiện';
      case 'COMPLETED': return 'Đã hoàn thành';
      case 'CANCELLED': return 'Đã hủy';
      default: return status;
    }
  }

  getActionPlanStatusClass(status: string): string {
    switch (status) {
      case 'DRAFT': return 'bg-slate-100 text-slate-700 border-slate-300';
      case 'CONFIRMED': return 'bg-blue-50 text-blue-800 border-blue-200';
      case 'IN_PROGRESS': return 'bg-amber-50 text-amber-800 border-amber-200';
      case 'COMPLETED': return 'bg-emerald-50 text-emerald-800 border-emerald-200';
      case 'CANCELLED': return 'bg-rose-50 text-rose-800 border-rose-200';
      default: return 'bg-slate-100 text-slate-700 border-slate-300';
    }
  }

  // ── COP-001 Context Awareness & COP-002 Grounded Answers Copilot ──────────
  toggleCopilot(sku?: string): void {
    if (sku) {
      this.activeCopilotSku = sku;
    } else if (this.selectedDecision) {
      this.activeCopilotSku = this.selectedDecision.sku;
    } else if (this.filteredDecisions.length > 0) {
      this.activeCopilotSku = this.filteredDecisions[0].sku;
    }
    this.isCopilotOpen = !this.isCopilotOpen;
    if (this.isCopilotOpen && this.copilotMessages.length === 0) {
      this.sendQuickCopilotQuestion(`Thông tin phân tích căn cứ cho mã ${this.activeCopilotSku}`);
    }
  }

  setCopilotContextSku(sku: string): void {
    this.activeCopilotSku = sku;
    this.copilotMessages.push({
      sender: 'copilot',
      text: `Đã cập nhật ngữ cảnh phân tích sang sản phẩm mã ${sku}. Bạn có thể đặt câu hỏi về rủi ro, lý do, vốn đọng, phương án xử lý tồn kho hoặc mô phỏng tài chính cho ${sku}.`
    });
  }

  sendQuickCopilotQuestion(question: string): void {
    this.copilotQuery = question;
    this.sendCopilotMessage();
  }

  sendCopilotMessage(): void {
    if (!this.copilotQuery || this.copilotQuery.trim() === '') return;

    const queryText = this.copilotQuery.trim();
    const contextSku = this.activeCopilotSku;

    this.copilotMessages.push({
      sender: 'user',
      text: queryText
    });
    this.copilotQuery = '';
    this.isCopilotLoading = true;

    this.http.post(`${this.apiService.getApiUrl()}/api/v1/copilot/chat/`, {
      query: queryText,
      context_sku: contextSku
    }).subscribe({
      next: (res: any) => {
        if (res && res.success) {
          this.copilotMessages.push({
            sender: 'copilot',
            text: res.answer,
            pillars: res.grounded_pillars || ['RỦI RO', 'GIẢI THÍCH', 'VỐN ĐỌNG', 'ĐỀ XUẤT', 'MÔ PHỎNG']
          });
        } else {
          this.computeGroundedCopilotFallback(queryText, contextSku);
        }
        this.isCopilotLoading = false;
      },
      error: () => {
        this.computeGroundedCopilotFallback(queryText, contextSku);
        this.isCopilotLoading = false;
      }
    });
  }

  computeGroundedCopilotFallback(queryText: string, contextSku: string): void {
    const item = this.decisions.find(d => d.sku === contextSku) || this.decisions[0];
    if (!item) {
      this.copilotMessages.push({
        sender: 'copilot',
        text: 'Chưa có dữ liệu quyết định cho SKU này, nên Trợ lý không thể đưa ra câu trả lời có căn cứ.'
      });
      return;
    }

    const cap = item.financial_impact.capital_exposure || 0;
    const rec = item.financial_impact.expected_recovery_value || 0;
    const discount = Math.round((item.decision.discount_rate || 0) * 100);
    const actionVi = this.translateAction(item.decision.action);
    const riskScore = item.risk.score || 0;
    const riskLabel = this.translateRiskClass(item.risk.class);
    const reasonSummary = item.explanation?.reason_codes?.length
      ? item.explanation.reason_codes.map(code => this.translateReasonCode(code)).join(', ')
      : 'Chưa có căn cứ bổ sung được lưu.';
    const actionSummary = discount > 0
      ? `${actionVi} với mức điều chỉnh giá ${discount}%`
      : actionVi;

    let text = '';
    if (queryText.toLowerCase().includes('tại sao') || queryText.toLowerCase().includes('lý do') || queryText.toLowerCase().includes('giải thích')) {
      text = `Phân tích căn cứ 5 chỉ số chính cho sản phẩm ${contextSku}:\n\n` +
        `1. Mức rủi ro: ${riskLabel} (điểm ${riskScore}).\n` +
        `2. Căn cứ: ${reasonSummary}.\n` +
        `3. Vốn đang chịu rủi ro: ${this.formatCurrency(cap)}.\n` +
        `4. Phương án: ${actionSummary}; giá trị theo kịch bản là ${this.formatCurrency(rec)}.\n` +
        `5. Mô phỏng: Các giá trị chỉ dựa trên dữ liệu quyết định hiện có.`;
    } else {
      text = `Thông tin phân tích thực tế 5 chỉ số cho mã ${contextSku}:\n\n` +
        `• Mã sản phẩm: ${contextSku}\n` +
        `• Mức rủi ro: ${riskLabel} (điểm ${riskScore})\n` +
        `• Giá vốn có rủi ro: ${this.formatCurrency(cap)}\n` +
        `• Phương án xử lý: ${actionSummary}\n` +
        `• Giá trị theo kịch bản: ${this.formatCurrency(rec)}`;
    }

    this.copilotMessages.push({
      sender: 'copilot',
      text: text,
      pillars: ['RỦI RO', 'GIẢI THÍCH', 'VỐN ĐỌNG', 'ĐỀ XUẤT', 'MÔ PHỎNG']
    });
  }
}
