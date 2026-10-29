import { Component, Input, OnInit, OnChanges, SimpleChanges, ElementRef, ViewChild, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

export interface ChatMessage {
  id: string;
  sender: 'ai' | 'user';
  text: string;
  time: string;
  actions?: QuickAction[];
}

export interface QuickAction {
  label: string;
  query: string;
}

export interface CapabilityCard {
  svgIcon: string; // SVG path data for Lucide-style icon
  title: string;
  desc: string;
  query: string;
}

@Component({
  selector: 'app-copilot-widget',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './copilot-widget.component.html',
  styleUrls: ['./copilot-widget.component.css']
})
export class CopilotWidgetComponent implements OnInit, OnChanges, AfterViewChecked {
  @Input() contextSku: string | null = null;
  @Input() activeStage: string = 'executive-dashboard';

  @ViewChild('chatScrollContainer') private chatScrollContainer!: ElementRef;

  isOpen = false;
  showWelcome = true;
  userQueryText = '';
  isAiThinking = false;
  shouldScrollToBottom = false;
  unreadCount = 0;

  messages: ChatMessage[] = [];

  // Lucide SVG paths for capability icons
  // search icon
  readonly iconSearch = 'M11 17.25a6.25 6.25 0 1 1 0-12.5 6.25 6.25 0 0 1 0 12.5ZM21 21l-4.35-4.35';
  // dollar-sign icon
  readonly iconDollar = 'M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6';
  // clipboard-list icon
  readonly iconClipboard = 'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1ZM12 11h4M12 16h4M8 11h.01M8 16h.01';
  // bar-chart icon
  readonly iconBarChart = 'M12 20V10M18 20V4M6 20v-4';

  capabilities: CapabilityCard[] = [
    {
      svgIcon: this.iconSearch,
      title: 'Tìm hiểu rủi ro sản phẩm',
      desc: 'Sản phẩm nào đang có vấn đề và vì sao — phân tích dựa trên dữ liệu bán hàng thực tế.',
      query: 'Những sản phẩm nào đang có rủi ro cao nhất và nguyên nhân là gì?'
    },
    {
      svgIcon: this.iconDollar,
      title: 'Kiểm tra vốn đang bị kẹt',
      desc: 'Xem bao nhiêu tiền nhập hàng đang nằm im trong kho, chưa quay vòng được.',
      query: 'Hiện tại shop đang bị kẹt bao nhiêu vốn trong kho?'
    },
    {
      svgIcon: this.iconClipboard,
      title: 'Gợi ý cách xử lý hàng ế',
      desc: 'Nên giảm giá bao nhiêu, xả qua kênh nào, ưu tiên mã hàng nào trước.',
      query: 'Tôi nên làm gì với những hàng tồn đang ế?'
    },
    {
      svgIcon: this.iconBarChart,
      title: 'Tổng quan nhanh tình hình kho',
      desc: 'Nhìn nhanh: hàng bán tốt, hàng chậm, hàng cần xả — tất cả trong vài dòng.',
      query: 'Cho tôi xem tổng quan tình hình kho hiện tại'
    }
  ];

  ngOnInit(): void {}

  ngOnChanges(changes: SimpleChanges): void {}

  ngAfterViewChecked(): void {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  toggleWidget(): void {
    this.isOpen = !this.isOpen;
    if (this.isOpen) {
      this.unreadCount = 0;
      this.shouldScrollToBottom = true;
    }
  }

  startFromCapability(card: CapabilityCard): void {
    this.showWelcome = false;
    this.sendUserMessage(card.query);
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessageFromInput();
    }
  }

  sendMessageFromInput(): void {
    if (!this.userQueryText || !this.userQueryText.trim()) return;
    const text = this.userQueryText.trim();
    this.userQueryText = '';
    this.showWelcome = false;
    this.sendUserMessage(text);
  }

  selectQuickAction(action: QuickAction): void {
    this.sendUserMessage(action.query);
  }

  resetToWelcome(): void {
    this.messages = [];
    this.showWelcome = true;
  }

  private sendUserMessage(text: string): void {
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: text,
      time: this.getFormattedTime()
    };
    this.messages.push(userMsg);
    this.shouldScrollToBottom = true;

    this.isAiThinking = true;
    const thinkTime = 500 + Math.random() * 600;
    setTimeout(() => {
      this.generateAiResponse(text);
      this.isAiThinking = false;
      this.shouldScrollToBottom = true;
    }, thinkTime);
  }

  private generateAiResponse(query: string): void {
    const q = query.toLowerCase();
    let replyText = '';
    let actions: QuickAction[] = [];

    // --- Risk Analysis ---
    if (q.includes('rủi ro') && (q.includes('cao nhất') || q.includes('nguyên nhân') || q.includes('có vấn đề'))) {
      replyText =
        'Dựa trên dữ liệu bán hàng, kho của bạn hiện có 3 nhóm sản phẩm chính:\n\n' +
        '**Nhóm cần xử lý gấp** — Đây là hàng nằm kho trên 120 ngày, gần như không có đơn mới. Càng giữ lâu càng mất giá, nên ưu tiên xả sớm.\n\n' +
        '**Nhóm cần theo dõi** — Hàng bắt đầu chậm dần trong 30–90 ngày gần đây. Nếu không can thiệp kịp, nhóm này sẽ chuyển sang ế hoàn toàn.\n\n' +
        '**Nhóm bán tốt** — Hàng quay vòng đều, không cần lo.\n\n' +
        'Nguyên nhân thường gặp: sản phẩm đã qua mùa, giá nhập cao hơn giá thị trường, hoặc đơn giản là mặt hàng ít người tìm kiếm.';
      actions = [
        { label: 'Xem chi tiết trong tab Rủi ro', query: 'Hướng dẫn tôi xem tab Rủi ro' },
        { label: 'Nên xử lý thế nào?', query: 'Tôi nên làm gì với những hàng tồn đang ế?' }
      ];

    // --- Capital stuck ---
    } else if (q.includes('vốn') && (q.includes('kẹt') || q.includes('tồn đọng') || q.includes('dòng tiền') || q.includes('chôn'))) {
      replyText =
        'Vốn bị kẹt nghĩa là số tiền bạn đã bỏ ra nhập hàng nhưng hàng chưa bán được — tiền đó đang "nằm im" trong kho thay vì quay vòng.\n\n' +
        'Điều này ảnh hưởng trực tiếp:\n' +
        '• Bạn không có tiền nhập thêm mặt hàng đang bán chạy\n' +
        '• Mỗi tháng vẫn phải trả phí kho, phí vận hành\n' +
        '• Hàng để lâu thường mất giá — thu hồi được ít hơn\n\n' +
        'Bạn có thể vào mục **Đánh giá vốn** để xem cụ thể từng sản phẩm đang giữ bao nhiêu vốn và nên ưu tiên giải phóng cái nào.';
      actions = [
        { label: 'Xem mục Đánh giá vốn', query: 'Hướng dẫn tôi xem tab Đánh giá vốn' },
        { label: 'Cách thu hồi vốn nhanh', query: 'Làm sao để thu hồi vốn bị kẹt nhanh nhất?' }
      ];

    // --- Liquidation advice ---
    } else if ((q.includes('xử lý') || q.includes('làm gì')) && (q.includes('hàng tồn') || q.includes('hàng ế') || q.includes('ế'))) {
      replyText =
        'Tùy tình trạng từng sản phẩm, bạn có thể cân nhắc:\n\n' +
        '**Với hàng ế nặng (trên 120 ngày):**\nGiảm sâu 30–50% và đẩy qua Flash Sale hoặc combo bundle. Mục tiêu là thu hồi tiền mặt nhanh — dù lỗ một chút vẫn tốt hơn để hàng tiếp tục mất giá.\n\n' +
        '**Với hàng chậm (30–90 ngày):**\nGiảm nhẹ 10–20%, kết hợp chạy ads hoặc tặng voucher. Nhóm này vẫn có cơ hội bán được nếu có đủ lượt tiếp cận.\n\n' +
        '**Với hàng bình thường:**\nGiữ nguyên giá, tối ưu ảnh và mô tả sản phẩm.\n\n' +
        'Mục **Đề xuất xử lý** có phương án cụ thể cho từng mã hàng; bạn có thể mở mục này để xem chi tiết.';
      actions = [
        { label: 'Xem đề xuất cụ thể', query: 'Hướng dẫn tôi xem tab Đề xuất xử lý' },
        { label: 'Giảm bao nhiêu là hợp lý?', query: 'Giảm giá bao nhiêu phần trăm cho hàng tồn kho là hợp lý?' }
      ];

    // --- Overview ---
    } else if (q.includes('tổng quan') || q.includes('tình hình kho') || q.includes('xem nhanh')) {
      replyText =
        'Hệ thống đã phân tích toàn bộ dữ liệu bán hàng và tồn kho của shop bạn.\n\n' +
        'Trong tab **Tổng quan**, bạn sẽ thấy:\n' +
        '• Tổng giá trị hàng tồn và bao nhiêu trong đó đang có vấn đề\n' +
        '• Số lượng sản phẩm cần can thiệp sớm\n' +
        '• Chi phí cơ hội mỗi tháng do hàng nằm im\n' +
        '• Danh sách nhanh những mã hàng đáng lo nhất\n\n' +
        'Nếu mới dùng lần đầu, tôi khuyên bạn bắt đầu từ Tổng quan → Rủi ro → Khuyến nghị, theo thứ tự đó sẽ dễ nắm bắt nhất.';
      actions = [
        { label: 'Mở tab Tổng quan', query: 'Hướng dẫn tôi xem tab Tổng quan' },
        { label: 'Hàng nào cần xả gấp?', query: 'Những sản phẩm nào đang có rủi ro cao nhất và nguyên nhân là gì?' }
      ];

    // --- Tab guides ---
    } else if (q.includes('hướng dẫn') && (q.includes('tổng quan') || q.includes('tab tổng'))) {
      replyText =
        'Tab **Tổng quan** là điểm khởi đầu — giúp bạn nắm bức tranh toàn cảnh kho hàng.\n\n' +
        'Phía trên là các thẻ chỉ số chính: tổng vốn tồn, số sản phẩm rủi ro, chi phí hàng tháng.\n\n' +
        'Phía dưới là danh sách những sản phẩm đang "chiếm" nhiều vốn nhất — bạn có thể click vào từng dòng để xem chi tiết hoặc chuyển sang tab khác để đi sâu hơn.';

    } else if (q.includes('hướng dẫn') && (q.includes('rủi ro') || q.includes('tab rủi'))) {
      replyText =
        'Tab **Rủi ro** giúp bạn biết sản phẩm nào đang có vấn đề và mức độ ra sao.\n\n' +
        'Ở trên có bộ lọc — bạn có thể lọc theo mức rủi ro: Cao, Trung bình, Thấp.\n\n' +
        'Bảng bên dưới hiển thị từng sản phẩm với thông tin: thời gian nằm kho, tốc độ bán, điểm rủi ro. Bạn click vào dòng nào sẽ xem phân tích chi tiết cho sản phẩm đó.\n\n' +
        'Nên xem nhóm rủi ro Cao trước — đây là nhóm cần hành động ngay để tránh mất thêm tiền.';

    } else if (q.includes('hướng dẫn') && (q.includes('đánh giá vốn') || q.includes('tab đánh'))) {
      replyText =
        'Tab **Đánh giá vốn** cho bạn thấy rõ tiền đang bị kẹt ở đâu.\n\n' +
        'Bạn sẽ thấy tổng vốn tồn đọng, chi phí gánh vốn hàng tháng, và bảng chi tiết từng sản phẩm đang chiếm bao nhiêu tiền.\n\n' +
        'Dùng bộ lọc "Vốn rủi ro cao" để nhanh chóng tìm ra những mã hàng chiếm vốn nhiều nhất — đó là những cái nên ưu tiên xả trước.';

    } else if (q.includes('hướng dẫn') && (q.includes('khuyến nghị') || q.includes('xả hàng') || q.includes('tab khuyến'))) {
      replyText =
        'Tab **Đề xuất xử lý** là nơi hệ thống đưa ra phương án cụ thể cho từng sản phẩm.\n\n' +
        'Mỗi sản phẩm có: hành động gợi ý (giảm giá / xử lý tồn kho / theo dõi), mức giảm đề xuất và giá trị thu hồi dự kiến.\n\n' +
        'Bạn có thể duyệt từng đề xuất và chọn "Duyệt" hoặc "Bỏ qua" — hoàn toàn do bạn quyết định.';

    // --- Discount guidance ---
    } else if (q.includes('giảm giá') && (q.includes('bao nhiêu') || q.includes('hợp lý') || q.includes('phần trăm'))) {
      replyText =
        'Mức giảm phụ thuộc vào hàng đã nằm kho bao lâu:\n\n' +
        '**30–60 ngày không bán được:** Thử giảm 10–15% — vẫn là mức an toàn, xem thị trường phản ứng thế nào.\n\n' +
        '**60–120 ngày:** Cần mạnh tay hơn, 20–30%. Lúc này ưu tiên tốc độ quay vòng hơn là biên lợi nhuận.\n\n' +
        '**Trên 120 ngày:** Giảm 35–50% và xả dứt điểm. Giữ thêm chỉ tốn thêm tiền kho mà hàng ngày càng khó bán hơn.\n\n' +
        'Một sai lầm phổ biến là giảm quá ít (5–10%) cho hàng ế lâu — mức đó thường không đủ để khách hàng chú ý. Chấp nhận cắt lỗ sớm sẽ giúp bạn có tiền mặt nhập hàng mới bán chạy hơn.';
      actions = [
        { label: 'Xem đề xuất cho từng sản phẩm', query: 'Hướng dẫn tôi xem tab Đề xuất xử lý' }
      ];

    // --- Capital recovery ---
    } else if (q.includes('thu hồi vốn') && (q.includes('nhanh') || q.includes('cách'))) {
      replyText =
        'Quy trình thu hồi vốn nhanh nhất:\n\n' +
        '**Bước 1** — Vào tab Rủi ro, xác định nhóm sản phẩm rủi ro cao nhất.\n\n' +
        '**Bước 2** — Qua tab Đánh giá vốn, xem sản phẩm nào đang chiếm nhiều vốn nhất.\n\n' +
        '**Bước 3** — Vào tab Khuyến nghị, áp dụng mức giảm giá mà hệ thống gợi ý.\n\n' +
        '**Bước 4** — Đưa lên sàn với giá mới, chạy Flash Sale hoặc kết hợp voucher.\n\n' +
        'Nguyên tắc cơ bản: xử lý mã hàng chiếm vốn lớn trước. Một sản phẩm ế giá trị 50 triệu cần ưu tiên hơn 10 sản phẩm ế giá trị 1 triệu.';
      actions = [
        { label: 'Hàng nào chiếm vốn nhiều nhất?', query: 'Hiện tại shop đang bị kẹt bao nhiêu vốn trong kho?' }
      ];

    // --- Fallback ---
    } else {
      replyText =
        'Tôi có thể hỗ trợ bạn mấy việc chính:\n\n' +
        '• Tìm hiểu sản phẩm nào đang có rủi ro và vì sao\n' +
        '• Xem bao nhiêu vốn đang bị kẹt trong kho\n' +
        '• Gợi ý phương án xử lý hàng tồn\n' +
        '• Hướng dẫn sử dụng từng phần trong hệ thống\n\n' +
        'Bạn cứ hỏi cụ thể hoặc chọn một chủ đề bên dưới.';
      actions = [
        { label: 'Sản phẩm nào đang rủi ro?', query: 'Những sản phẩm nào đang có rủi ro cao nhất và nguyên nhân là gì?' },
        { label: 'Kiểm tra vốn bị kẹt', query: 'Hiện tại shop đang bị kẹt bao nhiêu vốn trong kho?' },
        { label: 'Gợi ý xử lý hàng ế', query: 'Tôi nên làm gì với những hàng tồn đang ế?' }
      ];
    }

    this.messages.push({
      id: `ai-${Date.now()}`,
      sender: 'ai',
      text: replyText,
      time: this.getFormattedTime(),
      actions: actions.length > 0 ? actions : undefined
    });
  }

  formatText(text: string): string {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }

  private getFormattedTime(): string {
    const now = new Date();
    const hours = now.getHours().toString().padStart(2, '0');
    const minutes = now.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  }

  private scrollToBottom(): void {
    try {
      if (this.chatScrollContainer) {
        this.chatScrollContainer.nativeElement.scrollTop = this.chatScrollContainer.nativeElement.scrollHeight;
      }
    } catch (err) {
      console.warn('Scroll to bottom error:', err);
    }
  }
}
