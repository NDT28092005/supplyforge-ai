# Kế hoạch Triển khai Tổng thể & Lộ trình Kỹ thuật (Master Implementation Plan & Technical Roadmap)
**Dự án:** SupplyForge AI 2.0 — Hệ thống hỗ trợ quyết định có khả năng giải thích (xAI) ứng dụng Machine Learning & SHAP trong tối ưu hóa chuỗi cung ứng Thương mại Điện tử.  
**Tác giả:** Senior Technical Product Manager & Lead AI Architect

---

## 1. Executive Summary & Product Vision

### 1.1. Bối cảnh & Định vị Nền tảng
Trong thị trường bán lẻ thương mại điện tử (E-commerce) đa kênh (Shopee, Lazada, TikTok Shop) liên kết hệ thống ERP doanh nghiệp (Odoo), các hệ thống quản trị tồn kho truyền thống dựa trên quy luật tĩnh (Rule-based) đã bộc lộ những hạn chế nghiêm trọng. Chúng không thể thích ứng với tính chu kỳ ngắn, biến động giá bán, các chiến dịch khuyến mại (Flash Sale), hay hành vi hoàn hàng phức tạp của người tiêu dùng.

**SupplyForge AI 2.0** được thiết kế để chuyển dịch từ một công cụ quản lý thụ động thành một **Nền tảng Tình báo Bán lẻ (Retail Intelligence Platform)** chủ động. Nền tảng kết nối chặt chẽ giữa khả năng dự báo khoa học và hành động thực tế tại hiện trường thông qua 3 chân kiềng chiến lược:

```
                  ┌──────────────────────────────────────────────┐
                  │              SUPPLYFORGE AI 2.0              │
                  └──────────────────────┬───────────────────────┘
         ┌───────────────────────────────┼───────────────────────────────┐
         ▼                               ▼                               ▼
┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│   Tối ưu hóa     │           │ Quản lý Tác vụ   │           │ Giải thích Rủi ro│
│   Tồn kho (ML)   │           │ Vận hành (Tasks) │           │    bằng xAI      │
└──────────────────┘           └──────────────────┘           └──────────────────┘
```

1. **Tối ưu hóa tồn kho (Inventory Optimization):** Áp dụng mô hình học máy (Machine Learning) để dự báo nhu cầu (Demand Forecasting) và cảnh báo nguy cơ đứt hàng (Stockout) hoặc đọng vốn (Overstock) ở quy mô hàng chục ngàn SKU.
2. **Quản lý tác vụ vận hành (Operational Task Management):** Chuyển hóa các phân tích AI tĩnh thành các thẻ tác vụ (Actionable Task Cards) được giao trực tiếp cho nhân viên kho, tạo luồng xử lý khép kín.
3. **Giải thích rủi ro bằng trí tuệ nhân tạo (xAI):** Phá vỡ giới hạn "hộp đen" của AI. Giúp CFO và Quản lý vận hành hiểu rõ **LÝ DO** (qua biểu đồ thác nước SHAP) đằng sau xác suất rủi ro của từng SKU để đưa ra quyết định tài chính tự tin (ví dụ: xả hàng kích hoạt lá chắn thuế).

---

## 2. System Architecture & Data Flow

Hệ thống tuân thủ mô hình **Kiến trúc phân rã hoàn toàn (Decoupled Architecture)** nhằm đảm bảo tính cô lập của tài nguyên tính toán AI, tối ưu hóa băng thông CSDL chính và khả năng mở rộng độc lập.

### 2.1. Cấu trúc Mô-đun Hệ thống (Decoupled Architecture)

