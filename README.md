# SupplyForge AI — Supply Chain OS

**Supply Chain OS** dành cho các nhà bán lẻ thương mại điện tử (E-commerce) tại khu vực Đông Nam Á. Hệ thống giúp tối ưu hóa quản lý tồn kho, dòng tiền và SKU bằng trí tuệ nhân tạo (AI). Dự án đã được chuyển đổi toàn diện sang kiến trúc **Django (Python)** cho Backend, **AngularJS** cho Frontend, và **MySQL** cho Cơ sở dữ liệu.

---

## 🚀 Khả năng hiện tại của hệ thống:

1. **Nhập dữ liệu thông minh (Trust Theater):**
   - Hỗ trợ nhập dữ liệu dạng CSV cực lớn nhờ cơ chế đọc dòng-by-dòng (Streaming), tối ưu RAM (O(1) memory).
   - **AI Column Mapping:** Sử dụng Google Gemini API để tự động nhận diện và ánh xạ các cột dữ liệu từ file của người dùng sang chuẩn hệ thống.
2. **Quản lý SKU Tập trung (Tinder for SKUs):**
   - Tự động phát hiện các SKU bị trùng lặp bằng thuật toán khoảng cách Levenshtein và VietnameseNormalizer.
   - **Giao diện Vuốt (Tinder-style):** Cho phép người dùng gộp các SKU trùng lặp chỉ bằng một cú click đơn giản.
3. **Dashboard Phân tích Tồn kho chết (Dead Stock Analytics):**
   - Nhận diện các mặt hàng bán chậm không có biến động kho >45 ngày.
   - **Loss Aversion Framing:** Hiển thị số tiền bị "đóng băng" cùng ước tính thất thoát dòng tiền dưới dạng cảnh báo đỏ trực quan.
4. **Kiến trúc Đa Tenant (Multi-tenancy):**
   - Phân tách dữ liệu các shop qua `workspace_id`.
5. **AI Recovery Copilot & Clusters:**
   - Gom cụm thông minh các nhóm hàng bán chậm (Top 3 Recovery Clusters) và đưa ra gợi ý giải phóng hàng hóa CFO-grade.

---

## 1. Cơ cấu thư mục

```
supplyforge-ai/
├── backend/                 # Django Backend (DRF)
│   ├── manage.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── supplyforge_ai/      # Cấu hình chính dự án Django
│   └── core/                # Core application (Models, Views, Services)
├── frontend/                # AngularJS Frontend (SPA)
│   ├── index.html           # Single Page App entry (Tailwind CSS CDN)
│   ├── app.ts               # Định nghĩa app module & core controller
│   ├── tsconfig.json        # Cấu hình TypeScript
│   ├── package.json         # Danh sách thư viện & npm scripts
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── services/
│   │   └── apiService.ts    # Factory gọi REST API (TypeScript)
│   └── features/            # Các tính năng riêng lẻ (TypeScript + HTML)
├── docker-compose.yml
├── .env
└── README.md
```

---

## 2. Thiết lập cơ sở dữ liệu (MySQL)

Dữ liệu được lưu trữ trong MySQL. Django ORM quản lý schema; service
`migrate` chạy migrations một lần trước khi service web/worker khởi động.
Compose không tự seed tài khoản hoặc workspace mặc định.

---

## 3. Hướng dẫn chạy nhanh bằng Docker

Yêu cầu máy cài đặt Docker và Docker Compose.

```powershell
# 1. Sao chép biến môi trường
copy .env.example .env

# 2. Điền các secret bắt buộc trong .env rồi khởi chạy toàn bộ hệ thống
docker compose up --build
```

Sau khi các container khởi động hoàn tất, bạn có thể truy cập hệ thống tại:
- **Frontend SPA**: `http://localhost:3000`
- **Backend API status (Ping)**: `http://localhost:8080/api/v1/ping`
- **Liveness Probe**: `http://localhost:8080/health/live`
- **Readiness Probe**: `http://localhost:8080/health/ready`
- **API Version Info**: `http://localhost:8080/api/version`
- **Celery Worker Status**: `http://localhost:8080/api/v1/health/celery`

