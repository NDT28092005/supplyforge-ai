"""Public content API for SupplyForge pages."""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def about_us_api(request):
    """Return the public positioning and operating principles of the platform."""
    data = {
        "title": "Dữ liệu tồn kho cần được chuyển thành thứ tự ưu tiên rõ ràng.",
        "tagline": "Nền tảng phân tích rủi ro tồn kho cho doanh nghiệp thương mại Việt Nam",
        "description": (
            "SupplyForge đặt dữ liệu bán hàng trong đúng bối cảnh thời gian để đội ngũ có thể "
            "đánh giá danh mục, đối chiếu giá trị vốn và lựa chọn nội dung cần rà soát trước."
        ),
        "stats": [],
        "core_values": [
            {
                "id": "val-1",
                "title": "Dữ liệu có thể truy vết",
                "desc": "Mỗi tín hiệu được trình bày cùng lịch sử bán hàng, tồn kho và nguồn dữ liệu để đội ngũ rà soát.",
            },
            {
                "id": "val-2",
                "title": "Ưu tiên có cơ sở",
                "desc": "Danh mục được sắp xếp theo mức độ cần đánh giá để tập trung nguồn lực vào các SKU phù hợp.",
            },
            {
                "id": "val-3",
                "title": "Quyết định có kiểm soát",
                "desc": "Khuyến nghị được đưa về các phương án cụ thể để đội ngũ thảo luận, phê duyệt và theo dõi.",
            },
        ],
    }
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def services_api(request):
    """Return the platform capabilities displayed on the public features page."""
    services = [
        {
            "id": "srv-1",
            "title": "Xác thực và chuẩn hóa dữ liệu",
            "desc": "Đối chiếu trường dữ liệu, ngày bán và bản ghi trùng trước khi dữ liệu được sử dụng để phân tích.",
            "icon": "layers",
            "badge": "Dữ liệu đầu vào",
            "result": "Dữ liệu đầu vào đáng tin cậy",
        },
        {
            "id": "srv-2",
            "title": "Nhận diện rủi ro chậm luân chuyển",
            "desc": "Đánh giá tốc độ bán theo nhiều cửa sổ thời gian cùng tồn kho và các tín hiệu rủi ro liên quan.",
            "icon": "alert-triangle",
            "badge": "Phân tích rủi ro",
            "result": "Xác định SKU cần ưu tiên",
        },
        {
            "id": "srv-3",
            "title": "Đánh giá mức độ sử dụng vốn",
            "desc": "Đặt giá trị tồn kho cạnh mức độ rủi ro để nhận diện các vùng vốn cần được rà soát.",
            "icon": "credit-card",
            "badge": "Đánh giá vốn",
            "result": "Nhận diện vùng vốn cần quan tâm",
        },
        {
            "id": "srv-4",
            "title": "Hỗ trợ phương án xử lý",
            "desc": "Kết nối tín hiệu với các phương án theo dõi, kết hợp bán hàng hoặc điều chỉnh giá để đội ngũ phê duyệt.",
            "icon": "trending-up",
            "badge": "Hỗ trợ quyết định",
            "result": "Quyết định có căn cứ",
        },
    ]
    return Response({"services": services}, status=status.HTTP_200_OK)


def _article(article_id, slug, title, category, read_time, summary, content, key_takeaways):
    return {
        "id": article_id,
        "slug": slug,
        "title": title,
        "category": category,
        "date": "",
        "read_time": read_time,
        "summary": summary,
        "content": content,
        "key_takeaways": key_takeaways,
    }


