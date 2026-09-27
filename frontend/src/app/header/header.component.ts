import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.css']
})
export class HeaderComponent {
  title = 'SupplyForge AI';

  @Input() user: any = null;
  @Input() stage: string = 'hero';
  @Output() openLogin = new EventEmitter<void>();
  @Output() logout = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();
  @Output() demoLogin = new EventEmitter<void>();

  constructor(public router: Router) {}

  onLoginClick(): void {
    this.openLogin.emit();
  }

  onLogoutClick(): void {
    this.logout.emit();
  }

  onDemoLoginClick(): void {
    this.demoLogin.emit();
  }

  onLogoClick(): void {
    if (this.router.url.startsWith('/app')) {
      this.router.navigate(['/app/dashboard']);
    } else {
      this.router.navigate(['/']);
    }
  }
}
