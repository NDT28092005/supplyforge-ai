import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './sidebar.component.html',
  styleUrls: ['./sidebar.component.css']
})
export class SidebarComponent {
  @Input() activeStage: string = 'dashboard';
  @Output() selectStage = new EventEmitter<string>();
  @Output() importNew = new EventEmitter<void>();

  navigateTo(stage: string): void {
    this.selectStage.emit(stage);
  }

  onImportNewClick(): void {
    this.importNew.emit();
  }
}
