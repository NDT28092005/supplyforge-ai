import { Component, Input, Output, EventEmitter, OnInit, OnDestroy, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { FieldConfig } from '../field-config';
import { ApiService } from '../api.service';
import { IngestionStateService } from '../core/state/ingestion-state.service';

export interface ExtendedFieldConfig extends FieldConfig {
  required?: boolean;
}

@Component({
  selector: 'app-data-mapping-confirm',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './data-mapping-confirm.component.html',
  styleUrls: ['./data-mapping-confirm.component.css']
})
export class DataMappingConfirmComponent implements OnInit, OnDestroy, OnChanges {
  @Input() headers: string[] = [];
  @Input() sampleData: any[] = [];
  @Input() aiSuggestions: any = null;
  @Output() confirmMapping = new EventEmitter<{ finalMapping: Record<string, string> }>();

  fields: ExtendedFieldConfig[] = [
    { key: 'itemSku', label: 'Mã SKU', desc: 'Mã định danh duy nhất của sản phẩm/SKU', required: true },
    { key: 'orderDate', label: 'Ngày giao dịch', desc: 'Ngày bán hàng hoặc thời gian phát sinh đơn hàng', required: true },
    { key: 'stock', label: 'Số lượng', desc: 'Số lượng sản phẩm bán ra hoặc tồn kho', required: true },
    { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc mô tả đầy đủ của sản phẩm', required: false },
    { key: 'price', label: 'Giá bán', desc: 'Giá bán niêm yết cho người tiêu dùng', required: false },
    { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng', required: false },
  ];

  finalMapping: Record<string, string> = {
    productName: '',
    itemSku: '',
    price: '',
    cost: '',
    stock: '',
    orderDate: ''
  };

  userOverriddenKeys: Set<string> = new Set();
  isProcessing = false;
  private stateSub?: Subscription;

  constructor(
    private apiService: ApiService,
    private ingestionState: IngestionStateService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.stateSub = this.ingestionState.stateObservable.subscribe(state => {
      if (state.mappingData && (!this.headers || this.headers.length === 0)) {
        this.headers = state.mappingData.headers || [];
        this.sampleData = state.mappingData.sampleData || [];
        this.aiSuggestions = state.mappingData.aiSuggestions || null;
        this.detectMapping();
      }
    });

    const state = this.ingestionState.state;
    const mappingData = state.mappingData;
    if (mappingData && mappingData.headers && mappingData.headers.length > 0) {
      this.headers = mappingData.headers;
      this.sampleData = mappingData.sampleData || [];
      this.aiSuggestions = mappingData.aiSuggestions || null;
      this.detectMapping();
    } else if (state.activeSessionId) {
      this.recoverSessionFromBackend(state.activeSessionId);
    }
  }

  recoverSessionFromBackend(sessionId: string): void {
    if (!sessionId) return;
    this.apiService.getIngestionSession(sessionId).subscribe({
      next: (res: any) => {
        const profile = res?.profile || {};
        if (profile.headers && profile.headers.length > 0) {
          const recoveredMapping = {
            headers: profile.headers,
            sampleData: profile.previewRows ? profile.previewRows[0] : null,
            aiSuggestions: {
              sku_column_index: profile.headers.indexOf(profile.skuColumnDetected),
              record_date_column_index: profile.headers.indexOf(profile.dateColumnDetected),
              confidence: 'High (Session Recovered)'
            }
          };
          this.headers = profile.headers;
          this.sampleData = recoveredMapping.sampleData;
          this.aiSuggestions = recoveredMapping.aiSuggestions;
          this.ingestionState.setMappingData(recoveredMapping);
          this.detectMapping();
        }
      },
      error: (err) => console.warn('[DataMappingConfirm] Could not recover session:', err)
    });
  }

  ngOnDestroy(): void {
    if (this.stateSub) {
      this.stateSub.unsubscribe();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['headers'] || changes['aiSuggestions']) {
      this.detectMapping();
    }
  }

  detectMapping(): void {
    if (this.headers && this.headers.length > 0) {
      const suggestions = this.aiSuggestions || {};

      if (suggestions.sku_column_index !== undefined && suggestions.sku_column_index !== null && suggestions.sku_column_index >= 0 && this.headers[suggestions.sku_column_index]) {
        this.finalMapping['itemSku'] = this.headers[suggestions.sku_column_index];
      }
      if (suggestions.quantity_column_index !== undefined && suggestions.quantity_column_index !== null && suggestions.quantity_column_index >= 0 && this.headers[suggestions.quantity_column_index]) {
        this.finalMapping['stock'] = this.headers[suggestions.quantity_column_index];
      }
      if (suggestions.selling_price_column_index !== undefined && suggestions.selling_price_column_index !== null && suggestions.selling_price_column_index >= 0 && this.headers[suggestions.selling_price_column_index]) {
        this.finalMapping['price'] = this.headers[suggestions.selling_price_column_index];
      }
      if (suggestions.cost_price_column_index !== undefined && suggestions.cost_price_column_index !== null && suggestions.cost_price_column_index >= 0 && this.headers[suggestions.cost_price_column_index]) {
        this.finalMapping['cost'] = this.headers[suggestions.cost_price_column_index];
      }
      if (suggestions.record_date_column_index !== undefined && suggestions.record_date_column_index !== null && suggestions.record_date_column_index >= 0 && this.headers[suggestions.record_date_column_index]) {
        this.finalMapping['orderDate'] = this.headers[suggestions.record_date_column_index];
      }

      const findHeader = (regex: RegExp) => {
        const matched = this.headers.find((h) => regex.test(h));
        return matched || '';
      };

      if (!this.finalMapping['productName']) {
        this.finalMapping['productName'] = suggestions.product_name || findHeader(/product_name|item_name|product|name|tên|sản phẩm/i);
      }
      if (!this.finalMapping['itemSku']) {
        this.finalMapping['itemSku'] = suggestions.item_sku || findHeader(/^sku$|item_sku|mã_sku|mã_sp|sku|mã|code/i);
      }
      if (!this.finalMapping['price']) {
        this.finalMapping['price'] = suggestions.price || findHeader(/unit_price|selling_price|price|giá_bán|giá/i);
      }
      if (!this.finalMapping['cost']) {
        this.finalMapping['cost'] = suggestions.cost || findHeader(/cost_price|cost|giá_vốn|vốn/i);
      }
      if (!this.finalMapping['stock']) {
        this.finalMapping['stock'] = suggestions.stock || findHeader(/stock_on_hand|quantity|stock|số_lượng|tồn/i);
      }
      if (!this.finalMapping['orderDate']) {
        this.finalMapping['orderDate'] = suggestions.date || findHeader(/order_date|record_date|order_time|date|ngày/i);
      }
    }
  }

  onFieldChange(fieldKey: string): void {
    this.userOverriddenKeys.add(fieldKey);
  }

  getSampleValue(fieldKey: string): string | null {
    if (!this.sampleData || !this.headers) return null;
    const header = this.finalMapping[fieldKey];
    if (!header) return null;
    const idx = this.headers.indexOf(header);
    return idx >= 0 && idx < this.sampleData.length ? this.sampleData[idx] : null;
  }

  getMissingRequiredFields(): string[] {
    const missing: string[] = [];
    if (!this.finalMapping['itemSku']) missing.push('Mã SKU');
    if (!this.finalMapping['orderDate']) missing.push('Ngày giao dịch');
    if (!this.finalMapping['stock']) missing.push('Số lượng');
    return missing;
  }

  isBlocked(): boolean {
    return this.getMissingRequiredFields().length > 0;
  }

  getMethodBadge(fieldKey: string): { label: string; class: string } {
    if (this.userOverriddenKeys.has(fieldKey)) {
      return { label: 'Tự chọn', class: 'bg-purple-50 text-purple-700 border-purple-200' };
    }
    const val = this.finalMapping[fieldKey];
    if (!val) return { label: 'Chưa chọn', class: 'bg-rose-50 text-rose-700 border-rose-200' };

    return { label: 'Khớp tự động', class: 'bg-emerald-50 text-emerald-700 border-emerald-200' };
  }

  confirm(): void {
    if (this.isBlocked()) return;
    this.confirmMapping.emit({ finalMapping: this.finalMapping });

    const state = this.ingestionState.state;
    const activeSessionId = state.activeSessionId;
    const targetFile = state.uploadFile;

    if (this.router.url === '/app/import/mapping') {
      this.isProcessing = true;
      this.ingestionState.setProcessingBatch(true);

      const onComplete = (profileRes: any, processRes?: any) => {
        this.isProcessing = false;
        this.ingestionState.setProcessingBatch(false);
        const baseProfile = profileRes?.profile || profileRes || {};
        const proc = processRes || {};
        const profileData = {
          ...baseProfile,
          ...proc,
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
        this.ingestionState.setProfileData(profileData);
        this.router.navigate(['/app/import/profile', activeSessionId || 'default']);
      };

      if (activeSessionId) {
        const profile$ = this.apiService.triggerDatasetProfiling(activeSessionId, this.finalMapping).pipe(
          catchError(err => {
            console.warn('Dataset profiling error:', err);
            return of(null);
          })
        );

        const process$ = targetFile
          ? this.apiService.processFile(targetFile, this.finalMapping, 'user_default_001', 'INITIAL').pipe(
              catchError(err => {
                console.warn('Process file error:', err);
                return of(null);
              })
            )
          : of(null);

        forkJoin([profile$, process$]).subscribe({
          next: ([profileRes, processRes]) => onComplete(profileRes, processRes),
          error: () => {
            this.isProcessing = false;
            this.ingestionState.setProcessingBatch(false);
            this.router.navigate(['/app/dashboard']);
          }
        });
      } else if (targetFile) {
        this.apiService.processFile(targetFile, this.finalMapping, 'user_default_001', 'INITIAL').subscribe({
          next: (processRes) => onComplete(null, processRes),
          error: () => {
            this.isProcessing = false;
            this.ingestionState.setProcessingBatch(false);
            this.router.navigate(['/app/dashboard']);
          }
        });
      } else {
        this.isProcessing = false;
        this.ingestionState.setProcessingBatch(false);
        this.router.navigate(['/app/dashboard']);
      }
    }
  }
}
