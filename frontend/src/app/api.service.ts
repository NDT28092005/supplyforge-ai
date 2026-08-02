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
}
