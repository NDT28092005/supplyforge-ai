import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { of } from 'rxjs';
import { DecisionSupportDashboardComponent } from './decision-support-dashboard.component';
import { ApiService } from '../api.service';

describe('DecisionSupportDashboardComponent', () => {
  let component: DecisionSupportDashboardComponent;
  let fixture: ComponentFixture<DecisionSupportDashboardComponent>;
  let apiService: ApiService;

  const mockDecisions = [
    {
      decision_id: 'DEC-1001',
      sku: 'SKU_001',
      risk: { class: 'CRITICAL', score: 0.95 },
      decision: {
        action: 'DISCOUNT',
        discount_rate: 0.20,
        action_parameters: { discount_rate: 0.20 },
        priority: 'P1',
        priority_score: 0.92,
        priority_rank: 1,
        urgency: 'IMMEDIATE',
        confidence: 'HIGH',
        status: 'RECOMMENDED'
      },
      financial_impact: {
        capital_exposure: 15000000,
        expected_recovery_value: 12000000,
        recovery_rate: 0.80,
        residual_exposure: 3000000
      },
      explanation: { explanation_id: 'EXP-1001', reason_codes: ['CRITICAL_RISK', 'HIGH_CAPITAL_EXPOSURE'] },
      metadata: { dataset_version: 'v1.0', policy_version: 'v1.0', engine_version: 'm6-v1.0' },
      created_at: '2026-08-23T08:00:00Z',
      updated_at: '2026-08-23T08:00:00Z'
    }
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, DecisionSupportDashboardComponent],
      providers: [ApiService]
    }).compileComponents();

    fixture = TestBed.createComponent(DecisionSupportDashboardComponent);
    component = fixture.componentInstance;
    apiService = TestBed.inject(ApiService);
    spyOn(apiService, 'listDecisions').and.returnValue(of(mockDecisions));
    spyOn(apiService, 'getDecisionSummary').and.returnValue(of({
      at_risk_skus: 1,
      high_priority_count: 1,
      needs_review_count: 1,
      capital_exposure: 15000000,
      projected_recovery_value: 12000000,
    }));
    spyOn(apiService, 'getDecisionDataStatus').and.returnValue(of({
      state: 'READY_FOR_REVIEW', counts: { ready_for_review: 1, needs_data: 0, needs_source_check: 0, current_decisions: 1 },
    }));
    spyOn(apiService, 'getDecisionPortfolioQueue').and.returnValue(of({ summary: {}, items: [] }));
    fixture.detectChanges();
  });

  it('should create DecisionSupportDashboardComponent', () => {
    expect(component).toBeTruthy();
  });

  it('should load decisions and compute KPIs on init', () => {
    expect(component.decisions.length).toBe(1);
    expect(component.totalAtRiskSkus).toBe(1);
    expect(component.criticalSkus).toBe(1);
    expect(component.totalCapitalExposure).toBe(15000000);
    expect(component.totalExpectedRecovery).toBe(12000000);
    expect(component.highPriorityCount).toBe(1);
    expect(component.pendingDecisionsCount).toBe(1);
  });

  it('should open the decision drawer without changing decision status', () => {
    spyOn(apiService, 'getDecisionExplanation').and.returnValue(of({ explanation_id: 'EXP-1001' }));
    spyOn(apiService, 'getDecisionHistory').and.returnValue(of({ history: [] }));
    spyOn(apiService, 'updateDecisionStatus').and.returnValue(of({ ...mockDecisions[0], decision: { ...mockDecisions[0].decision, status: 'REVIEWED' } }));

    component.openDecisionDetail(mockDecisions[0] as any);
    expect(component.isDrawerOpen).toBeTrue();
    expect(component.selectedDecision?.sku).toBe('SKU_001');
    expect(apiService.updateDecisionStatus).not.toHaveBeenCalled();
  });

  it('marks a recommendation as reviewed only after the merchant opens evidence', () => {
    spyOn(apiService, 'getDecisionExplanation').and.returnValue(of({ explanation_id: 'EXP-1001' }));
    spyOn(apiService, 'getDecisionHistory').and.returnValue(of({ history: [] }));
    spyOn(apiService, 'updateDecisionStatus').and.returnValue(of({ ...mockDecisions[0], decision: { ...mockDecisions[0].decision, status: 'REVIEWED' } }));

    component.openDecisionDetail(mockDecisions[0] as any);
    component.openEvidence();

    expect(apiService.updateDecisionStatus).toHaveBeenCalledWith(
      'DEC-1001', 'REVIEWED', 'merchant', 'Merchant explicitly opened recommendation evidence.'
    );
  });

  it('uses the P1/P2 operational inbox as the default segment', () => {
    expect(component.activeQueueSegment).toBe('TODAY');
    expect(component.selectedPriority).toBe('P1,P2');
    expect(component.selectedStatus).toBe('GENERATED,RECOMMENDED,NEEDS_REVIEW,REVIEWED');
    expect(component.filteredDecisions.length).toBe(1);
  });

  it('should format currency correctly', () => {
    const formatted = component.formatCurrency(15000000);
    expect(formatted).toContain('15');
  });

  it('should assign correct priority badge classes', () => {
    expect(component.getPriorityBadgeClass('P1')).toBe('priority-p1');
    expect(component.getPriorityBadgeClass('P2')).toBe('priority-p2');
  });

  it('allows a legacy price recommendation to check the current SKU data', () => {
    const legacyDecision = {
      ...mockDecisions[0],
      decision: { ...mockDecisions[0].decision, action: 'DISCOUNT_CLEARANCE', action_parameters: {} },
    } as any;

    expect(component.canSimulateDecision(legacyDecision)).toBeTrue();
    expect(component.getProjectionReadinessLabel(legacyDecision)).toBe('Có thể kiểm tra theo dữ liệu hiện tại');
    expect(component.translateAction(legacyDecision.decision.action)).toBe('Giảm tồn kho ưu tiên');
  });

  it('explains zero observed demand without claiming that price or stock is missing', () => {
    const unavailableDecision = {
      ...mockDecisions[0],
      decision: {
        ...mockDecisions[0].decision,
        action_parameters: {
          projection: { status: 'UNAVAILABLE' },
          input_readiness: { demand_observed: true, demand_positive: false },
        },
      },
    } as any;

    expect(component.canSimulateDecision(unavailableDecision)).toBeFalse();
    expect(component.getSimulationUnavailableMessage(unavailableDecision)).toContain('chưa ghi nhận nhu cầu bán');
    expect(component.translateReasonCode('ZERO_RECENT_DEMAND_NO_PRICE_PROJECTION')).toContain('nhu cầu bán');
  });

  it('explains exactly which decision facts are ready without technical labels', () => {
    const decision = {
      ...mockDecisions[0],
      decision: {
        ...mockDecisions[0].decision,
        action_parameters: {
          commercial_fact_snapshot: {
            state: 'READY', analysis_as_of: '2026-10-29T23:59:59Z', source_scope_fingerprint: 'scope-1',
          },
          input_readiness: { inventory_observed: true, demand_observed: true, financial_inputs_complete: true },
        },
      },
    } as any;

    const contract = component.getDecisionDataContract(decision);

    expect(contract.label).toBe('Đủ dữ liệu để xem xét');
    expect(contract.rows.every(row => row.ready)).toBeTrue();
    expect(contract.message).not.toContain('confidence');
  });

  it('uses the persisted merchant option set without exposing strategy scores', () => {
    const optionDecision = {
      ...mockDecisions[0],
      decision: {
        ...mockDecisions[0].decision,
        options: {
          scope: { source_type: 'CSV', analysis_as_of: '2026-10-29T23:59:59Z' },
          options: [
            {
              option_key: 'KEEP_PRICE', label: 'Giữ giá và theo dõi',
              tradeoff: 'Theo dõi thêm.', status: 'NOT_RECOMMENDED', status_label: 'Chưa phù hợp lúc này',
              is_recommended: false, reasons: ['Rủi ro hiện tại không phù hợp để giữ giá.'],
            },
            {
              option_key: 'CONTROLLED_DISCOUNT', label: 'Giảm giá có kiểm soát',
              tradeoff: 'Kiểm tra biên lợi nhuận.', status: 'READY', status_label: 'Sẵn sàng lập kế hoạch',
              is_recommended: true, reasons: [],
            },
            {
              option_key: 'FAST_CLEARANCE', label: 'Xả hàng nhanh có phê duyệt',
              tradeoff: 'Cần phê duyệt.', status: 'APPROVAL_REQUIRED', status_label: 'Cần phê duyệt',
              is_recommended: false, reasons: [],
            },
          ],
        },
      },
    } as any;

    const options = component.getRecommendationOptions(optionDecision);

    expect(options.length).toBe(3);
    expect(options[0].label).toBe('Giảm giá có kiểm soát');
    expect(options[0].statusLabel).toBe('Sẵn sàng lập kế hoạch');
    expect((options[0] as any).score).toBeUndefined();
    expect(component.getDecisionScopeText(optionDecision)).toContain('CSV');
  });
});
