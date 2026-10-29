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
      description: 'SupplyForge đặt dữ liệu bán hàng trong đúng bối cảnh thời gian để đội ngũ có thể đối chiếu các phiên nạp và đưa ra quyết định dựa trên bằng chứng vận hành.',
      core_values: [
        { title: 'Minh bạch trước khi tự động hóa', desc: 'Hiển thị nguồn dữ liệu, mốc thời gian và cửa sổ quan sát trước khi tạo tín hiệu.' },
        { title: 'Ưu tiên theo vốn và tốc độ bán', desc: 'Đặt SKU chậm luân chuyển cạnh giá trị tồn để xác định nội dung cần rà soát trước.' },
        { title: 'Hệ thống hỗ trợ, đội ngũ phê duyệt', desc: 'Khuyến nghị rút ngắn thời gian phân tích, trong khi quyền phê duyệt thuộc về người vận hành.' }
      ],
      stats: []
    };
  }
}
