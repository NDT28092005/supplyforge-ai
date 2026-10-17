import { Component, OnInit, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

@Component({
  selector: 'app-services-page',
  standalone: true,
  imports: [CommonModule, PageMotionDirective],
  templateUrl: './services-page.component.html',
  styleUrls: ['./services-page.component.css']
})
export class ServicesPageComponent implements OnInit {
  @Output() navigateAction = new EventEmitter<string>();

  services: any[] = [];
  loading = true;

  constructor(
    private apiService: ApiService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.apiService.getServices().subscribe({
      next: (res) => {
        this.services = res.services || [];
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load Services API:', err);
        this.loading = false;
      }
    });
  }

  onAction(target: string): void {
    this.navigateAction.emit(target);
    if (target === 'csv-upload' || target === 'hero') {
      this.router.navigate(['/app/import']);
    } else if (target === 'executive-dashboard') {
      this.router.navigate(['/app/dashboard']);
    } else {
      this.router.navigate(['/']);
    }
  }
}
