import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-cashflow-vault',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './cashflow-vault.component.html',
  styleUrls: ['./cashflow-vault.component.css']
})
export class CashflowVaultComponent {
  @Input() data: any = null;
  @Output() proceed = new EventEmitter<void>();
  @Output() recovery = new EventEmitter<void>();
  @Output() commandCenter = new EventEmitter<void>();
  @Output() importNew = new EventEmitter<void>();

  formatVND(value: number): string {
    if (!value) return '0 ₫';
    return Math.round(value).toLocaleString('vi-VN') + ' ₫';
  }

  getPct(part: number, total: number): string {
    if (!total || total <= 0) return '0.0';
    return ((part / total) * 100).toFixed(1);
  }
}
