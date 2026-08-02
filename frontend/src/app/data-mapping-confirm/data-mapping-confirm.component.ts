import { Component, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { FieldConfig } from '../field-config';

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

  fields: FieldConfig[] = [
    { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc nhãn hiệu của SKU' },
    { key: 'itemSku', label: 'Mã SKU', desc: 'Mã vạch hoặc mã ký tự SKU định danh' },
    { key: 'price', label: 'Giá bán', desc: 'Giá niêm yết bán lẻ cho người tiêu dùng' },
    { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng' },
    { key: 'stock', label: 'Tồn kho', desc: 'Số lượng đơn vị còn tồn kho' },
    { key: 'orderDate', label: 'Ngày ghi nhận', desc: 'Ngày nhập kho hoặc ngày giao dịch gần nhất' }
  ];

  finalMapping: Record<string, string> = {
    productName: '',
    itemSku: '',
    price: '',
    cost: '',
    stock: '',
    orderDate: ''
  };

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

      // 1. Map index-based Gemini suggestions
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

      // 2. Map string-key suggestions or heuristic fallbacks
      const findHeader = (regex: RegExp, fallbackIdx: number) => {
        const matched = this.headers.find((h) => regex.test(h));
        return matched || (fallbackIdx < this.headers.length ? this.headers[fallbackIdx] : this.headers[0]);
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

  getSampleValue(fieldKey: string): string | null {
    if (!this.sampleData || !this.headers) return null;
    const header = this.finalMapping[fieldKey];
    if (!header) return null;
    const idx = this.headers.indexOf(header);
    return idx >= 0 && idx < this.sampleData.length ? this.sampleData[idx] : null;
  }

  confirm(): void {
    this.confirmMapping.emit({ finalMapping: this.finalMapping });
  }
}
