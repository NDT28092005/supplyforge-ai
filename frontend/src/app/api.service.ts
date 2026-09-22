import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private apiUrl = 'http://localhost:8080';

  constructor(private http: HttpClient) {}

  setApiUrl(url: string): void {
    if (url) {
      this.apiUrl = url;
    }
  }

  getApiUrl(): string {
    return this.apiUrl;
  }

  ping(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ping`);
  }

  checkData(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/data/check`);
  }

  // ── Content REST API Methods ──────────────────────────────────────
  getAboutUs(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/about_us`);
  }

  getServices(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/services`);
  }

  getBlogPosts(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/blog`);
  }

  getBlogDetail(slug: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/blog/${slug}`);
  }

  syncProducts(file: File, userId = 'user_default_001'): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('userId', userId);
    return this.http.post(`${this.apiUrl}/api/v1/sync/products`, formData);
  }

  syncOrders(file: File, userId = 'user_default_001'): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('userId', userId);
    return this.http.post(`${this.apiUrl}/api/v1/sync/orders`, formData);
  }

  analyzeFile(file: File): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post(`${this.apiUrl}/api/v1/import/analyze`, formData);
  }

  // ── Module 01 Data Ingestion ─────────────────────────────────────
  uploadCsvV2(file: File, workspaceId: number = 1, sessionType: string = 'INITIAL'): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspaceId', workspaceId.toString());
    formData.append('sessionType', sessionType);
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/upload`, formData);
  }

  uploadFile(file: File, workspaceId: string): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('workspaceId', workspaceId);
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/upload`, formData);
  }

  getIngestionSession(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}`);
  }

  listIngestionSessions(workspaceId: number = 1): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions?workspaceId=${workspaceId}`);
  }

  getIngestionSessions(workspaceId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions?workspaceId=${workspaceId}`);
  }

  // ── Module 01 Task 02 Dataset Profiling ─────────────────────────────
  triggerDatasetProfiling(sessionId: string, columnMapping: any = {}): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/profile`, { columnMapping });
  }

  getDatasetProfile(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/profile/detail`);
  }

  getSkuProfiles(sessionId: string, page: number = 1, search: string = ''): Observable<any> {
    let params = new HttpParams().set('page', page.toString());
    if (search) params = params.set('search', search);
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-profiles`, { params });
  }

  processFile(file: File, mappingRule: any, userId = 'user_default_001'): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('mappingRule', JSON.stringify(mappingRule));
    formData.append('userId', userId);
    return this.http.post(`${this.apiUrl}/api/v1/import/process`, formData);
  }

  clearData(userId = 'user_default_001'): Observable<any> {
    return this.http.delete(`${this.apiUrl}/api/v1/import/clear?userId=${userId}`);
  }

  refreshDashboard(workspaceId: number, userId = 'user_default_001'): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/dead-stock/refresh?userId=${userId}`, {});
  }

  getDashboard(workspaceId: number, userId = 'user_default_001'): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/dead-stock?userId=${userId}`);
  }

  getAging(workspaceId: number, userId = 'user_default_001'): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/aging?userId=${userId}`);
  }

  getPortfolioCommand(workspaceId: number, userId = 'user_default_001'): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/portfolio/command?userId=${userId}`);
  }

  getFinancialAnalysis(workspaceId: number, userId = 'user_default_001', discount = 0.35, accounting = 'FIFO', skuId?: string, skuName?: string): Observable<any> {
    let params = new HttpParams()
      .set('userId', userId)
      .set('discount', discount.toString())
      .set('accounting', accounting);
    if (skuId) params = params.set('skuId', skuId);
    if (skuName) params = params.set('skuName', skuName);

    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/portfolio/financial-analysis`, { params });
  }

  getSkuXai(workspaceId: number, skuId: string, userId = 'user_default_001'): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/sku/${skuId}/xai?userId=${userId}`);
  }

  getCandidates(workspaceId: number, userId = 'user_default_001'): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/sku-merge/candidates?userId=${userId}`);
  }

  mergeProducts(workspaceId: number, parentId: string, childId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/sku-merge/merge`, {
      parentSkuId: parentId,
      childSkuId: childId
    });
  }

  undoMerge(workspaceId: number, parentId: string, childId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/sku-merge/undo`, {
      parentSkuId: parentId,
      childSkuId: childId
    });
  }

  ignorePair(workspaceId: number, skuAId: string, skuBId: string, userId = 'user_default_001'): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/workspaces/${workspaceId}/sku-merge/ignore`, {
      skuAId,
      skuBId,
      userId
    });
  }

  completeGooglePhone(tempUserId: string, phone: string, picture = ''): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/auth/google/complete-phone`, {
      tempUserId,
      phone,
      picture
    });
  }

  // ── Module 01 Task 03 Column Mapping API ─────────────────────────────
  triggerColumnMapping(sessionId: string, userOverrides?: Record<string, string>): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/map-columns`, {
      userOverrides: userOverrides || {}
    });
  }

  submitMappingOverride(sessionId: string, sourceColumn: string, canonicalField: string | null): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/mapping-override`, {
      sourceColumn,
      canonicalField
    });
  }

  // ── Module 01 Task 04 Canonical Schema Validation API ─────────────
  validateCanonicalSchema(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/validate-schema`, {});
  }

  getSchemaValidationReport(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/schema-validation`);
  }

  // ── Module 01 DAT-05 Data Quality Validation API ───────────────
  validateDataQuality(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/quality-validation`, {});
  }

  getSkuQualityProfiles(sessionId: string, page: number = 1, pageSize: number = 5): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-quality-profiles?page=${page}&pageSize=${pageSize}`);
  }

  // ── Module 01 DAT-06 SKU Normalization API ───────────────────────
  normalizeSkus(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/normalize-skus`, {});
  }

  getSkuCandidates(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-candidates`);
  }

  mergeSkuPair(sessionId: string, canonicalSkuId: string, childSkuId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-merge`, {
      canonicalSkuId,
      childSkuId
    });
  }

  undoSkuMerge(sessionId: string, canonicalSkuId: string, childSkuId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-undo-merge`, {
      canonicalSkuId,
      childSkuId
    });
  }

  getSkuMasterCatalog(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-master`);
  }

  // ── Module 01 DAT-07 Incremental Upload & Dataset Merge API ───────
  executeIncrementalMerge(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/incremental-merge`, {});
  }

  getMergeReport(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/merge-report`);
  }

  getDatasetVersions(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/dataset-versions`);
  }

  // ── Module 01 DAT-08 Data Freshness Tracking API ──────────────────
  trackDataFreshness(sessionId: string, customThresholds?: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/freshness-tracking`, {
      customThresholds: customThresholds || null
    });
  }

  getFreshnessStatus(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/freshness-status`);
  }

  getSkuFreshnessReport(sessionId: string, page: number = 1, pageSize: number = 5): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/sku-freshness?page=${page}&pageSize=${pageSize}`);
  }

  // ── Module 01 DAT-09 Ingestion History & Audit Trail API ─────────
  recordIngestionHistory(sessionId: string, payload: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/record-history`, payload);
  }

  getIngestionHistoryDetail(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/history`);
  }

  getAllIngestionHistory(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/history-list`);
  }

  // ── Module 01 DAT-10 Data Quality Report UI & Readiness Guard API ──
  generateConsolidatedQualityReport(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/generate-quality-report`, {});
  }

  getConsolidatedQualityDashboard(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/quality-dashboard`);
  }

  getAffectedRecordsSample(sessionId: string, issueId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/affected-records?issueId=${issueId}`);
  }

  // ── Module 01 DAT-11 Data Readiness Gate & Downstream Guard API ──
  evaluateDataReadinessGate(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/evaluate-readiness`, {});
  }

  getDataReadinessGateStatus(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/ingestion/sessions/${sessionId}/readiness-gate-status`);
  }

  // ── Module 02 Analytics M2-01 Slow-Moving Risk Feature Engineering API ──
  computeSlowMovingFeatures(sessionId: string, decisionDate?: string): Observable<any> {
    const payload = decisionDate ? { decisionDate } : {};
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/compute-features`, payload);
  }

  getSlowMovingFeatures(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/features`);
  }

  getFeatureQualityReport(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-quality`);
  }

  // ── Module 02 Analytics M2-02 Demand Pattern Classification API ──
  classifyDemandPatterns(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/classify-demand-patterns`, {});
  }

  getDemandPatterns(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/demand-patterns`);
  }

  getDemandPatternSummary(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/demand-pattern-summary`);
  }

  // ── Module 02 Analytics M2-03 Slow-Moving Risk Feature Assembly API ──
  assembleRiskFeatures(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/assemble-risk-features`, {});
  }

  getRiskFeatures(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-features`);
  }

  getRiskFeatureRegistry(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-registry`);
  }

  // ── Module 02 Analytics M2-04 Slow-Moving Risk Feature Engineering API ──
  buildRiskFeatureMatrix(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/build-risk-feature-matrix`, {});
  }

  getRiskFeatureMatrix(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-feature-matrix`);
  }

  getFeatureDictionary(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-dictionary`);
  }

  getFeatureCorrelation(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-correlation`);
  }

  // ── Module 02 Analytics M2-05 Slow-Moving Risk Feature Scoring API ──
  computeRiskScores(sessionId: string, customThresholds?: any): Observable<any> {
    const payload = customThresholds ? { customThresholds } : {};
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/compute-risk-scores`, payload);
  }

  getRiskScores(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-scores`);
  }

  getRiskScoringConfig(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-scoring-config`);
  }

  // ── Module 02 Analytics M2-06 Slow-Moving Risk Classification API ──
  classifySlowMovingRisk(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/classify-slow-moving-risk`, {});
  }

  getRiskClassifications(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-classifications`);
  }

  getRiskClassificationSummary(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-classification-summary`);
  }

  // ── Module 02 Analytics M2-07 Slow-Moving Risk Ranking & Prioritization API ──
  prioritizeSlowMovingRisk(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/prioritize-slow-moving-risk`, {});
  }

  getRiskPrioritizedQueue(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-prioritized-queue`);
  }

  getRiskPrioritizationSummary(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-prioritization-summary`);
  }

  // ── Module 02 Analytics M2-08 Feature Validation & Readiness Gate API ──
  validateFeatureMatrix(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/validate-feature-matrix`, {});
  }

  getFeatureReadinessCertificate(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-readiness-certificate`);
  }

  getFrozenFeatureMatrix(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/frozen-feature-matrix`);
  }

  // ── Module 02 Analytics M2-09 Feature Snapshot & Downstream Handoff API ──
  createFeatureSnapshot(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/create-feature-snapshot`, {});
  }

  getFeatureSnapshotMetadata(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/feature-snapshot-metadata`);
  }

  getRiskModelContract(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-model-contract`);
  }

  // ── Module 02 Analytics M2-10 Risk Dashboard UI & Module 02 Acceptance API ──
  runModule02Acceptance(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/run-module02-acceptance`, {});
  }

  getRiskSummary(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-summary`);
  }

  getRiskProducts(sessionId: string, params: any = {}): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-products`, { params });
  }

  getRiskProductDetail(sessionId: string, sku: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/analytics/sessions/${sessionId}/risk-products/${sku}`);
  }

  // ── Module 03 Analytics M3-07 & M3-08 APIs ──
  getM3RiskSummary(sessionId?: string): Observable<any> {
    const params = sessionId ? { session_id: sessionId } : {};
    return this.http.get(`${this.apiUrl}/api/v1/risk/summary`, { params });
  }

  getM3RiskAssessments(params: any = {}): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/risk/assessments/list`, { params });
  }

  getM3RiskAssessmentDetail(id: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/risk/assessments/${id}`);
  }

  getM3SkuRisk(skuId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/risk/skus/${skuId}`);
  }

  runM3RiskAssessmentAssembly(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/risk/assessments`, { session_id: sessionId });
  }

  runM3RiskMonitoring(sessionId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/risk/monitoring/run`, { session_id: sessionId });
  }

  getM3MonitoringRuns(sessionId?: string): Observable<any> {
    const params = sessionId ? { session_id: sessionId } : {};
    return this.http.get(`${this.apiUrl}/api/v1/risk/monitoring`, { params });
  }

  getM3MonitoringRunDetail(runId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/risk/monitoring/${runId}`);
  }

  getM3ActiveMonitoringAlerts(sessionId?: string): Observable<any> {
    const params = sessionId ? { session_id: sessionId } : {};
    return this.http.get(`${this.apiUrl}/api/v1/risk/monitoring/alerts`, { params });
  }

  // ── Module 04 Explainability APIs (M4-08 & M4-09) ──
  getSkuExplanation(skuId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/explanations/${skuId}`);
  }

  getSkuExplanationHistory(skuId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/explanations/${skuId}/history`);
  }

  getBatchExplanations(skus: string[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/explanations/batch`, { skus });
  }

  getGlobalExplanation(): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/explanations/global`);
  }

  listExplanations(params: any = {}): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/explanations`, { params });
  }

  // ── Module 05 Capital Exposure & Aging APIs (M5-09 & M5-10) ──
  createCapitalExposureAnalysis(payload: any = {}): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/capital-exposure/analyses`, payload);
  }

  getCapitalExposureAnalysis(analysisId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}`);
  }

  getCapitalExposureSummary(analysisId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}/summary`);
  }

  listCapitalExposureItems(analysisId: string, params: any = {}): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}/items`, { params });
  }

  getCapitalExposureSkuDetail(analysisId: string, skuId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}/items/${skuId}`);
  }

  getCapitalExposureAgingDistribution(analysisId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}/aging`);
  }

  getCapitalExposureRiskDistribution(analysisId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/capital-exposure/analyses/${analysisId}/risk-distribution`);
  }

  // ── Module 06 Decision Support & Capital Recovery APIs (M6-10 & M6-11) ──
  listDecisions(filters: any = {}): Observable<any> {
    let params = new HttpParams();
    Object.keys(filters).forEach(key => {
      if (filters[key] !== null && filters[key] !== undefined && filters[key] !== '' && filters[key] !== 'ALL') {
        params = params.set(key, filters[key]);
      }
    });
    return this.http.get(`${this.apiUrl}/api/v1/decisions/`, { params });
  }

  getDecisionDetail(decisionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/decisions/${decisionId}/`);
  }

  updateDecisionStatus(decisionId: string, status: string, actor: string = 'merchant', notes: string = ''): Observable<any> {
    return this.http.patch(`${this.apiUrl}/api/v1/decisions/${decisionId}/status/`, { status, actor, notes });
  }

  getDecisionHistory(decisionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/decisions/${decisionId}/history/`);
  }

  getDecisionExplanation(decisionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/api/v1/decisions/${decisionId}/explanation/`);
  }

  persistDecision(recommendation: any, explanation: any = null, datasetVersion: string = 'v1.0'): Observable<any> {
    return this.http.post(`${this.apiUrl}/api/v1/decisions/`, { recommendation, explanation, dataset_version: datasetVersion });
  }
}



