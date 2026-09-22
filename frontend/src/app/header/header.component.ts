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
  @Input() stage: string = 'hero';
  @Output() openLogin = new EventEmitter<void>();
  @Output() logout = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();
  @Output() demoLogin = new EventEmitter<void>();

  @Output() openAbout = new EventEmitter<void>();
  @Output() openServices = new EventEmitter<void>();
  @Output() openBlog = new EventEmitter<void>();

  onLoginClick(): void {
    this.openLogin.emit();
  }

  onLogoutClick(): void {
    this.logout.emit();
  }

  onDemoLoginClick(): void {
    this.demoLogin.emit();
  }

  onAboutClick(): void {
    this.openAbout.emit();
  }

  onServicesClick(): void {
    this.openServices.emit();
  }

  onBlogClick(): void {
    this.openBlog.emit();
  }

  onLogoClick(): void {
    if (this.stage === 'hero') {
      this.navigateStage.emit('hero');
    } else {
      this.navigateStage.emit('executive-dashboard');
    }
  }

  onNavigate(targetStage: string): void {
    this.navigateStage.emit(targetStage);
  }
}
