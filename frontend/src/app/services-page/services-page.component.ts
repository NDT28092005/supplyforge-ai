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
        title: 'Kiểm tra và chuẩn hóa file',
        desc: 'Đối chiếu cột, ngày bán và bản ghi trùng trước khi dữ liệu được dùng để phân tích.',
        result: 'Đầu vào rõ ràng hơn'
      },
      {
        title: 'Nhận diện hàng bán chậm có giải thích',
        desc: 'Đọc sức bán theo nhiều cửa sổ thời gian và đặt cạnh tồn kho, giá trị vốn liên quan.',
        result: 'Biết SKU cần xem trước'
      },
      {
        title: 'Ước tính tác động lên dòng vốn',
        desc: 'Nhìn phần vốn đang bị giữ trong hàng chậm để đội ngũ cân nhắc hành động phù hợp.',
        result: 'Biết tiền đang ở đâu'
      },
      {
        title: 'Đề xuất hướng xử lý để duyệt',
        desc: 'Chuyển tín hiệu thành phương án như theo dõi, bán kèm hoặc xả hàng, luôn kèm dữ liệu nguồn.',
        result: 'Quyết định có căn cứ'
      }
    ];
  }
}
