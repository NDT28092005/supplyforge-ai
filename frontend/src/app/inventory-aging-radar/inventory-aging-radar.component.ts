import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-inventory-aging-radar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './inventory-aging-radar.component.html',
  styleUrls: ['./inventory-aging-radar.component.css']
})
export class InventoryAgingRadarComponent {
  @Input() data: any = null;
  @Output() triggerCopilot = new EventEmitter<{ item: any }>();

  bucketFilter = 'all';

  setBucketFilter(filter: string): void {
    this.bucketFilter = filter;
  }

  getAllSkusCount(): number {
    if (!this.data) return 0;
    return (this.data.healthySkus || []).length +
      (this.data.watchlistSkus || []).length +
      (this.data.slowMovingSkus || []).length +
      (this.data.deadStockSkus || []).length;
  }

  getFilteredSkus(): any[] {
    if (!this.data) return [];
    let all: any[] = [];
    if (this.bucketFilter === 'all') {
      all = all.concat(this.data.healthySkus || []);
      all = all.concat(this.data.watchlistSkus || []);
      all = all.concat(this.data.slowMovingSkus || []);
      all = all.concat(this.data.deadStockSkus || []);
    } else if (this.bucketFilter === 'DEAD_STOCK') {
      all = this.data.deadStockSkus || [];
    } else if (this.bucketFilter === 'SLOW_MOVING') {
      all = this.data.slowMovingSkus || [];
    }
    return all.sort((x, y) => (y.totalValue || 0) - (x.totalValue || 0));
  }

  formatVND(value: number): string {
    if (!value) return '0 ₫';
    return Math.round(value).toLocaleString('vi-VN') + ' ₫';
  }

  getBarWidth(value: number): number {
    if (!this.data) return 0;
    const total = (this.data.totalHealthyValue || 0) +
      (this.data.totalWatchlistValue || 0) +
      (this.data.totalSlowMovingValue || 0) +
      (this.data.totalDeadStockValue || 0);
    if (!total) return 0;
    return (value / total) * 100;
  }

  getSunkCostRatio(sunk: number, total: number): number {
    if (!total || total <= 0) return 0;
    const ratio = (sunk / total) * 100;
    return Math.min(100, Math.round(ratio * 10) / 10);
  }

  onTriggerCopilot(item: any): void {
    this.triggerCopilot.emit({ item });
  }
}
