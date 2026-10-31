# Kiểm thử tải

Các kịch bản trong thư mục này chỉ được chạy với môi trường cô lập, dữ liệu giả lập và cửa sổ kiểm thử đã được phê duyệt. Không chạy tải lên `localhost` bằng SQLite để kết luận về năng lực production; cũng không chạy lên production.

## Phân biệt hai mục tiêu

- **10.000 tài khoản đăng ký** là quy mô dữ liệu identity. Nó không chứng minh hệ thống có thể phục vụ 10.000 người đang hoạt động cùng lúc.
- **10.000 người dùng đồng thời** là 10.000 phiên có token riêng và cùng thực hiện luồng nghiệp vụ. Đây là mục tiêu của `k6_10k_concurrent_read.js`.
- **Thông lượng API** là số request mỗi giây. Với ba API đọc mỗi khoảng 30 giây, profile 10.000 người dùng tạo xấp xỉ 1.000 request/giây khi hệ thống đã ổn định; số thực tế phụ thuộc vào độ trễ.

## Điều kiện bắt buộc

1. Dùng môi trường staging tách biệt: MySQL/PostgreSQL production-like, Redis, Celery worker, reverse proxy và Prometheus/Grafana. Không dùng SQLite, Django `runserver` hoặc Odoo production.
2. Tạo 10.000 tài khoản thử nghiệm đang hoạt động, phân bổ trên nhiều workspace giống cơ cấu merchant dự kiến. Cấp token ngắn hạn cho từng tài khoản qua kênh bảo mật.
3. Lưu token ngoài Git, ví dụ `/secure/supplyforge-load/tokens-10000.json`. File là JSON array gồm chuỗi token hoặc object `{ "access_token": "..." }`.
4. Cô lập dữ liệu và khóa các tác vụ định kỳ không liên quan. Không chạy import, đồng bộ ERP hay export hàng loạt trong bài tải đọc.
5. Bật dashboard theo dõi CPU, memory, DB connection pool, slow query, Redis memory/evictions, Celery queue, HTTP p95/p99, tỷ lệ 401/429/5xx và business metrics.

## Cài k6

Theo tài liệu chính thức của Grafana k6 dành cho hệ điều hành đang dùng. Kiểm tra:

```bash
k6 version
```

## Chạy smoke trước

`k6_business_read_flow.js` xác nhận luồng đọc với một tài khoản và mức request nhỏ. Nó không đại diện cho 10.000 người dùng.

```bash
cd ops/loadtest
BASE_URL=http://127.0.0.1:8080 \
SF_EMAIL='load-test@example.test' \
SF_PASSWORD='temporary-password' \
TARGET_RPS=20 \
k6 run k6_business_read_flow.js
```

Chỉ sau khi smoke pass và observability hoạt động, mới chạy profile concurrent.

## Chạy 10.000 người dùng đồng thời

```bash
cd ops/loadtest
BASE_URL=https://staging.example.test \
ALLOW_NON_LOCAL=true \
ALLOW_LARGE_TEST=true \
VUS=10000 \
TOKEN_FILE=/secure/supplyforge-load/tokens-10000.json \
REQUIRE_UNIQUE_TOKENS=true \
THINK_TIME_SECONDS=30 \
k6 run --summary-export=artifacts/k6-10k-summary.json k6_10k_concurrent_read.js
```

`REQUIRE_UNIQUE_TOKENS=true` là mặc định. Nếu token không đủ 10.000, script dừng ngay, vì không được gọi kết quả là “10.000 người dùng”. `REQUIRE_UNIQUE_TOKENS=false` chỉ hợp lệ khi đo giới hạn phiên đồng thời bằng một nhóm tài khoản nhỏ và phải ghi rõ trong báo cáo.

## Tiêu chí đạt và điểm dừng

- Tỷ lệ request lỗi dưới 1%; không có lỗi phân quyền chéo tenant hoặc lỗi dữ liệu.
- HTTP p95 dưới 800 ms, p99 dưới 1.500 ms ở ba endpoint đọc; các ngưỡng này đã được khai báo trong script.
- Không tăng dần connection pool, memory, độ sâu queue hay độ trễ DB trong 15 phút giữ tải.
- Dừng bài test nếu 5xx trên 2% trong 2 phút, Redis eviction tăng, DB connection bị cạn hoặc dữ liệu tenant bị ảnh hưởng.
- Lưu file summary, dashboard Grafana, phiên bản ứng dụng, commit, cấu hình VU/think-time và thời gian chạy cùng báo cáo. Một lần pass không đủ để kết luận capacity; chạy lại sau thay đổi lớn và ở ít nhất hai thời điểm.

## Phạm vi không đo bởi bài này

Script chỉ đo hành vi đọc của người dùng đã đăng nhập. Import CSV, đồng bộ Odoo/SAP/WMS, mapping SKU, cập nhật kế hoạch xử lý và export có đặc tính write/worker khác; chúng cần bài tải tách riêng với idempotency check, quota theo tenant và dữ liệu disposable.