* **Frontend Layer (Angular):** Client Single Page Application (SPA), hoạt động theo cơ chế Component-based. Tận dụng tối đa SVG động (Dynamic SVG) tự vẽ trên client để đảm bảo tốc độ hiển thị và hiệu ứng mượt mà khi trực quan hóa SHAP Waterfall.
* **Core Backend (Django + MySQL):** Chịu trách nhiệm quản lý phiên làm việc, phân quyền (Authentication), đồng bộ dữ liệu giao dịch từ Shopee/Odoo, quản lý vòng đời tác vụ vận hành (Tasks) và thực thi logic nghiệp vụ lõi.
* **AI Microservice (FastAPI + Redis):** Dịch vụ tính toán độc lập viết bằng FastAPI (Python). FastAPI tải sẵn các mô hình LightGBM/XGBoost vào bộ nhớ và thực hiện dự đoán rủi ro + tính toán SHAP values thông qua các luồng bất tuần tự (Asynchronous endpoints). Sử dụng Redis làm tầng đệm Cache (24 giờ) cho các payload dự báo tĩnh của SKU.

### 2.2. Biểu đồ Luồng dữ liệu (Data Flow)

```
[ Shopee / TikTok Webhooks ]
[    Odoo ERP Sync APIs    ]
             │
             ▼
┌──────────────────────────┐
│   Core Django Backend    │ <─── Sync Jobs (Celery / Redis)
└────────────┬─────────────┘
             │ Writes to
             ▼
┌──────────────────────────┐      JSON       ┌──────────────────────────┐
│      MySQL Database      │ ──────────────> │    FastAPI AI Service    │
└──────────────────────────┘  Feature ETL    └────────────┬─────────────┘
                                                          │ Calculates ML & SHAP
                                                          ▼
┌──────────────────────────┐    Minimal JSON   ┌──────────────────────────┐
│   Angular SVG Client     │ <──────────────── │   xAI API Response Port  │
└──────────────────────────┘   Waterfall UI    └──────────────────────────┘
```

---

## 3. Data Engineering & Feature Strategy

Dữ liệu thô từ sàn TMĐT và ERP chứa rất nhiều nhiễu, dữ liệu khuyết thiếu và chuỗi SKU thô không đồng nhất. Dưới đây là chiến lược tiền xử lý bắt buộc:

### 3.1. Xử lý nhu cầu ngắt quãng (Intermittent Demand & Daily Time Resolution)
Các SKU bán chậm thường có doanh số ngắt quãng (ví dụ: cả tuần không có đơn, chỉ có đơn vào thứ 7). Nếu trực tiếp tính toán rolling features trên chuỗi dữ liệu thô này, mô hình sẽ tính toán sai lệch tốc độ tiêu thụ.
* **Chiến lược xử lý:**
  1. Xây dựng ma trận lịch (Calendar Matrix) ở mức độ **Hàng ngày (Daily)** cho mỗi SKU hoạt động.
  2. Thực hiện kỹ thuật **Fill Missing Dates:** Tự động chèn các bản ghi ngày còn thiếu với số lượng đơn hàng và số lượng bán bằng `0.0`.
  3. Sau khi điền khuyết chuỗi thời gian liên tục, tiến hành áp dụng các hàm cửa sổ trượt (Rolling windows) để tính các đặc trưng dịch chuyển trung bình động (`7d`, `14d`, `30d`).

### 3.2. Chuẩn hóa thuộc tính SKU thông qua RegEx (Bóc tách đặc trưng vật lý)
Để giải quyết bài toán khởi động lạnh (Cold Start) khi một SKU mới tinh được tạo ra (chưa có lịch sử bán hàng), mô hình cần học được từ các thuộc tính vật lý của sản phẩm. Chuỗi tên SKU thô dạng text cần được chuẩn hóa bằng các mẫu RegEx (Regular Expressions) thành các cột số/phân loại sạch:
* **Mẫu Regex bóc tách:**
  * **Size:** Trích xuất từ các ký tự `S`, `M`, `L`, `XL`, `XXL` hoặc chỉ số size số `(29|30|31|32)`.
  * **Type (Dạng/Loại):** Bóc tách các từ khóa như `áo thun`, `quần tây`, `sữa bột`, `hộp nhựa` để phân nhóm.
  * **Trọng lượng giới hạn (MinKG & MaxKG):** Đối với các sản phẩm đóng gói hoặc tã/sữa, dùng regex bóc tách chỉ số kg như `(9-14kg)` thành cột `min_kg = 9.0`, `max_kg = 14.0`.
  * **Pack (Quy cách đóng gói):** Trích xuất các cụm `combo 3`, `hộp x6`, `set 2` thành cột `pack_size = 3`, `pack_size = 6`.

