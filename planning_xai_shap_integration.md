# Kế hoạch phát triển: Tích hợp Giải thích Mô hình xAI SHAP vào SupplyForge AI

Tài liệu này đã được tinh chỉnh và hoàn thiện dựa trên phản hồi chiến lược để chuyển đổi hệ thống phân tích từ Rule-based sang mô hình Machine Learning giải thích được bằng **SHAP (SHapley Additive exPlanations)**.

---

## 1. Định hướng Thiết kế & Giải pháp Chiến lược

### 1.1 Chiến lược Mô hình: Hybrid Model (Kết hợp)
Hệ thống sẽ áp dụng cách tiếp cận lai để giải quyết bài toán dữ liệu lạnh (Cold Start) của các cửa hàng mới:
- **Giai đoạn Onboarding (Cold Start - Global Model)**: Khi một shop mới đăng ký, hệ thống sử dụng một mô hình toàn cục (Global Model) được huấn luyện sẵn trên tập dữ liệu thương mại điện tử lớn chuẩn ngành để dự đoán rủi ro cơ sở.
- **Giai đoạn Trưởng thành (Shop-specific Model)**: Khi shop tích lũy đủ dữ liệu lịch sử (từ 6-12 tháng, tối thiểu hàng chục ngàn dòng giao dịch), hệ thống tự động kích hoạt quá trình fine-tuning cục bộ để tạo ra mô hình riêng biệt (Shop-specific Model) phản ánh đúng đặc thù kinh doanh riêng của họ.

### 1.2 Trực quan hóa Giao diện: Waterfall Plot (Biểu đồ Thác nước)
Chúng ta chọn biểu đồ thác nước **Waterfall Plot** làm cấu trúc UI/UX chủ đạo:
- **Ưu điểm**: Đọc tuần tự từ trên xuống dưới theo từng bậc thang đóng góp, giúp người dùng phổ thông (CFO, thủ kho) hiểu rõ quá trình suy luận của AI:
  `Tỉ lệ rủi ro trung bình (35%) -> Tăng 28% do lưu kho quá 90 ngày -> Giảm 10% do đang chạy khuyến mãi -> Kết quả: 53%`.
- **Thiết kế**: Vẽ hoàn toàn bằng SVG động trên Angular, cho phép tùy biến màu sắc (đỏ neon cho tăng rủi ro, xanh ngọc cho giảm rủi ro), hiệu ứng hover mượt mà và tooltip chi tiết.

---

## 2. Các điểm Cải tiến Kỹ thuật (Backend & API)

- **Human-Readable Feature Mapping (Trình thông dịch thuộc tính)**:
  - Backend sẽ duy trì một Dictionary ánh xạ các biến đã mã hóa (ví dụ: `category_fmcg`, `price_ratio`) thành chuỗi tiếng Việt dễ hiểu (`Ngành hàng: Tiêu dùng nhanh`, `Tỉ lệ Giá bán / Giá vốn`) trước khi gửi JSON về frontend.
- **Model Versioning (Quản lý phiên bản mô hình)**:
  - Bổ sung trường `model_version` (ví dụ: `v1.2.0-global` hoặc `v2.0.1-shop15`) trong API response để phục vụ việc debug khi người dùng báo cáo AI dự báo lệch.
- **Tối giản hóa API Payload**:
  - Loại bỏ trường `impact` dư thừa. Frontend sẽ tự dựa vào dấu của `shap_value` (dương để tô màu đỏ tăng rủi ro, âm để tô màu xanh giảm rủi ro).

---

## 3. Kiến trúc Luồng Dữ liệu (Data Flow)

```
[Onboarding Shop] ---> Global Pre-trained Model ──┐
                                                  ├──> [SHAP Explainer] ---> [Feature Translation] ---> [Minimal JSON API] ---> [Angular SVG Waterfall Plot]
[Mature Shop]     ---> Shop-specific Fine-tuned   ┘
```

---

## 4. Danh sách nhiệm vụ cụ thể (Vertical Task Slicing)

### Giai đoạn 1: Xây dựng Core Machine Learning & SHAP (Backend)