def _articles():
    return {
        "nhan-dien-rui-ro-cham-luan-chuyen": _article(
            "post-1",
            "nhan-dien-rui-ro-cham-luan-chuyen",
            "Nhận diện sớm danh mục có nguy cơ chậm luân chuyển",
            "Quản trị rủi ro",
            "4 phút đọc",
            "Các tín hiệu cần xem xét để xác định danh mục cần rà soát trước, thay vì dựa vào một chỉ số đơn lẻ.",
            [
                "Tốc độ bán thấp là một tín hiệu cần được đặt trong bối cảnh thời gian, mùa vụ, tồn kho và giá trị vốn liên quan.",
                "Việc không phát sinh doanh số trong một cửa sổ quan sát có thể là dấu hiệu cần theo dõi, nhưng không tự động xác định nguyên nhân hoặc phương án xử lý.",
                "Danh mục nên được ưu tiên theo mức độ rủi ro và khả năng tác động, sau đó được đội ngũ vận hành xác thực trước khi triển khai.",
            ],
            [
                "Dùng nhiều cửa sổ thời gian để phân biệt biến động ngắn hạn và xu hướng kéo dài.",
                "Đối chiếu tín hiệu bán hàng với tồn kho và giá trị vốn.",
                "Xem rủi ro là cơ sở để rà soát, không phải một quyết định tự động.",
            ],
        ),
        "doc-chi-so-vong-quay-ton-kho": _article(
            "post-2",
            "doc-chi-so-vong-quay-ton-kho",
            "Đọc chỉ số vòng quay tồn kho trong bối cảnh vận hành",
            "Quản lý vốn",
            "5 phút đọc",
            "Cách sử dụng chỉ số vòng quay như một tín hiệu quản trị, kết hợp với danh mục, chu kỳ kinh doanh và dữ liệu bán hàng.",
            [
                "Vòng quay tồn kho phản ánh tương quan giữa giá vốn hàng bán và giá trị tồn kho bình quân trong một giai đoạn xác định.",
                "Không có một ngưỡng vòng quay phù hợp cho mọi doanh nghiệp. Mục tiêu cần được xác lập theo ngành hàng, chu kỳ cung ứng và chính sách danh mục.",
                "Chỉ số tổng hợp cần được đọc cùng các SKU cụ thể để xác định khu vực nào đang tạo ra biến động đáng chú ý.",
            ],
            [
                "Thống nhất kỳ đo lường trước khi so sánh các giai đoạn.",
                "Đánh giá vòng quay theo nhóm hàng và SKU, không chỉ ở cấp tổng danh mục.",
                "Không diễn giải chỉ số đơn lẻ mà thiếu bối cảnh vận hành.",
            ],
        ),
        "thiet-ke-phuong-an-xu-ly-ton-kho": _article(
            "post-3",
            "thiet-ke-phuong-an-xu-ly-ton-kho",
            "Thiết kế phương án xử lý tồn kho có kiểm soát",
            "Kế hoạch hành động",
            "5 phút đọc",
            "Một khuôn khổ để đánh giá phương án xử lý danh mục dựa trên bằng chứng, trách nhiệm phê duyệt và tiêu chí theo dõi.",
            [
                "Sau khi nhận diện SKU cần chú ý, đội ngũ nên xác nhận nguyên nhân vận hành trước khi chọn phương án như theo dõi thêm, kết hợp bán hàng hoặc điều chỉnh giá.",
                "Mỗi phương án cần có người phụ trách, thời hạn đánh giá lại và tiêu chí theo dõi để đảm bảo có thể kiểm tra kết quả thực hiện.",
                "Mô hình chỉ hỗ trợ sắp xếp thông tin và gợi ý hướng xem xét; quyết định thương mại thuộc về đội ngũ có thẩm quyền.",
            ],
            [
                "Đánh giá nguyên nhân trước khi chọn phương án xử lý.",
                "Ghi nhận người phụ trách, thời hạn và tiêu chí theo dõi.",
                "Duy trì cơ chế phê duyệt trước khi triển khai thay đổi thương mại.",
            ],
        ),
        "chi-phi-nam-giu-hang-ton-kho": _article(
            "post-4",
            "chi-phi-nam-giu-hang-ton-kho",
            "Xác định chi phí nắm giữ hàng tồn kho",
            "Tài chính tồn kho",
            "4 phút đọc",
            "Các thành phần chi phí cần được xem xét khi đánh giá tác động tài chính của hàng tồn kho chậm luân chuyển.",
            [
                "Chi phí nắm giữ hàng tồn kho có thể bao gồm chi phí vốn, lưu kho, bảo quản, rủi ro giảm giá trị và chi phí cơ hội.",
                "Phương pháp tính cần phù hợp với dữ liệu và chính sách kế toán của doanh nghiệp; hệ thống phân tích không thay thế cho hạch toán tài chính.",
                "Đặt các chi phí này cạnh giá trị tồn và tốc độ bán giúp đội ngũ xác định khu vực cần được trao đổi trong kế hoạch vận hành.",
            ],
            [
                "Xác định rõ thành phần chi phí và nguồn dữ liệu sử dụng.",
                "Phân biệt chỉ số hỗ trợ quyết định với số liệu hạch toán chính thức.",
                "Đánh giá chi phí cùng rủi ro bán chậm và giá trị vốn liên quan.",
            ],
        ),
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_list_api(request):
    """Return concise professional learning material for the public knowledge library."""
    posts = []
    for article in _articles().values():
        posts.append({key: article[key] for key in ('id', 'slug', 'title', 'category', 'date', 'read_time', 'summary')})
    return Response({"posts": posts}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_detail_api(request, slug):
    """Return one knowledge-library article; unknown slugs use the first article as a safe fallback."""
    articles = _articles()
    post = articles.get(slug) or next(iter(articles.values()))
    return Response(post, status=status.HTTP_200_OK)