### 3.3. Đặc trưng phân cấp (Hierarchical Features)
Khi một sản phẩm có dữ liệu quá thưa thớt, mô hình sẽ tận dụng thông tin tổng hợp của cấp cha (Parent node) trong cấu trúc cây sản phẩm:
* Tính toán tổng doanh số, tốc độ tăng trưởng, và chỉ số xu hướng (Trend) ở cấp độ **Thương hiệu (Brand)** và **Danh mục (Category)**.
* Gán các giá trị phân cấp này vào đặc trưng của SKU tương ứng để gánh dự báo cho các SKU bị thiếu dữ liệu lịch sử.

### 3.4. Metadata nghiệp vụ mở rộng (Business Metadata Expansion)
Tận dụng các thuộc tính phi logic chuỗi cung ứng thông thường để giải quyết các bài toán biên có giá trị kinh tế lớn:
* **Voucher & Discount:** Tính toán biên độ ưu đãi để xây dựng bài toán **Promotion Effectiveness** (Đo lường độ nhạy cảm của khách hàng với khuyến mại).
* **Shipping Fee & Delivery Partner:** Tổng hợp phí ship thực tế và đơn vị vận chuyển (Giao Hàng Nhanh, Viettel Post, Shopee Express) nhằm dự báo rủi ro hoàn hàng (**Return Risk**), đặc biệt cho các vùng sâu vùng xa hoặc phương thức COD.

---

## 4. Core Machine Learning & XAI Strategy

### 4.1. Chiến lược mô hình & Quá trình huấn luyện
Hệ thống sử dụng phương pháp huấn luyện gia tăng và lựa chọn mô hình theo độ phức tạp tăng dần:

```
[ Baseline: Linear Regression ] ──> [ Random Forest Classifier ] ──> [ LightGBM (Tweedie/Poisson) ]
```

* **LightGBM** được lựa chọn làm mô hình sản xuất chính vì khả năng huấn luyện thần tốc, hỗ trợ tốt cho dữ liệu dạng bảng có kích thước lớn và hỗ trợ trực tiếp việc xử lý các giá trị NaN.

### 4.2. Hàm mục tiêu tối ưu hóa (Objective Function)
Vì dữ liệu bán hàng (đặc biệt là bán lẻ TMĐT) là dữ liệu đếm (Count data - số lượng sản phẩm bán ra là số nguyên dương $\ge 0$) và bị phân phối thưa thớt cực đại (Zero-inflation), việc dùng hàm loss bình phương tối thiểu thông thường (MSE) sẽ dẫn đến dự báo bị lệch nghiêm trọng.
* **Giải pháp:** Sử dụng hàm mục tiêu **Poisson Loss** hoặc **Tweedie Loss** trong LightGBM. Tweedie Loss cho phép tự điều chỉnh phân phối trung gian giữa Poisson và Gamma, cực kỳ mạnh mẽ trong việc mô hình hóa các chuỗi bán hàng chứa nhiều giá trị `0`.

### 4.3. Chỉ số đánh giá (Evaluation Metric) & Error Analysis
* ** MAPE (Mean Absolute Percentage Error) bị loại bỏ hoàn toàn** vì gặp lỗi chia cho $0$ khi ngày không có đơn và phạt quá nặng các sai lệch nhỏ của các SKU bán chậm.
* **Thay thế bằng WMAPE (Weighted Mean Absolute Percentage Error):**
  $$\text{WMAPE} = \frac{\sum_{i=1}^{n} |y_i - \hat{y}_i|}{\sum_{i=1}^{n} y_i}$$
  WMAPE triệt tiêu lỗi chia cho $0$ và đánh trọng số lỗi theo quy mô doanh số. Một SKU chủ lực (doanh số lớn) bị dự báo sai sẽ làm WMAPE tăng cao hơn nhiều so với một SKU ngách bán chậm.
