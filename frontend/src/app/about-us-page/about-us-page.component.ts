import { Component, OnInit, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

@Component({
  selector: 'app-about-us-page',
  standalone: true,
  imports: [CommonModule, PageMotionDirective],
  templateUrl: './about-us-page.component.html',
  styleUrls: ['./about-us-page.component.css']
})
export class AboutUsPageComponent implements OnInit {
  @Output() navigateAction = new EventEmitter<string>();

  data: any = null;
  loading = true;

  constructor(
    private apiService: ApiService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.apiService.getAboutUs().subscribe({
      next: (res) => {
        this.data = res;
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load About Us API:', err);
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
