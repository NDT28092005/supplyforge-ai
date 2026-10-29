import { Component, OnInit, OnDestroy, Output, EventEmitter } from '@angular/core';
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

  // Filter & Sort State
  selectedRiskClass = 'ALL';
  selectedPriority = 'ALL';
  selectedActionType = 'ALL';
  selectedStatus = 'ALL';
  selectedSortField = 'priority'; // priority, capital, recovery, risk
  searchQuery = '';
  targetSkuParam: string | null = null;
  autoOpenedSku = false;

  // Drawer & Detail State
  selectedDecision: DecisionItem | null = null;
  selectedExplanation: any = null;
  selectedHistory: any[] = [];
  isDrawerOpen = false;
  activeTab: 'OVERVIEW' | 'EXPLANATION' | 'EVIDENCE' | 'HISTORY' = 'OVERVIEW';

  // Simulation Engine State (SIM-001 & SIM-002)
  simDiscountRate = 15;
  simDurationDays = 14;
  isSimulating = false;
  sim001Result: any = null;
  sim002Result: any = null;
  simulationError = '';

  // ACT-001 & ACT-002 Action Plan State
  actionPlans: any[] = [];
  isCreatePlanModalOpen = false;
  planCampaign = '';
  planSku = '';
  planDuration = 14;
  planStrategy = 'Giảm giá 15%';
  planOwner = 'Merchant';
  planStartDate = '2026-09-28';
  planStatus = 'DRAFT';
  planNotes = '';

  // Outcome Tracking Modal State (ACT-004)
  isOutcomeModalOpen = false;
  selectedPlanForOutcome: any = null;
  outcomeExpectedRecovery = 12000000;
  outcomeActualRecovery = 9500000;
  outcomeExpectedUnits = 100;
  outcomeActualUnits = 82;
  outcomeAccuracyRecoveryPct = 79.2;
  outcomeAccuracyUnitsPct = 82.0;
  outcomeUsefulnessRating = 'Rất chính xác (Đề xuất hiệu quả cao)';

  // Rejection Modal State
  isRejectModalOpen = false;
  rejectionReason = 'RECOMMENDATION_NOT_SUITABLE';
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
    } else {
      this.targetSkuParam = null;
      this.searchQuery = '';
    }
    this.loadDecisions();
    this.loadActionPlans();
  }

  ngOnDestroy(): void {
    document.body.style.overflow = '';
  }

  loadDecisions(): void {
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

    this.apiService.listDecisions(filters).subscribe({
      next: (data: DecisionItem[]) => {
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
      result = result.filter(d => d.decision.priority === this.selectedPriority);
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
      result = result.filter(d => d.decision.status === this.selectedStatus);
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
    const headers = ['Mã kế hoạch', 'Tên chiến dịch', 'Mã sản phẩm', 'Thời gian thực hiện (ngày)', 'Chiến lược áp dụng', 'Người phụ trách', 'Ngày bắt đầu', 'Trạng thái thực hiện', 'Vốn thu hồi dự kiến (VND)', 'Vốn thu hồi thực tế (VND)', 'Độ chính xác AI (%)'];
    const rows = this.actionPlans.map(p => [
      p.plan_id,
      `"${(p.campaign_name || '').replace(/"/g, '""')}"`,
      p.sku,
      p.duration_days || 14,
      `"${(p.strategy || '').replace(/"/g, '""')}"`,
      `"${(p.owner || 'Chủ cửa hàng').replace(/"/g, '""')}"`,
      p.start_date || '2026-09-28',
      `"${this.translateActionPlanStatus(p.status)}"`,
      p.expected_recovery_value || 0,
      p.actual_recovery_value !== null && p.actual_recovery_value !== undefined ? p.actual_recovery_value : 0,
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
    this.applySearchFilter();
  }

  calculateKpis(): void {
    const atRiskDecisions = this.decisions.filter(d => ['CRITICAL', 'HIGH_RISK'].includes(d.risk.class));
    this.totalAtRiskSkus = atRiskDecisions.length;
    this.criticalSkus = atRiskDecisions.length;
    // Portfolio recovery KPIs describe the actionable high-risk cohort, not
    // every decision record including low-risk monitoring recommendations.
    this.totalCapitalExposure = atRiskDecisions.reduce((acc, d) => acc + d.financial_impact.capital_exposure, 0);
    this.totalExpectedRecovery = atRiskDecisions.reduce((acc, d) => acc + d.financial_impact.expected_recovery_value, 0);
    this.highPriorityCount = this.decisions.filter(d => ['P1', 'P2'].includes(d.decision.priority)).length;
    this.pendingDecisionsCount = this.decisions.filter(d => ['RECOMMENDED', 'GENERATED', 'REVIEWED'].includes(d.decision.status)).length;
  }

  openDecisionDetail(decision: DecisionItem): void {
    this.selectedDecision = decision;
    this.activeCopilotSku = decision.sku; // COP-001 Context Awareness
    this.isDrawerOpen = true;
    this.activeTab = 'OVERVIEW';
    this.simDiscountRate = Math.round((decision.decision.discount_rate || 0.15) * 100);
    this.simDurationDays = 14;
    this.runSimulation();
    document.body.style.overflow = 'hidden';

    this.apiService.getDecisionExplanation(decision.decision_id).subscribe({
      next: (exp: any) => { this.selectedExplanation = exp; },
      error: (err: any) => { this.selectedExplanation = null; }
    });

    this.apiService.getDecisionHistory(decision.decision_id).subscribe({
      next: (hist: any) => { this.selectedHistory = hist.history || []; },
      error: (err: any) => { this.selectedHistory = []; }
    });

    if (decision.decision.status === 'RECOMMENDED' || decision.decision.status === 'GENERATED') {
      this.apiService.updateDecisionStatus(decision.decision_id, 'REVIEWED', 'merchant', 'Merchant opened decision detail drawer.').subscribe({
      next: (updated: DecisionItem) => {
          decision.decision.status = updated.decision.status;
          this.calculateKpis();
        },
        error: () => { /* Opening a drawer must not mutate a failed decision update. */ }
      });
    }
  }

  runSimulation(): void {
    if (!this.selectedDecision) return;
    const discountRate = this.simDiscountRate / 100.0;
    const durationDays = this.simDurationDays;

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
        if (res && res.success) {
          this.sim001Result = res.sim_001;
          this.sim002Result = res.sim_002;
        } else {
          this.simulationError = 'Chưa đủ dữ liệu đầu vào để chạy mô phỏng cho SKU này.';
        }
        this.isSimulating = false;
      },
      error: (err: any) => {
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
    this.isDrawerOpen = false;
    this.selectedDecision = null;
    this.selectedExplanation = null;
    this.selectedHistory = [];
    document.body.style.overflow = '';
  }

  acceptDecision(decision: DecisionItem): void {
    this.apiService.updateDecisionStatus(decision.decision_id, 'ACCEPTED', 'merchant', 'Merchant accepted recommendation.').subscribe({
      next: (updated: DecisionItem) => {
        decision.decision.status = updated.decision.status;
        this.calculateKpis();
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

    const notes = `Rejected: ${this.rejectionReason} ${this.customRejectionNote ? '- ' + this.customRejectionNote : ''}`;
    this.apiService.updateDecisionStatus(this.selectedDecision.decision_id, 'REJECTED', 'merchant', notes).subscribe({
      next: (updated: DecisionItem) => {
        if (this.selectedDecision) {
          this.selectedDecision.decision.status = updated.decision.status;
        }
        this.closeRejectModal();
        this.calculateKpis();
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
      case 'STOP_REPLENISHMENT':
        return 'Ngừng nhập';
      case 'REVIEW':
      case 'NEEDS_REVIEW':
        return 'Rà soát';
      case 'NO_ACTION':
      case 'NOT_APPLICABLE':
        return 'Chưa xử lý';
      default:
        return action.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, l => l.toUpperCase());
    }
  }

  translateStatus(status: string): string {
    switch (status) {
      case 'RECOMMENDED': return 'Chờ duyệt';
      case 'REVIEWED': return 'Đã xem chi tiết';
      case 'ACCEPTED': return 'Đã phê duyệt';
      case 'REJECTED': return 'Đã từ chối';
      case 'EXECUTED': return 'Đã thực thi';
      default: return status;
    }
  }

  // ── ACT-001 & ACT-002 Action Plan Management ──────────────────────────────
  loadActionPlans(): void {
    this.apiService.getActionPlans().subscribe({
      next: (res: any) => {
        if (res && res.success && res.plans) {
          this.actionPlans = res.plans;
        } else if (Array.isArray(res)) {
          this.actionPlans = res;
        } else {
          this.actionPlans = [];
        }
      },
      error: () => {
        this.actionPlans = [];
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
    this.outcomeExpectedUnits = plan.expected_units_sold || 0;
    this.outcomeActualUnits = plan.actual_units_sold ?? 0;
    this.calculateOutcomeMetrics();
    this.isOutcomeModalOpen = true;
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
      this.outcomeUsefulnessRating = 'Rất chính xác (Đề xuất hiệu quả cao)';
    } else if (avgPct >= 60) {
      this.outcomeUsefulnessRating = 'Khá chính xác (Đạt kỳ vọng cơ bản)';
    } else {
      this.outcomeUsefulnessRating = 'Cần điều chỉnh thuật toán AI';
    }
  }

  submitOutcomeTracking(): void {
    if (!this.selectedPlanForOutcome) return;

    const outcomeData = {
      actual_recovery_value: this.outcomeActualRecovery,
      actual_units_sold: this.outcomeActualUnits,
      expected_recovery_value: this.outcomeExpectedRecovery,
      expected_units_sold: this.outcomeExpectedUnits
    };

    this.apiService.recordActionPlanOutcome(this.selectedPlanForOutcome.plan_id, outcomeData).subscribe({
      next: (res: any) => {
        if (this.selectedPlanForOutcome) {
          this.selectedPlanForOutcome.actual_recovery_value = this.outcomeActualRecovery;
          this.selectedPlanForOutcome.actual_units_sold = this.outcomeActualUnits;
          this.selectedPlanForOutcome.expected_recovery_value = this.outcomeExpectedRecovery;
          this.selectedPlanForOutcome.expected_units_sold = this.outcomeExpectedUnits;
          this.selectedPlanForOutcome.recovery_accuracy_pct = this.outcomeAccuracyRecoveryPct;
          this.selectedPlanForOutcome.units_accuracy_pct = this.outcomeAccuracyUnitsPct;
          this.selectedPlanForOutcome.status = 'COMPLETED';
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
    if (decision) {
      this.planSku = decision.sku;
      this.planCampaign = `Kế hoạch xử lý tồn kho ${decision.sku}`;
      const discPct = Math.round((decision.decision.discount_rate || 0.15) * 100);
      this.planStrategy = `Giảm giá ${discPct}%`;
      this.planDuration = 14;
    } else {
      this.planSku = '';
      this.planCampaign = '';
      this.planStrategy = 'Giảm giá 15%';
      this.planDuration = 14;
    }
    this.planOwner = 'Merchant';
    this.planStartDate = new Date().toISOString().split('T')[0];
    this.planStatus = 'DRAFT';
    this.planNotes = '';
    this.isCreatePlanModalOpen = true;
  }

  closeCreatePlanModal(): void {
    this.isCreatePlanModalOpen = false;
  }

  submitCreateActionPlan(): void {
    const payload = {
      campaign: this.planCampaign,
      sku: this.planSku,
      duration: this.planDuration,
      strategy: this.planStrategy,
      owner: this.planOwner,
      start: this.planStartDate,
      status: this.planStatus,
      notes: this.planNotes,
      decision_id: this.selectedDecision?.decision_id
    };

    this.apiService.createActionPlan(payload).subscribe({
      next: (res: any) => {
        if (res && res.success) {
          this.actionPlans.unshift(res);
        }
        this.closeCreatePlanModal();
        this.loadActionPlans();
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể tạo kế hoạch xử lý. Vui lòng thử lại.';
      }
    });
  }

  updateActionPlanStatus(plan: any, newStatus: string): void {
    this.apiService.updateActionPlanStatus(plan.plan_id, newStatus).subscribe({
      next: (res: any) => {
        plan.status = newStatus;
      },
      error: (err: any) => {
        this.errorMessage = err?.error?.error || 'Không thể cập nhật trạng thái kế hoạch. Vui lòng thử lại.';
      }
    });
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

    let text = '';
    if (queryText.toLowerCase().includes('tại sao') || queryText.toLowerCase().includes('lý do') || queryText.toLowerCase().includes('giải thích')) {
      text = `Phân tích căn cứ 5 chỉ số chính cho sản phẩm ${contextSku}:\n\n` +
        `1. Rủi ro (Risk): ${item.risk.class} (Score: ${riskScore}).\n` +
        `2. Giải thích (Explanation): ${item.explanation?.reason_codes?.join(', ') || 'Chưa có mã lý do được cung cấp.'}\n` +
        `3. Vốn đọng (Capital): Đang gánh ${this.formatCurrency(cap)} tiền giá vốn.\n` +
        `4. Đề xuất (Decision): Khuyên áp dụng phương án '${actionVi}' giảm giá ${discount}% để thu hồi ngay ${this.formatCurrency(rec)}.\n` +
        `5. Mô phỏng: Các giá trị chỉ dựa trên dữ liệu quyết định hiện có.`;
    } else {
      text = `Thông tin phân tích thực tế 5 chỉ số cho mã ${contextSku}:\n\n` +
        `• Ngữ cảnh mã sản phẩm (Context): ${contextSku}\n` +
        `• Mức Rủi ro (Risk): ${item.risk.class} (${riskScore})\n` +
        `• Vốn tồn đọng (Capital): ${this.formatCurrency(cap)}\n` +
        `• Đề xuất xử lý (Decision): ${actionVi} (-${discount}%)\n` +
        `• Vốn dự kiến thu hồi (Recovery): ${this.formatCurrency(rec)}`;
    }

    this.copilotMessages.push({
      sender: 'copilot',
      text: text,
      pillars: ['RỦI RO', 'GIẢI THÍCH', 'VỐN ĐỌNG', 'ĐỀ XUẤT', 'MÔ PHỎNG']
    });
  }
}