* **Error Analysis Tagging:** Hệ thống tự động phân loại và gắn tag lỗi dự báo sai lệch lớn: `FLASH_SALE_OUTLIER` (dự báo lệch do có flash sale đột xuất), `STOCKOUT_BIAS` (lệch do sản phẩm bị hết hàng ở hiện trường làm đứt chuỗi bán thực tế).

### 4.4. Phòng chống rò rỉ dữ liệu (Data Leakage Prevention)
Tuyệt đối không sử dụng cơ chế chia ngẫu nhiên (Random Train/Test Split) vì dữ liệu chuỗi thời gian có tính phụ thuộc thời gian (Temporal dependency). Việc dùng Random Split sẽ làm rò rỉ thông tin tương lai về quá khứ.
* **Giải pháp:** Áp dụng **Time-series Split** (Walk-forward Validation) với mốc thời gian cố định. Ví dụ: Dùng dữ liệu trước ngày `2026-07-01` làm tập Train, và dữ liệu từ `2026-07-01` đến nay làm tập Validation.

### 4.5. Giải thích mô hình bằng SHAP (xAI)
* **Backend:**
  * Sử dụng `shap.TreeExplainer` để khai thác trực tiếp cấu trúc cây của LightGBM/XGBoost, rút ngắn thời gian tính toán SHAP values xuống mức milliseconds.
  * Tích hợp lớp **Human-Readable Feature Mapping** dịch các biến mã hóa một chiều (One-hot encoded) hoặc biến kỹ thuật thành từ ngữ tự nhiên. Ví dụ: `inventory_coverage_days <= 7` được ánh xạ thành `"Lượng hàng trong kho chỉ đủ bán dưới 7 ngày"`.
  * API Endpoint trả về cấu trúc JSON tối giản:
    ```json
    {
      "risk_probability": 0.88,
      "base_value": 0.35,
      "model_version": "v2.0.1-shop-12",
      "shap_contributions": [
        {"feature_name": "Thời gian lưu kho", "feature_value": "95 ngày", "shap_value": 0.35},
        {"feature_name": "Tốc độ bán hàng tuần", "feature_value": "+28%", "shap_value": 0.25},
        {"feature_name": "Nhà cung cấp giao chậm", "feature_value": "Tỷ lệ 18%", "shap_value": 0.10},
        {"feature_name": "Khuyến mại đang chạy", "feature_value": "Giảm 15%", "shap_value": -0.17}
      ]
    }
    ```
* **Frontend Angular UI:**
  * Tiếp nhận JSON thô và tự động vẽ **biểu đồ thác nước SVG động (Dynamic SVG Waterfall Plot)** trực tiếp trên DOM.
  * Chỉ hiển thị **Top 5 yếu tố có trị tuyệt đối SHAP lớn nhất**, gom tất cả các yếu tố còn lại vào nhóm `"Khác"` để tránh làm rối mắt người dùng.
  * Sử dụng màu **Đỏ Neon** biểu thị tác động làm tăng rủi ro đứt hàng/đọng vốn (`shap_value > 0`) và màu **Xanh Ngọc** cho yếu tố làm giảm rủi ro (`shap_value < 0`).

---

## 5. Operational Task Integration (Vòng lặp Phân tích - Vận hành)

Để các insight từ mô hình AI không bị "bỏ quên" trên Dashboard, SupplyForge AI tích hợp mô-đun **Quản lý tác vụ vận hành (Operational Task Management)**.

```
┌──────────────────┐      Vượt ngưỡng rủi ro      ┌──────────────────┐
│   FastAPI XAI    │ ───────────────────────────> │ Tạo Task tự động │
│  Prediction API  │                              │  (Django TaskDB) │
└──────────────────┘                              └────────┬─────────┘
                                                           │
                                                           ▼
┌──────────────────┐      Xác nhận hoàn tất       ┌──────────────────┐
│ Cập nhật CSDL    │ <─────────────────────────── │ Nhân viên kho    │
│  Tồn kho thực    │                              │ thực thi tác vụ  │
└──────────────────┘                              └──────────────────┘
```

