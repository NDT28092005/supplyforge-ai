import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface BlogPost {
  id: string;
  title: string;
  category: string;
  date: string;
  readTime: string;
  summary: string;
  content: string[];
  keyTakeaways: string[];
}

@Component({
  selector: 'app-info-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './info-modal.component.html',
  styleUrls: ['./info-modal.component.css']
})
export class InfoModalComponent {
  @Input() activeTab: 'about' | 'services' | 'blog' = 'about';
  @Output() close = new EventEmitter<void>();
  @Output() navigateAction = new EventEmitter<string>();

  selectedArticle: BlogPost | null = null;

  blogPosts: BlogPost[] = [
    {
      id: 'post-1',
      title: '3 Dấu hiệu nhận biết "Tồn kho chết" và cách xử lý trước khi quá trễ',
      category: 'Quản trị rủi ro',
      date: '15/09/2026',
      readTime: '4 phút đọc',
      summary: 'Làm sao để phát hiện sớm các mặt hàng có nguy cơ đóng băng nguồn vốn ngay từ ngày thứ 45 thay vì chờ đến khi hết mùa hàng.',
      content: [
        'Hàng tồn kho chết (Dead Stock) là một trong những lý do hàng đầu khiến các cửa hàng E-commerce bị cạn kiệt dòng tiền mặt dù doanh số vẫn có vẻ ổn định trên báo cáo.',
        'Dấu hiệu 1: Số ngày ngưng phát sinh đơn hàng kéo dài trên 45 ngày liên tục dù lượt xem sản phẩm vẫn có. Điều này cho thấy giá bán hoặc mức độ hấp dẫn của sản phẩm đã giảm.',
        'Dấu hiệu 2: Tỷ lệ không bán được (Zero-sales rate) vượt quá 75% số ngày trong kỳ quan sát 90 ngày.',
        'Dấu hiệu 3: Chi phí lưu kho và chi phí vốn bắt đầu vượt quá biên lợi nhuận kỳ vọng.',
        'Khuyến nghị: Đánh giá phương án điều chỉnh giá hoặc phân phối theo gói từ sớm, dựa trên biên lợi nhuận và mục tiêu thu hồi vốn.'
      ],
      keyTakeaways: [
        'Đo lường số ngày ngưng phát sinh đơn hàng (DSLS) hàng tuần.',
        'Đánh giá tồn kho từ ngày 45–60 giúp kiểm soát rủi ro mất giá.',
        'Vốn thu hồi cần được phân bổ theo kế hoạch danh mục đã phê duyệt.'
      ]
    },
    {
      id: 'post-2',
      title: 'Tối ưu hóa Vòng quay tồn kho (ITR) trong kinh doanh E-commerce',
      category: 'Quản lý dòng vốn',
      date: '10/09/2026',
      readTime: '5 phút đọc',
      summary: 'Cách tính chỉ số ITR chuẩn xác và áp dụng chiến lược tái đầu tư cuốn chiếu để nhân đôi tốc độ quay vòng vốn nhập hàng.',
      content: [
        'Chỉ số Vòng quay tồn kho (Inventory Turnover Rate - ITR) đo lường số lần kho hàng được bán hết và thay thế trong một khoảng thời gian (thường là 1 năm hoặc 1 quý).',
        'Công thức tính: ITR = Giá vốn hàng bán (COGS) / Giá trị tồn kho trung bình.',
        'Chỉ số ITR cao cho thấy tốc độ quay vòng vốn hiệu quả và mức vốn tồn đọng thấp hơn.',
        'Ngược lại, ITR dưới 3 lần/năm cảnh báo bạn đang nhập quá nhiều hàng bán chậm hoặc giữ tồn kho vượt nhu cầu thực tế.'
      ],
      keyTakeaways: [
        'Duy trì chỉ số ITR mục tiêu từ 6–10 vòng/năm cho mảng bán lẻ.',
        'Chỉ nhập thêm hàng khi SKU đạt tốc độ bán ổn định.',
        'Giảm quy mô lô nhập (Lot size) đối với các mã hàng mới thử nghiệm.'
      ]
    },
    {
      id: 'post-3',
      title: 'Chiến lược xả hàng thu tiền mặt mà không hỏng giá trị thương hiệu',
      category: 'Chiến lược bán hàng',
      date: '02/09/2026',
      readTime: '6 phút đọc',
      summary: 'Phương pháp đóng gói combo tặng kèm (Bundle Cross-selling) và xả qua kênh ẩn giúp xả sạch kho mà không cần công khai hạ giá niêm yết.',
      content: [
        'Một lo lắng lớn của các thương hiệu khi xả hàng là lo ngại làm hỏng định vị giá trong mắt khách hàng thành "hàng giá rẻ".',
        'Giải pháp 1 — Combo mua kèm (Bundle deals): Ghép sản phẩm bán chậm làm quà tặng kèm hoặc bán giá ưu đãi khi mua cùng SKU bán chạy nhất.',
        'Giải pháp 2 — Chương trình Flash Sale kín: Tổ chức bán ưu đãi dành riêng cho khách hàng cũ qua Zalo OA, email hoặc nhóm chăm sóc khách hàng thân thiết.',
        'Giải pháp 3 — Xả hàng theo lô (B2B Liquidation): Bán sỉ nguyên lô cho các đại lý tuyến dưới hoặc đối tác xả tồn chuyên nghiệp.'
      ],
      keyTakeaways: [
        'Ưu tiên ghép bundle sản phẩm thay vì giảm giá đơn lẻ.',
        'Tận dụng tệp khách hàng cũ để giải phóng tồn kho nhanh.',
        'Giữ nguyên giá niêm yết công khai trên gian hàng chính.'
      ]
    },
    {
      id: 'post-4',
      title: 'Cách tính chi phí gánh vốn (Carrying Cost) thực tế cho cửa hàng',
      category: 'Tài chính kho hàng',
      date: '25/08/2026',
      readTime: '4 phút đọc',
      summary: 'Bao gồm chi phí lưu kho, rủi ro lỗi thời, rủi ro mất giá và chi phí cơ hội do không thể nhập hàng mới hot trend.',
      content: [
        'Rất nhiều chủ shop nghĩ rằng hàng nằm trong kho chỉ "tốn không gian". Thực tế, chi phí gánh vốn (Holding/Carrying Cost) chiếm trung bình 15% – 30% giá trị lô hàng mỗi năm.',
        'Các thành phần chi phí gánh vốn:',
        '1. Chi phí vốn (Capital Cost): Lãi suất vay hoặc lợi nhuận kỳ vọng từ số tiền chôn trong kho.',
        '2. Chi phí không gian kho (Storage Space Cost): Phí thuê kho, điện nước, quản lý.',
        '3. Chi phí rủi ro hàng hóa (Inventory Risk Cost): Hàng quá hạn, hư hỏng, lỗi thời mốt.',
        '4. Chi phí cơ hội (Opportunity Cost): Vốn tồn đọng không thể được phân bổ cho các nhu cầu có hiệu quả sử dụng cao hơn.'
      ],
      keyTakeaways: [
        'Chi phí gánh vốn ước tính khoảng 2% – 3% giá trị hàng tồn mỗi tháng.',
        'Mỗi tháng hàng nằm kho đồng nghĩa với việc bạn mất đi một khoản chi phí thực tế.',
        'Giải phóng vốn sớm giúp tối ưu hóa tổng chi phí vận hành.'
      ]
    }
  ];

  selectTab(tab: 'about' | 'services' | 'blog'): void {
    this.activeTab = tab;
    this.selectedArticle = null;
  }

  readArticle(post: BlogPost): void {
    this.selectedArticle = post;
  }

  backToBlogList(): void {
    this.selectedArticle = null;
  }

  closeModal(): void {
    this.close.emit();
  }

  triggerAction(action: string): void {
    this.closeModal();
    this.navigateAction.emit(action);
  }
}
