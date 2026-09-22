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

  it('should open decision detail drawer and transition status to REVIEWED', () => {
    spyOn(apiService, 'getDecisionExplanation').and.returnValue(of({ explanation_id: 'EXP-1001' }));
    spyOn(apiService, 'getDecisionHistory').and.returnValue(of({ history: [] }));
    spyOn(apiService, 'updateDecisionStatus').and.returnValue(of({ ...mockDecisions[0], decision: { ...mockDecisions[0].decision, status: 'REVIEWED' } }));

    component.openDecisionDetail(mockDecisions[0] as any);
    expect(component.isDrawerOpen).toBeTrue();
    expect(component.selectedDecision?.sku).toBe('SKU_001');
    expect(apiService.updateDecisionStatus).toHaveBeenCalledWith('DEC-1001', 'REVIEWED', 'merchant', jasmine.any(String));
  });

  it('should format currency correctly', () => {
    const formatted = component.formatCurrency(15000000);
    expect(formatted).toContain('15');
  });

  it('should assign correct priority badge classes', () => {
    expect(component.getPriorityBadgeClass('P1')).toBe('priority-p1');
    expect(component.getPriorityBadgeClass('P2')).toBe('priority-p2');
  });
});
