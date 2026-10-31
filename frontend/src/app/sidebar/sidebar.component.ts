import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './sidebar.component.html',
  styleUrls: ['./sidebar.component.css']
})
export class SidebarComponent {
  @Input() activeStage: string = 'dashboard';
  @Input() collapsed = false;
  @Output() selectStage = new EventEmitter<string>();
  @Output() importNew = new EventEmitter<void>();
  @Output() importIncremental = new EventEmitter<void>();
  @Output() toggleCollapsed = new EventEmitter<void>();

  constructor(public router: Router) {}

  onImportIncrementalClick(): void {
    this.importIncremental.emit();
  }

  onImportNewClick(): void {
    this.importNew.emit();
  }

  onToggleCollapsed(): void {
    this.toggleCollapsed.emit();
  }
}
