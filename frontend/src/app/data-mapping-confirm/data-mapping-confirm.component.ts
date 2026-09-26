import { Component, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { FieldConfig } from '../field-config';

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
export class DataMappingConfirmComponent implements OnInit, OnChanges {
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

  ngOnInit(): void {
    this.detectMapping();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['headers'] || changes['aiSuggestions']) {
      this.detectMapping();
    }
  }

  detectMapping(): void {
    if (this.headers && this.headers.length > 0) {
      const suggestions = this.aiSuggestions || {};

      if (suggestions.sku_column_index !== undefined && suggestions.sku_column_index !== null && this.headers[suggestions.sku_column_index]) {
        this.finalMapping['itemSku'] = this.headers[suggestions.sku_column_index];
      }
      if (suggestions.quantity_column_index !== undefined && suggestions.quantity_column_index !== null && this.headers[suggestions.quantity_column_index]) {
        this.finalMapping['stock'] = this.headers[suggestions.quantity_column_index];
      }
      if (suggestions.selling_price_column_index !== undefined && suggestions.selling_price_column_index !== null && this.headers[suggestions.selling_price_column_index]) {
        this.finalMapping['price'] = this.headers[suggestions.selling_price_column_index];
      }
      if (suggestions.cost_price_column_index !== undefined && suggestions.cost_price_column_index !== null && this.headers[suggestions.cost_price_column_index]) {
        this.finalMapping['cost'] = this.headers[suggestions.cost_price_column_index];
      }
      if (suggestions.record_date_column_index !== undefined && suggestions.record_date_column_index !== null && this.headers[suggestions.record_date_column_index]) {
        this.finalMapping['orderDate'] = this.headers[suggestions.record_date_column_index];
      }

      const findHeader = (regex: RegExp, fallbackIdx: number) => {
        const matched = this.headers.find((h) => regex.test(h));
        return matched || (fallbackIdx < this.headers.length ? this.headers[fallbackIdx] : '');
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
        this.finalMapping['stock'] = suggestions.stock || findHeader(/stock|quantity|số lượng|sl|tồn/i, 1);
      }
      if (!this.finalMapping['orderDate']) {
        this.finalMapping['orderDate'] = suggestions.date || findHeader(/date|ngày/i, 4);
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
  }
}
