import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { ApiService } from '../api.service';
import { PageMotionDirective } from '../core/motion/page-motion.directive';

@Component({
  selector: 'app-blog-page',
  standalone: true,
  imports: [CommonModule, RouterModule, PageMotionDirective],
  templateUrl: './blog-page.component.html',
  styleUrls: ['./blog-page.component.css']
})
export class BlogPageComponent implements OnInit {
  posts: any[] = [];
  selectedArticle: any = null;
  loading = true;
  loadingArticle = false;

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    this.posts = this.defaultPosts();
    this.apiService.getBlogPosts().subscribe({
      next: (res) => {
        if (res?.posts?.length) this.posts = res.posts;
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load Blog Posts API:', err);
        this.loading = false;
      }
    });
  }

  readArticle(slug: string): void {
    this.loadingArticle = true;
    this.apiService.getBlogDetail(slug).subscribe({
      next: (res) => {
        this.selectedArticle = res;
        this.loadingArticle = false;
      },
      error: (err) => {
        console.error('Failed to load Blog Detail API:', err);
        this.selectedArticle = this.posts.find((post) => post.slug === slug) || null;
        this.loadingArticle = false;
      }
    });
  }

  backToList(): void {
    this.selectedArticle = null;
  }

  private defaultPosts(): any[] {
    return [
      {
        slug: 'doc-du-lieu-ton-kho-theo-cua-so-thoi-gian',
        category: 'Data windows',
        read_time: '4 phút đọc',
        title: 'Vì sao cùng một SKU có thể “chậm” ở 7 ngày nhưng không chậm ở 90 ngày?',
        summary: 'Một cửa sổ ngắn phản ánh nhịp bán gần đây. Một cửa sổ dài cho bạn biết đó là nhiễu tạm thời hay một xu hướng cần hành động.',
        content: [
          'Khi nhìn vào hàng bán chậm, câu hỏi quan trọng không chỉ là “đã bán bao nhiêu?”. Cần biết con số đó được đo trong khoảng thời gian nào.',
          'Cửa sổ 7 ngày giúp nhận ra thay đổi mới, 30 ngày cho một bối cảnh cân bằng hơn và 90 ngày giúp tránh kết luận vội từ một tuần đặc biệt.',
          'Vì vậy, một phiên nạp mới không nên ghi đè lịch sử. Phiên này cần được lưu cùng mốc dữ liệu và các cửa sổ quan sát để đội ngũ có thể đối chiếu.'
        ],
        key_takeaways: ['Luôn kiểm tra mốc dữ liệu cuối cùng.', 'Không dùng một cửa sổ duy nhất để đưa ra quyết định.', 'Lưu lịch sử phiên nạp để theo dõi xu hướng.']
      },
      {
        slug: 'hang-ban-cham-khong-dong-nghia-voi-hang-xau',
        category: 'Inventory basics',
        read_time: '5 phút đọc',
        title: 'Hàng bán chậm không đồng nghĩa với hàng xấu',
        summary: 'Một sản phẩm có thể đang ở mùa thấp điểm, vừa ra mắt hoặc bị che khuất bởi một SKU thay thế.',
        content: [
          'Tốc độ bán chậm là một tín hiệu để xem xét, không phải một phán quyết. Cần đặt nó cạnh tuổi tồn, giá trị vốn và lịch sử theo mùa.',
          'Một hệ thống hỗ trợ quyết định tốt phải cho thấy lý do và dữ liệu nền để người quản lý kiểm tra trước khi hành động.'
        ],
        key_takeaways: ['Tín hiệu cần bối cảnh.', 'AI nên giúp đặt câu hỏi đúng hơn là thay bạn kết luận.']
      },
      {
        slug: 'chuan-bi-tep-csv-cho-phan-tich',
        category: 'Quy trình dữ liệu',
        read_time: '3 phút đọc',
        title: 'Danh mục kiểm tra trước khi nạp tệp CSV',
        summary: 'Tên cột, ngày bán, mã SKU và bản ghi trùng là bốn điểm cần được xác thực trước khi phân tích.',
        content: [
          'Tệp bán hàng cần có cấu trúc đủ rõ để mỗi bản ghi được nhận diện chính xác trong quá trình phân tích.',
          'SupplyForge kiểm tra cấu trúc dữ liệu trước khi chuyển sang bước ánh xạ trường và đánh giá rủi ro.'
        ],
        key_takeaways: ['Có tiêu đề cột rõ ràng.', 'Có trường ngày bán và mã SKU.', 'Tránh nạp lại cùng một tệp khi chưa cần thiết.']
      }
    ];
  }
}
