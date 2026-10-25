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
    this.data = this.defaultData();
    this.apiService.getAboutUs().subscribe({
      next: (res) => {
        this.data = {
          ...this.data,
          ...res,
          core_values: res?.core_values?.length ? res.core_values : this.data.core_values,
          stats: res?.stats?.length ? res.stats : this.data.stats
        };
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
    } else if (target === 'services') {
      this.router.navigate(['/services']);
    } else if (target === 'executive-dashboard') {
      this.router.navigate(['/app/dashboard']);
    } else {
      this.router.navigate(['/']);
    }
  }

  private defaultData(): any {
    return {
      title: 'SupplyForge AI',
      description: 'SupplyForge đặt dữ liệu bán hàng vào đúng mốc thời gian để merchant không phải dò từng file, quên lần nhập trước hoặc quyết định theo cảm giác.',
      core_values: [
        { title: 'Minh bạch trước khi tự động hóa', desc: 'Luôn hiển thị nguồn dữ liệu, mốc thời gian và cửa sổ quan sát trước khi tạo tín hiệu.' },
        { title: 'Ưu tiên theo vốn và sức bán', desc: 'Đặt SKU chậm cạnh giá trị tồn để đội ngũ biết việc nào đáng được xem trước.' },
        { title: 'AI hỗ trợ, merchant quyết định', desc: 'Khuyến nghị giúp rút ngắn thời gian phân tích, nhưng quyền duyệt vẫn ở người vận hành.' }
      ],
      stats: []
    };
  }
}