* **Cơ chế kích hoạt (Trigger):** Khi `risk_probability` của một SKU vượt ngưỡng cấu hình (ví dụ: rủi ro đứt hàng $> 85\%$ hoặc rủi ro đọng vốn $> 80\%$), hệ thống Django Backend tự động khởi tạo một thẻ tác vụ trong cơ sở dữ liệu (`Task` model).
* **Các loại Tác vụ chuẩn hóa:**
  * **Tác vụ xả hàng (Liquidation Task):** Kích hoạt khi rủi ro đọng vốn vượt ngưỡng. Giao cho bộ phận Marketing/Bán hàng thiết lập chương trình giảm giá mô phỏng theo gợi ý của AI.
  * **Tác vụ tái đặt hàng (Reorder Task):** Kích hoạt khi rủi ro đứt hàng tăng cao. Tự động soạn thảo đơn nháp mua hàng gửi cho nhà cung cấp kèm số lượng khuyến nghị.
  * **Tác vụ kiểm kho đột xuất (Cycle Counting Task):** Kích hoạt khi phát hiện bất thường về dữ liệu tồn kho (outlier giá trị âm hoặc lệch lớn so với vận tốc bán thực tế). Giao cho nhân viên kho cầm máy quét mã vạch đi xác thực thực tế.
* **Đóng vòng lặp dữ liệu (Feedback Loop):** Khi nhân viên kho ấn "Xác nhận hoàn thành tác vụ" trên Angular Mobile UI, trạng thái tồn kho thực tế được cập nhật vào MySQL, tạo ra điểm dữ liệu huấn luyện mới (Labeled training data) chính xác hơn cho chu kỳ huấn luyện ML tiếp theo.

---

## 6. Phased Development Roadmap (8 Phases)

Lộ trình triển khai tổng thể được chia thành 8 Phase chặt chẽ nhằm kiểm soát rủi ro hệ thống và đảm bảo phân phối giá trị sản phẩm tăng dần theo thời gian.

### Phase 1: Business Understanding & Scope Definition
* **Đầu vào (Inputs):** Bản mô tả yêu cầu nghiệp vụ (Business Requirements), Cấu trúc dữ liệu kho Shopee/Odoo hiện tại.
* **Công việc thực hiện (Activities):** Xác định bài toán máy học (Phân loại đứt hàng vs Hồi quy dự báo doanh số); Xác định ngưỡng rủi ro tài chính của doanh nghiệp; Xây dựng ma trận ưu tiên Use-case.
* **Đầu ra (Deliverables):** Tài liệu đặc tả Use-case; Thiết kế API Contract chuẩn giữa Django, FastAPI và Angular; Chỉ số thành công KPI nghiệp vụ ($\text{WMAPE} < 15\%$).

### Phase 2: Data Understanding & Profiling
* **Đầu vào (Inputs):** Dữ liệu lịch sử thô `orders.csv` và `products.json` trong thư mục dữ liệu nghiên cứu khoa học.
* **Công việc thực hiện (Activities):** Chạy công cụ kiểm toán dữ liệu (Audit); Phân tích tỷ lệ khuyết thiếu (Null rate), dữ liệu trùng lặp (Duplicate) và ngoại lệ (Outliers); Phân tích tính mùa vụ và tính chu kỳ của đơn hàng bán lẻ.
* **Đầu ra (Deliverables):** Báo cáo kiểm định chất lượng dữ liệu (Data Quality Report); Báo cáo Phân tích Khám phá Dữ liệu (EDA Report); Danh mục đặc trưng thô sơ bộ (Feature Inventory).

