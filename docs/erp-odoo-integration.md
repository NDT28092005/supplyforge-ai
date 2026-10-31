# Odoo ERP Integration

## Phạm vi hiện tại

SupplyForge đọc dữ liệu từ Odoo theo một chiều. Tích hợp không tạo hoặc cập nhật chứng từ, sản phẩm, tồn kho hay khách hàng trong Odoo.

- Một connection chọn một company Odoo và một hoặc nhiều kho.
- Initial sync đọc tối đa 12 tháng dữ liệu danh mục, bán hàng, hàng trả, phiếu nhập và tồn khả dụng.
- Lượt đồng bộ gia tăng chạy mỗi 15 phút qua Celery Beat, với cửa sổ overlap 30 ngày để xử lý chứng từ bị sửa hoặc hủy.
- Customer PII không được đọc hoặc lưu. Webhook chỉ là tín hiệu ký HMAC để yêu cầu worker pull lại dữ liệu từ Odoo.
- Dữ liệu được lưu ở `IntegrationSkuDailyMetric`, tách khỏi luồng CSV hiện hữu. Đây là contract chuẩn để bổ sung SAP hoặc provider khác.

## Kích hoạt workspace

Quyền sử dụng được cấp nội bộ, độc lập với hệ thống billing:

```bash
cd backend
APP_ENV=development USE_SQLITE=1 SQLITE_PATH="$PWD/db.sqlite3" \
  .venv/bin/python manage.py migrate

APP_ENV=development USE_SQLITE=1 SQLITE_PATH="$PWD/db.sqlite3" \
  .venv/bin/python manage.py set_erp_entitlement <workspace_id> \
  --assigned-by operations@example.com
```

Thu hồi quyền:

```bash
.venv/bin/python manage.py set_erp_entitlement <workspace_id> --disable
```

## Quyền Odoo tối thiểu

Tạo một service account/API key riêng, chỉ có quyền đọc các model sau:

- `res.company`, `stock.warehouse`, `product.product`, `stock.quant`
- Một trong hai nguồn doanh số: `pos.order` và `pos.order.line`, hoặc `sale.order` và `sale.order.line`
- Tùy chọn cho inbound context: `stock.picking.type`, `stock.move`

Không cấp quyền ghi, quyền quản trị hệ thống, quyền CRM hoặc quyền đọc thông tin khách hàng nếu không cần thiết.

## Môi trường production

Credential được mã hóa Fernet. Production bắt buộc phải cấu hình một key riêng và danh sách đích Odoo có thể kết nối:

```bash
export INTEGRATION_CREDENTIAL_ENCRYPTION_KEY='base64-url-safe-fernet-key'
export INTEGRATION_ALLOWED_HOSTS='erp.example.com,odoo.customer.example'
```

`INTEGRATION_ALLOWED_HOSTS` là allowlist chính xác theo hostname. Production chỉ chấp nhận URL HTTPS. Odoo on-prem cần một endpoint HTTPS mà worker SupplyForge truy cập được; không mở quyền tới IP/nội bộ tùy ý.

## Chạy worker và scheduler

```bash
cd backend
celery -A config worker -l info
celery -A config beat -l info
```

Celery Beat gọi `supplyforge.tasks.enqueue_due_integration_syncs` mỗi 900 giây. Task loại trừ connection đang có lượt chạy `PENDING` hoặc `RUNNING`, nên không chồng lấn cùng một connection.

Hai file Docker Compose của repository đã khai báo `celery_beat`; chỉ cần cung cấp hai biến `INTEGRATION_CREDENTIAL_ENCRYPTION_KEY` và `INTEGRATION_ALLOWED_HOSTS` cho môi trường triển khai. Không cần Terraform để bật scheduler này.

## Theo dõi vận hành

Prometheus export các metric có label cardinality thấp, không chứa workspace, SKU hay dữ liệu khách hàng:

- `supplyforge_erp_sync_total{provider,run_type,status}` và `supplyforge_erp_sync_duration_seconds`
- `supplyforge_erp_source_records_total{provider,entity}`
- `supplyforge_erp_webhook_total{provider,status}`
- `supplyforge_business_erp_connections_total{status}`
- `supplyforge_business_erp_sync_age_seconds`
- `supplyforge_business_erp_unmapped_skus_total`

Cảnh báo khuyến nghị: sync age vượt 30 phút, có connection ở trạng thái `ERROR`, hoặc SKU chưa mapping tăng liên tục sau initial sync.

## Quy trình merchant

1. Vào **Nguồn dữ liệu ERP**, tạo connection Odoo với URL, database, service-account username và API key.
2. Chạy **Xác thực & đọc phạm vi**.
3. Chọn một company và các kho được phép theo dõi, sau đó lưu phạm vi.
4. Chạy **Nạp lịch sử 12 tháng**. Không chuyển sang dashboard rủi ro cho đến khi dữ liệu nguồn và mapping SKU đã được kiểm tra.
5. Xử lý các SKU cần mapping, theo dõi tồn theo kho và chạy **Đối soát tồn khả dụng** khi cần.

## Webhook tùy chọn

URL được trả về đúng một lần khi tạo connection:

```text
POST /api/v1/integrations/webhooks/{webhook_token}/
X-SupplyForge-Timestamp: 2026-10-30T14:00:00Z
X-SupplyForge-Signature: hex(hmac_sha256(secret, timestamp + "." + raw_body))
```

Body tối thiểu:

```json
{
  "event_id": "odoo-stock-1001-20261030T140000",
  "event_type": "stock.changed",
  "occurred_at": "2026-10-30T14:00:00Z",
  "payload": {"sku": "SKU-1001"}
}
```

Timestamp phải nằm trong 5 phút và `event_id` idempotent theo connection. Sau khi signature hợp lệ, SupplyForge tạo một lượt incremental pull; payload không được dùng để cập nhật giao dịch hay tồn kho trực tiếp.

## Kiểm thử

```bash
cd backend
TMPDIR=/tmp/supplyforge-mpl MPLCONFIGDIR=/tmp/supplyforge-mpl \
APP_ENV=development USE_SQLITE=1 SQLITE_PATH="$PWD/db.sqlite3" PYTHONPATH="$PWD/.." \
  .venv/bin/python manage.py test supplyforge.tests.test_erp_integration -v 2
```
