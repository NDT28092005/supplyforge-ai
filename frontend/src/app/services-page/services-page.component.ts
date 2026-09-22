import { Component, OnInit, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../api.service';

@Component({
  selector: 'app-services-page',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './services-page.component.html',
  styleUrls: ['./services-page.component.css']
})
export class ServicesPageComponent implements OnInit {
  @Output() navigateAction = new EventEmitter<string>();

  services: any[] = [];
  loading = true;

  constructor(private apiService: ApiService) {}

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
  }
}