### Phase 3: Data Engineering & Clean Master Dataset
* **Đầu vào (Inputs):** File SQL Database và tệp CSV giao dịch.
* **Công việc thực hiện (Activities):** Viết script ETL xử lý luồng ghi nhận dữ liệu lớn bằng chunking; Thực hiện Fill Missing Dates để giải quyết dữ liệu ngắt quãng; Làm sạch đơn hàng hoàn/huỷ.
* **Đầu ra (Deliverables):** Pipeline tích lũy dữ liệu hoạt động ổn định; Tệp dữ liệu sạch hợp nhất `master_dataset.csv` sẵn sàng cho việc trích xuất đặc trưng.

### Phase 4: Feature Store & Normalization Pipeline
* **Đầu vào (Inputs):** `master_dataset.csv`.
* **Công việc thực hiện (Activities):** Triển khai parser Regex để bóc tách Size, Type, Min/Max KG, Pack từ SKU; Xây dựng đặc trưng phân cấp cấp Brand/Category; Tạo các rolling features của lượng bán hàng ngày.
* **Đầu ra (Deliverables):** Mô-đun Feature Engineering hoàn thiện; Feature Store chứa khoảng $150$ đến $250$ đặc trưng được tối ưu hóa tốc độ truy vấn.

### Phase 5: Label Engineering & Training Set Creation
* **Đầu vào (Inputs):** Feature Store.
* **Công việc thực hiện (Activities):** Thiết lập logic gắn nhãn đứt hàng và đọng vốn động dựa trên số ngày hàng còn đáp ứng nhu cầu; Gắn nhãn các tác động ngoại cảnh (Flash sale, chiến dịch lễ hội).
* **Đầu ra (Deliverables):** Dataset huấn luyện được gán nhãn hoàn chỉnh (`training_dataset.csv`) được phân chia thành các tập Train/Test theo trục thời gian (Time-series split).

### Phase 6: Machine Learning Modeling & Tuning
* **Đầu vào (Inputs):** Tập dữ liệu huấn luyện và kiểm thử.
* **Công việc thực hiện (Activities):** Thiết lập baseline với Linear Regression; Huấn luyện Random Forest và LightGBM Regressor sử dụng hàm Poisson/Tweedie Loss; Thực hiện căn chỉnh siêu tham số (Hyperparameter tuning) qua Grid Search / Bayesian Optimization.
* **Đầu ra (Deliverables):** Tệp mô hình đóng gói `stockout_model.pkl`; Bảng đánh giá chỉ số WMAPE chi tiết và biểu đồ phân tích lỗi (Error Analysis).

### Phase 7: Explainable AI & API Integration
* **Đầu vào (Inputs):** `stockout_model.pkl` và FastAPI framework.
* **Công việc thực hiện (Activities):** Tích hợp `shap.TreeExplainer` vào FastAPI AI Microservice; Viết bộ dịch thuộc tính SHAP sang tiếng Việt; Thiết lập endpoint API trả về JSON tối giản; Triển khai component Angular SVG Waterfall tự vẽ.
* **Đầu ra (Deliverables):** API Endpoint `/xai` hoạt động với độ trễ thấp ($< 100\text{ms}$); Component Angular thác nước SVG vẽ đẹp, có hiệu ứng hover tooltip trực quan.

### Phase 8: AI Copilot & Operational Workflow Closing
* **Đầu vào (Inputs):** Endpoint dự báo rủi ro, SHAP values, Hệ thống Tasks Django, SDK Gemini.
* **Công việc thực hiện (Activities):** Nhúng bộ diễn giải ngôn ngữ tự nhiên sử dụng mô hình Gemini (hoặc Rule-based engine fallback) vào giao diện Angular; Cấu hình hệ thống tự sinh Task vận hành kho khi rủi ro vượt ngưỡng; Đóng vòng lặp phản hồi dữ liệu.
* **Đầu ra (Deliverables):** Sidebar Recovery Copilot hoàn chỉnh; Trình giả lập CFO tích hợp giải thích tự nhiên của AI; Hệ thống quản trị thẻ tác vụ vận hành kho chạy mượt mà, giúp tăng hiệu quả luân chuyển hàng hóa thực tế.