API clients should send the JWT as `Authorization: Bearer <token>`. Tenant
identity comes from the validated token; `workspaceId`, `workspace_id`, and
`userId` request fields are only consistency checks and cannot switch scope.
The synchronous profiling upload remains at `/api/v2/ingestion/upload`; the
background queue upload is `/api/v2/jobs/upload`.

### Các Container Services được tự động khởi tạo:
1. `frontend`: Single Page App (Angular JS/TS phục vụ bởi Nginx).
2. `backend`: REST API Server (Django / Gunicorn / Python 3.11).
3. `migrate`: Release step chạy Django migrations một lần.
4. `mysql`: Database Server (MySQL 8.0), chỉ truy cập trong network nội bộ.
5. `redis`: In-memory data store & Celery Broker (Redis 7), chỉ truy cập trong network nội bộ.
6. `celery_data`: Dedicated Worker cho xử lý dữ liệu và CSV Ingestion (`data_worker` queue).
7. `celery_ml`: Dedicated Worker cho mô hình ML & Risk Calibration (`ml_worker` queue).
8. `celery_decision`: Dedicated Worker cho Decision Engine & Action Planning (`decision_worker` queue).

---

## 3.1 Cấu hình Môi trường (Environment Foundation)

Hệ thống hỗ trợ 3 môi trường phát triển chính thông qua biến `APP_ENV`:

| Môi trường | File cấu hình | Mô tả |
| :--- | :--- | :--- |
| **development** | `backend/.env.development` | Môi trường phát triển cục bộ (Debug `True`, SQLite/MySQL local) |
| **staging** | `backend/.env.staging` | Môi trường kiểm thử staging (Template không commit secret thật) |
| **production** | `backend/.env.production` | Môi trường production chính thức (Template không commit secret thật) |

Khai báo mẫu mặc định được lưu ở `backend/.env.example` và `.env.example` tại thư mục gốc. Phiên bản hệ thống được định nghĩa tại file [VERSION](file:///home/nguyen-dai-tung/supplyforge-ai/VERSION).

Ở development/test, `STORAGE_BACKEND=local` dùng filesystem local. Staging và
production bắt buộc `STORAGE_BACKEND=s3` với bucket S3/MinIO-compatible được
cấu hình qua `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` và tùy chọn
`S3_ENDPOINT_URL`/`S3_REGION`. SQLite chỉ được phép ngoài staging/production;
test runner dùng database in-memory.

---

## 4. Chạy cục bộ cho phát triển (Local Development)

### Django Backend
1. Cài đặt Python 3.11+.
2. Vào thư mục `backend`, tạo môi trường ảo và cài đặt thư viện:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # Trên Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Đảm bảo MySQL cục bộ của bạn đang chạy và cấu hình kết nối khớp trong `.env`.
4. Tạo migrations và seed dữ liệu:
   ```bash
   python manage.py makemigrations core
   python manage.py migrate
   python manage.py seed_db
   ```
5. Chạy server phát triển (cổng 8080):
   ```bash
   python manage.py runserver 8080
   ```

### AngularJS Frontend
Ứng dụng frontend được viết bằng TypeScript và cần được biên dịch sang JavaScript trước khi chạy.
1. Cài đặt các thư viện hỗ trợ (TypeScript và AngularJS Types):
   ```bash
   cd frontend
   npm install
   ```
2. Biên dịch mã nguồn TypeScript:
   * Chạy biên dịch một lần:
     ```bash
     npm run build
     ```
   * Hoặc chạy ở chế độ tự động biên dịch lại khi thay đổi code (watch mode):
     ```bash
     npm run watch
     ```
3. Phục vụ web tĩnh: Sau khi biên dịch sinh ra các file `.js` trong các thư mục tương ứng, bạn có thể phục vụ thư mục `frontend/` thông qua local web server bất kỳ (ví dụ: Live Server của VS Code, hoặc Python HTTP server tại cổng 3000):
   ```bash
   python -m http.server 3000
   ```
4. Truy cập địa chỉ `http://localhost:3000` để trải nghiệm hệ thống.
