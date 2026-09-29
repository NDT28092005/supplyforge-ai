# SupplyForge AI — Database Migration Policy (Backward Compatibility)

Dài hạn & Sản xuất (Production Zero-Downtime Deployment Policy).

---

## 1. Chuẩn hóa Quy trình Migration

Khi phát triển tính năng mới có sự thay đổi mô hình dữ liệu (Django ORM Models):

```bash
# 1. Kiểm tra trạng thái migrations hiện tại
python manage.py showmigrations

# 2. Tạo file migration mới dựa trên sự thay đổi của model
python manage.py makemigrations

# 3. Xem trước câu lệnh SQL sẽ được thực thi trên DB
python manage.py sqlmigrate supplyforge <migration_number>

# 4. Áp dụng migration vào cơ sở dữ liệu
python manage.py migrate
```

---

## 2. Nguyên tắc Backward Compatibility (Tương thích Ngược trong Production)

Trong môi trường Production với chiến lược phát hành cuốn chiếu (Rolling Releases hoặc Blue/Green Deployment), **tất cả các file database migration phải đảm bảo tương thích ngược** với phiên bản mã nguồn cũ đang chạy đồng thời.

### ❌ Những thao tác CẤM thực hiện trực tiếp trong 1 release:
1. **`DROP COLUMN old_field`**: Xóa cột đang được phiên bản cũ đọc/ghi.
2. **`RENAME COLUMN old_field TO new_field`**: Đổi tên cột làm gãy các SQL query từ các API pod chưa reload.
3. **`ADD COLUMN new_field NOT NULL` (không có `default`)**: Gây lỗi INSERT từ phiên bản ứng dụng cũ.
4. **`DROP TABLE table_name`**: Xóa bảng khi ứng dụng cũ chưa ngừng truy cập.

---

## 3. Mô hình Phấn tách 3 Giai đoạn (Expand & Contract Pattern)

Để thay đổi hoặc loại bỏ một trường/bảng dữ liệu, quy trình phải trải qua **3 Releases**:

- **Release N (EXPAND)**: Thêm cột mới `new_field` (`null=True` hoặc có `default`). Vẫn giữ nguyên `old_field`.
- **Release N+1 (MIGRATE & DUAL-WRITE)**: Chuyển code sang dùng `new_field`. Backfill dữ liệu từ `old_field` sang `new_field`.
- **Release N+2 (CONTRACT & CLEANUP)**: Xóa `old_field` an toàn sau khi 100% ứng dụng chạy trên Release N+1.
