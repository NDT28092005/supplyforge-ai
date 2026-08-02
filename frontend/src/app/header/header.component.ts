import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.css']
})
export class HeaderComponent {
  title = 'SupplyForge AI';

  @Input() user: any = null;
  @Input() stage = 'hero';
  @Output() openLogin = new EventEmitter<void>();
  @Output() logout = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();

  onLoginClick(): void {
    this.openLogin.emit();
  }

  onLogoutClick(): void {
    this.logout.emit();
  }

  onLogoClick(): void {
    this.navigateStage.emit('hero');
  }
}


