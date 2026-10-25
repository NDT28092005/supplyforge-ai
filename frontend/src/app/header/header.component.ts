import { Component, Input, Output, EventEmitter, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ApiService } from '../api.service';

export interface AppNotification {
  id: number;
  workspace_id: number;
  notification_type: string;
  notification_type_display: string;
  title: string;
  message: string;
  severity: string;
  severity_display: string;
  is_read: boolean;
  related_sku?: string;
  action_url?: string;
  created_at: string;
}

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.css']
})
export class HeaderComponent implements OnInit {
  title = 'SupplyForge AI';

  @Input() user: any = null;
  @Input() stage: string = 'hero';
  @Output() openLogin = new EventEmitter<void>();
  @Output() logout = new EventEmitter<void>();
  @Output() navigateStage = new EventEmitter<string>();
  @Output() demoLogin = new EventEmitter<void>();

  // In-App Notification Center State (NOTI-001 & NOTI-002)
  isNotificationOpen: boolean = false;
  unreadCount: number = 0;
  notifications: AppNotification[] = [];
  filterTab: 'all' | 'unread' | 'critical' = 'all';
  isLoadingNoti: boolean = false;
  isMobileMenuOpen = false;

  constructor(
    public router: Router,
    private apiService: ApiService
  ) {}

  ngOnInit(): void {
    if (this.isAppRoute) this.loadNotifications();
  }

  get isAppRoute(): boolean {
    return this.router.url.startsWith('/app');
  }

  loadNotifications(): void {
    this.isLoadingNoti = true;
    this.apiService.getNotifications(1).subscribe({
      next: (res) => {
        this.isLoadingNoti = false;
        if (res && res.success) {
          this.notifications = res.notifications || [];
          this.unreadCount = res.unread_count || 0;
        }
      },
      error: () => {
        this.isLoadingNoti = false;
      }
    });
  }

  toggleNotificationPanel(): void {
    this.isNotificationOpen = !this.isNotificationOpen;
    if (this.isNotificationOpen) {
      this.loadNotifications();
    }
  }

  get filteredNotifications(): AppNotification[] {
    if (this.filterTab === 'unread') {
      return this.notifications.filter(n => !n.is_read);
    }
    if (this.filterTab === 'critical') {
      return this.notifications.filter(n => n.severity === 'CRITICAL' || n.severity === 'HIGH');
    }
    return this.notifications;
  }

  markRead(item?: AppNotification, event?: MouseEvent): void {
    if (event) event.stopPropagation();

    const notiId = item ? item.id : undefined;
    const markAll = !item;

    this.apiService.markNotificationRead(notiId, markAll, 1).subscribe({
      next: (res) => {
        if (res && res.success) {
          if (markAll) {
            this.notifications.forEach(n => n.is_read = true);
            this.unreadCount = 0;
          } else if (item) {
            item.is_read = true;
            this.unreadCount = Math.max(0, this.unreadCount - 1);
          }
        }
      }
    });
  }

  onNotificationClick(item: AppNotification): void {
    if (!item.is_read) {
      this.markRead(item);
    }
    this.isNotificationOpen = false;

    if (item.action_url) {
      if (item.action_url.includes('?sku=')) {
        const parts = item.action_url.split('?sku=');
        this.router.navigate([parts[0]], { queryParams: { sku: parts[1] } });
      } else {
        this.router.navigate([item.action_url]);
      }
    } else if (item.related_sku) {
      this.router.navigate(['/app/risk'], { queryParams: { sku: item.related_sku } });
    }
  }

  onLoginClick(): void {
    this.closeMobileMenu();
    this.router.navigate(['/auth']);
  }

  onLogoutClick(): void {
    this.logout.emit();
  }

  onDemoLoginClick(): void {
    this.demoLogin.emit();
  }

  onLogoClick(): void {
    this.closeMobileMenu();
    if (this.router.url.startsWith('/app')) {
      this.router.navigate(['/app/dashboard']);
    } else {
      this.router.navigate(['/']);
    }
  }

  toggleMobileMenu(): void {
    this.isMobileMenuOpen = !this.isMobileMenuOpen;
  }

  closeMobileMenu(): void {
    this.isMobileMenuOpen = false;
  }
}
