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
    this.services = this.defaultServices();
    this.apiService.getServices().subscribe({
      next: (res) => {
        if (res?.services?.length) this.services = res.services;
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

  private defaultServices(): any[] {
    return [
      {
        title: 'Xác thực và chuẩn hóa dữ liệu',
        desc: 'Đối chiếu trường dữ liệu, ngày bán và bản ghi trùng trước khi dữ liệu được sử dụng để phân tích.',
        result: 'Dữ liệu đầu vào đáng tin cậy'
      },
      {
        title: 'Nhận diện rủi ro chậm luân chuyển',
        desc: 'Đánh giá tốc độ bán theo nhiều cửa sổ thời gian cùng tồn kho và giá trị vốn liên quan.',
        result: 'Xác định SKU cần ưu tiên'
      },
      {
        title: 'Đánh giá mức độ sử dụng vốn',
        desc: 'Định lượng giá trị vốn liên quan đến danh mục có tín hiệu chậm luân chuyển.',
        result: 'Nhận diện vùng vốn cần rà soát'
      },
      {
        title: 'Hỗ trợ phương án xử lý',
        desc: 'Chuyển tín hiệu thành phương án theo dõi, kết hợp bán hàng hoặc điều chỉnh giá, luôn kèm dữ liệu nguồn.',
        result: 'Quyết định có căn cứ'
      }
    ];
  }
}
