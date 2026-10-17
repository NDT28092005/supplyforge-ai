"""
SupplyForge AI — Content API Views (About Us, Services, Blog)
============================================================
REST API endpoints delivering rich content for About Us, Services & Solutions,
and Inventory Management Blog articles.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

@api_view(['GET'])
@permission_classes([AllowAny])
def about_us_api(request):
    """GET /api/v1/about_us - Returns company mission, vision, core values and platform stats."""
    data = {
        "title": "Kho không thiếu dữ liệu. Kho thiếu thứ tự để xử lý.",
        "tagline": "Hệ thống điều hành rủi ro tồn kho cho nhà bán lẻ và e-commerce Việt Nam",
        "description": "SupplyForge giúp merchant nhìn rõ hàng bán chậm, vốn đang nằm ở đâu và việc nào cần được đưa lên trước trong kế hoạch xử lý kho.",
        "stats": [
            {"label": "Tỷ lệ tiết kiệm thời gian", "value": "95%", "desc": "Chuẩn hóa SKU tự động thay vì rà soát Excel thủ công"},
            {"label": "Tỷ lệ giải phóng dòng tiền", "value": "30%", "desc": "Thu hồi dòng vốn kẹt ở hàng cận date & bán chậm"},
            {"label": "Độ chính xác mô hình ML", "value": "98.2%", "desc": "Phân loại chu kỳ không phát sinh đơn hàng"}
        ],
        "core_values": [
            {
                "id": "val-1",
                "title": "Dữ liệu có căn cứ",
                "desc": "Mỗi tín hiệu được đặt cạnh lịch sử bán, tồn và nguồn dữ liệu để đội ngũ kiểm tra lại."
            },
            {
                "id": "val-2",
                "title": "Ưu tiên có lý do",
                "desc": "Danh mục được sắp theo mức cần xử lý để merchant không phải dò từng mã hàng bằng tay."
            },
            {
                "id": "val-3",
                "title": "Hành động có thể theo dõi",
                "desc": "Khuyến nghị được đưa về các phương án cụ thể để đội ngũ bàn bạc, duyệt và theo dõi."
            }
        ]
    }
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def services_api(request):
    """GET /api/v1/services - Returns list of core inventory services and solutions."""
    services = [
        {
            "id": "srv-1",
            "title": "Nhận diện hàng bán chậm",
            "desc": "Đặt SKU vào mức ưu tiên dựa trên nhịp bán và tín hiệu rủi ro.",
            "icon": "alert-triangle",
            "badge": "Phân tích tự động",
            "result": "Biết mã nào cần xem trước"
        },
        {
            "id": "srv-2",
            "title": "Nhìn rõ vốn đang bị giữ",
            "desc": "Nối giá trị tồn với mức độ bán chậm theo từng SKU.",
            "icon": "credit-card",
            "badge": "Đo lường tài chính",
            "result": "Thấy phần vốn cần quan tâm"
        },
        {
            "id": "srv-3",
            "title": "Chuẩn bị hướng xử lý",
            "desc": "Đưa các phương án hành động vào cùng bối cảnh dữ liệu kho.",
            "icon": "trending-up",
            "badge": "Hỗ trợ quyết định",
            "result": "Có phương án để đội ngũ duyệt"
        },
        {
            "id": "srv-4",
            "title": "Kiểm tra và chuẩn hóa file nhập",
            "desc": "Đọc tệp CSV từ nhiều nguồn, đối chiếu cột và chặn dữ liệu trùng.",
            "icon": "layers",
            "badge": "Dữ liệu đầu vào",
            "result": "Bắt đầu phân tích từ dữ liệu sạch"
        }
    ]
    return Response({"services": services}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_list_api(request):
    """GET /api/v1/blog - Returns list of inventory management blog posts."""
    posts = [
        {
            "id": "post-1",
            "slug": "dau-hieu-ton-kho-chet",
            "title": "3 Dấu hiệu nhận biết \"Tồn kho chết\" và cách xử lý trước khi quá trễ",
            "category": "Quản trị rủi ro",
            "date": "15/09/2026",
            "read_time": "4 phút đọc",
            "summary": "Làm sao để phát hiện sớm các mặt hàng có nguy cơ đóng băng nguồn vốn ngay từ ngày thứ 45 thay vì chờ đến khi hết mùa hàng."
        },
        {
            "id": "post-2",
            "slug": "toi-uu-vong-quay-ton-kho-itr",
            "title": "Tối ưu hóa Vòng quay tồn kho (ITR) trong kinh doanh E-commerce",
            "category": "Quản lý dòng vốn",
            "date": "10/09/2026",
            "read_time": "5 phút đọc",
            "summary": "Cách tính chỉ số ITR chuẩn xác và áp dụng chiến lược tái đầu tư cuốn chiếu để nhân đôi tốc độ quay vòng vốn nhập hàng."
        },
        {
            "id": "post-3",
            "slug": "chien-luoc-xa-hang-khong-hong-thuong-hieu",
            "title": "Chiến lược xả hàng thu tiền mặt mà không hỏng giá trị thương hiệu",
            "category": "Chiến lược bán hàng",
            "date": "02/09/2026",
            "read_time": "6 phút đọc",
            "summary": "Phương pháp đóng gói combo tặng kèm (Bundle Cross-selling) và xả qua kênh ẩn giúp xả sạch kho mà không cần công khai hạ giá niêm yết."
        },
        {
            "id": "post-4",
            "slug": "tinh-chi-phi-ganh-von-carrying-cost",
            "title": "Cách tính chi phí gánh vốn (Carrying Cost) thực tế cho cửa hàng",
            "category": "Tài chính kho hàng",
            "date": "25/08/2026",
            "read_time": "4 phút đọc",
            "summary": "Bao gồm chi phí lưu kho, rủi ro lỗi thời, rủi ro mất giá và chi phí cơ hội do không thể nhập hàng mới hot trend."
        }
    ]
    return Response({"posts": posts}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_detail_api(request, slug):
    """GET /api/v1/blog/<slug> - Returns detailed blog post content."""
    articles = {
        "dau-hieu-ton-kho-chet": {
            "id": "post-1",
            "slug": "dau-hieu-ton-kho-chet",
            "title": "3 Dấu hiệu nhận biết \"Tồn kho chết\" và cách xử lý trước khi quá trễ",
            "category": "Quản trị rủi ro",
            "date": "15/09/2026",
            "read_time": "4 phút đọc",
            "summary": "Làm sao để phát hiện sớm các mặt hàng có nguy cơ đóng băng nguồn vốn ngay từ ngày thứ 45 thay vì chờ đến khi hết mùa hàng.",
            "content": [
                "Hàng tồn kho chết (Dead Stock) là một trong những lý do hàng đầu khiến các cửa hàng E-commerce bị cạn kiệt dòng tiền mặt dù doanh số vẫn có vẻ ổn định trên báo cáo.",
                "Dấu hiệu 1: Số ngày ngưng phát sinh đơn hàng kéo dài trên 45 ngày liên tục dù lượt xem sản phẩm vẫn có. Điều này cho thấy giá bán hoặc mức độ hấp dẫn của sản phẩm đã giảm.",
                "Dấu hiệu 2: Tỷ lệ không bán được (Zero-sales rate) vượt quá 75% số ngày trong kỳ quan sát 90 ngày.",
                "Dấu hiệu 3: Chi phí gánh vốn (phí kho, chi phí chôn tiền) bắt đầu vượt quá biên lợi nhuận dự kiến ban đầu.",
                "Lời khuyên: Chấp nhận giảm giá xả tồn từ 20–30% ở giai đoạn sớm sẽ thu hồi tiền mặt nhanh hơn rất nhiều so với việc chờ 6 tháng sau mới giảm 50%."
            ],
            "key_takeaways": [
                "Đo lường số ngày ngưng phát sinh đơn hàng (DSLS) hàng tuần.",
                "Xả tồn sớm từ ngày 45–60 giúp bảo toàn tối đa giá vốn.",
                "Tiền mặt thu về từ xả hàng nên tái đầu tư ngay vào SKU bán chạy."
            ]
        },
        "toi-uu-vong-quay-ton-kho-itr": {
            "id": "post-2",
            "slug": "toi-uu-vong-quay-ton-kho-itr",
            "title": "Tối ưu hóa Vòng quay tồn kho (ITR) trong kinh doanh E-commerce",
            "category": "Quản lý dòng vốn",
            "date": "10/09/2026",
            "read_time": "5 phút đọc",
            "summary": "Cách tính chỉ số ITR chuẩn xác và áp dụng chiến lược tái đầu tư cuốn chiếu để nhân đôi tốc độ quay vòng vốn nhập hàng.",
            "content": [
                "Chỉ số Vòng quay tồn kho (Inventory Turnover Rate - ITR) đo lường số lần kho hàng được bán hết và thay thế trong một khoảng thời gian (thường là 1 năm hoặc 1 quý).",
                "Công thức tính: ITR = Giá vốn hàng bán (COGS) / Giá trị tồn kho trung bình.",
                "Một chỉ số ITR cao (từ 6 đến 12 lần/năm) chứng tỏ dòng tiền quay vòng rất nhanh, cửa hàng ít bị chôn vốn và khả năng thích ứng với thị trường cao.",
                "Ngược lại, ITR dưới 3 lần/năm cảnh báo bạn đang nhập quá nhiều hàng bán chậm hoặc giữ tồn kho vượt nhu cầu thực tế."
            ],
            "key_takeaways": [
                "Duy trì chỉ số ITR mục tiêu từ 6–10 vòng/năm cho mảng bán lẻ.",
                "Chỉ nhập thêm hàng khi SKU đạt tốc độ bán ổn định.",
                "Giảm quy mô lô nhập (Lot size) đối với các mã hàng mới thử nghiệm."
            ]
        },
        "chien-luoc-xa-hang-khong-hong-thuong-hieu": {
            "id": "post-3",
            "slug": "chien-luoc-xa-hang-khong-hong-thuong-hieu",
            "title": "Chiến lược xả hàng thu tiền mặt mà không hỏng giá trị thương hiệu",
            "category": "Chiến lược bán hàng",
            "date": "02/09/2026",
            "read_time": "6 phút đọc",
            "summary": "Phương pháp đóng gói combo tặng kèm (Bundle Cross-selling) và xả qua kênh ẩn giúp xả sạch kho mà không cần công khai hạ giá niêm yết.",
            "content": [
                "Một lo lắng lớn của các thương hiệu khi xả hàng là lo ngại làm hỏng định vị giá trong mắt khách hàng thành \"hàng giá rẻ\".",
                "Giải pháp 1 — Combo mua kèm (Bundle deals): Ghép sản phẩm bán chậm làm quà tặng kèm hoặc bán giá ưu đãi khi mua cùng SKU bán chạy nhất.",
                "Giải pháp 2 — Chương trình Flash Sale kín: Tổ chức bán ưu đãi dành riêng cho khách hàng cũ qua Zalo OA, email hoặc nhóm chăm sóc khách hàng thân thiết.",
                "Giải pháp 3 — Xả hàng theo lô (B2B Liquidation): Bán sỉ nguyên lô cho các đại lý tuyến dưới hoặc đối tác xả tồn chuyên nghiệp."
            ],
            "key_takeaways": [
                "Ưu tiên ghép bundle sản phẩm thay vì giảm giá đơn lẻ.",
                "Tận dụng tệp khách hàng cũ để giải phóng tồn kho nhanh.",
                "Giữ nguyên giá niêm yết công khai trên gian hàng chính."
            ]
        },
        "tinh-chi-phi-ganh-von-carrying-cost": {
            "id": "post-4",
            "slug": "tinh-chi-phi-ganh-von-carrying-cost",
            "title": "Cách tính chi phí gánh vốn (Carrying Cost) thực tế cho cửa hàng",
            "category": "Tài chính kho hàng",
            "date": "25/08/2026",
            "read_time": "4 phút đọc",
            "summary": "Bao gồm chi phí lưu kho, rủi ro lỗi thời, rủi ro mất giá và chi phí cơ hội do không thể nhập hàng mới hot trend.",
            "content": [
                "Rất nhiều chủ shop nghĩ rằng hàng nằm trong kho chỉ \"tốn không gian\". Thực tế, chi phí gánh vốn (Holding/Carrying Cost) chiếm trung bình 15% – 30% giá trị lô hàng mỗi năm.",
                "Các thành phần chi phí gánh vốn:",
                "1. Chi phí vốn (Capital Cost): Lãi suất vay hoặc lợi nhuận kỳ vọng từ số tiền chôn trong kho.",
                "2. Chi phí không gian kho (Storage Space Cost): Phí thuê kho, điện nước, quản lý.",
                "3. Chi phí rủi ro hàng hóa (Inventory Risk Cost): Hàng quá hạn, hư hỏng, lỗi thời mốt.",
                "4. Chi phí cơ hội (Opportunity Cost): Tiền kẹt ở hàng ế không thể dùng để nhập mặt hàng đang bán chạy số 1."
            ],
            "key_takeaways": [
                "Chi phí gánh vốn ước tính khoảng 2% – 3% giá trị hàng tồn mỗi tháng.",
                "Mỗi tháng hàng nằm kho đồng nghĩa với việc bạn mất đi một khoản chi phí thực tế.",
                "Giải phóng vốn sớm giúp tối ưu hóa tổng chi phí vận hành."
            ]
        }
    }
    
    post = articles.get(slug)
    if not post:
        # Fallback to first post if slug not found
        post = articles.get("dau-hieu-ton-kho-chet")
        
    return Response(post, status=status.HTTP_200_OK)