#### Task 1: Huấn luyện & Đóng gói Hybrid Model Pipeline
- **Mô tả**: Xây dựng module huấn luyện, hỗ trợ cả nạp mô hình toàn cục (Global Model `.pkl`) và cơ chế Fine-tuning cục bộ khi dữ liệu đạt ngưỡng.
- **Tiêu chí nghiệm thu**:
  - Class ML Helper có thể nạp mô hình phù hợp tùy theo cấu hình tài khoản (Onboarding vs Mature).
  - Trả về xác suất rủi ro dự đoán (0.0 đến 1.0) kèm theo số phiên bản mô hình `model_version`.
- **Tệp tin ảnh hưởng**:
  - `backend/supplyforge/services/ml_model.py` (NEW)
  - `backend/tests/test_ml_model.py` (NEW)

#### Task 2: Tính toán SHAP Values & Dịch tên thuộc tính (Feature Mapping)
- **Mô tả**: Sử dụng `shap.TreeExplainer` tính toán SHAP values. Chạy qua Dictionary Translator để dịch các tên cột mã hóa sang ngôn ngữ tự nhiên.
- **Tiêu chí nghiệm thu**:
  - Đầu ra được dịch sạch sẽ: `[ { "feature_name": "Thời gian lưu kho", "feature_value": "95 ngày", "shap_value": 0.28 } ]`.
- **Tệp tin ảnh hưởng**:
  - `backend/supplyforge/services/shap_service.py` (NEW)

---

### Giai đoạn 2: Phát triển API Endpoints

#### Task 3: Xây dựng API Endpoint `/api/v1/workspaces/<id>/sku/<sku_id>/xai`
- **Mô tả**: API endpoint tối giản hóa trả về dữ liệu thô phục vụ vẽ biểu đồ thác nước và quản lý phiên bản.
- **Tiêu chí nghiệm thu**:
  - API trả về JSON định dạng tối giản:
    ```json
    {
      "risk_probability": 0.72,
      "base_value": 0.35,
      "model_version": "v1.2.0-global",
      "shap_contributions": [
        {"feature_name": "Số ngày lưu kho", "feature_value": "95 ngày", "shap_value": 0.28},
        {"feature_name": "Tốc độ bán hàng tuần tự", "feature_value": "0.15", "shap_value": -0.10}
      ]
    }
    ```
- **Tệp tin ảnh hưởng**:
  - `backend/supplyforge/urls.py`
  - `backend/supplyforge/views/xai.py` (NEW)

---

### Giai đoạn 3: Phát triển Giao diện Tương tác SHAP (Frontend)

#### Task 4: Tạo Component Biểu đồ Waterfall SVG
- **Mô tả**: Tạo component Angular `shap-waterfall` vẽ biểu đồ thác nước SVG. 
- **Tiêu chí nghiệm thu**:
  - Trực quan hóa bậc thang từ `base_value` cộng dồn các `shap_value` đến `risk_probability`.
  - Tự động tô màu đỏ nếu `shap_value > 0` và màu xanh dương/ngọc nếu `shap_value < 0`.
- **Tệp tin ảnh hưởng**:
  - `frontend/src/app/shap-waterfall/shap-waterfall.component.ts` (NEW)
  - `frontend/src/app/shap-waterfall/shap-waterfall.component.html` (NEW)
  - `frontend/src/app/shap-waterfall/shap-waterfall.component.css` (NEW)

#### Task 5: Nhúng Giải thích xAI vào màn hình Recovery Copilot
- **Mô tả**: Nhúng biểu đồ thác nước vào Sidebar của Recovery Copilot để hỗ trợ CFO/Thủ kho đưa ra quyết định thanh lý tối ưu.
- **Tệp tin ảnh hưởng**:
  - `frontend/src/app/recovery-copilot/recovery-copilot.component.html`
  - `frontend/src/app/recovery-copilot/recovery-copilot.component.ts`

---

## 5. Rủi ro & Giải pháp giảm thiểu (Risks & Mitigations)

| Rủi ro | Mức độ | Giải pháp |
|---|---|---|
| Mất cân bằng nhãn (Imbalanced Data) khi fine-tune mô hình ở shop ít sản phẩm lỗi | **Trung bình** | Sử dụng kỹ thuật SMOTE hoặc Class Weighting khi huấn luyện mô hình cục bộ. |
| Độ trễ khi vẽ SVG động nếu mảng SHAP values quá nhiều dòng | **Thấp** | Chỉ lấy Top 5 thuộc tính có tác động lớn nhất (dựa trên trị tuyệt đối của `shap_value`), gom các thuộc tính còn lại vào nhóm "Khác". |
