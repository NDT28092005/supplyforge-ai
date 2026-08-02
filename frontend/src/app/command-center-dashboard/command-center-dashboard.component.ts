import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-command-center-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './command-center-dashboard.component.html',
  styleUrls: ['./command-center-dashboard.component.css']
})
export class CommandCenterDashboardComponent {
  @Input() portfolioData: any = null;
  @Input() loading = false;
  @Output() back = new EventEmitter<void>();
  @Output() selectCluster = new EventEmitter<{ cluster: any }>();

  onSelectCluster(cluster: any): void {
    this.selectCluster.emit({ cluster });
  }

  formatVND(value: number): string {
    if (!value) return '0 ₫';
    return Math.round(value).toLocaleString('vi-VN') + ' ₫';
  }
}
