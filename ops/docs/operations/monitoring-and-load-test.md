# Giám sát và kiểm thử tải cục bộ

Tài liệu này dành cho môi trường phát triển hoặc staging cô lập. Không chạy
kịch bản tải trên Render, production, hay bất kỳ URL dùng chung nào. Quy trình
này không dùng Terraform và không tạo tài nguyên cloud.

## 1. Chỉ số cần theo dõi

Dashboard `SupplyForge - Vận hành rủi ro và quyết định` dùng dữ liệu đã được
lưu, không suy diễn từ log hay dữ liệu demo:

| Nhóm | Chỉ số | Ý nghĩa vận hành |
| --- | --- | --- |
| Dữ liệu | `supplyforge_business_snapshot_up`, active datasets, freshness, quality | Dataset nào đang là nguồn quyết định, collector có đọc được snapshot hay không và dữ liệu có còn đáng tin cậy hay không. |
| Rủi ro | `supplyforge_business_portfolio_skus{risk_class}` | Số SKU hiện tại ở bốn mức CRITICAL, HIGH_RISK, MEDIUM_RISK, LOW_RISK. |
| Vốn | `supplyforge_business_capital_exposure_vnd{metric}` | Giá trị tồn kho, vốn có trọng số rủi ro, vốn theo xác suất và chi phí cơ hội. |
| Hành động | `supplyforge_business_action_backlog_total{priority_tier}` | Khuyến nghị chưa xử lý theo P1-P4 trên dataset active. |
| Cảnh báo | `supplyforge_business_unread_notifications_total{severity}` | Thông báo nghiệp vụ chưa đọc theo mức độ. |
| Độ tin cậy hệ thống | failure rate, API latency, cache hit rate, queue depth/age | Xác nhận hệ thống vẫn đáp ứng được luồng ra quyết định. |

Các metric snapshot không gắn `workspace_id`, SKU, user, email hay request ID.
Khi có nhiều replica backend, dashboard dùng `max` cho snapshot danh mục để
không nhân đôi KPI cùng đọc từ một cơ sở dữ liệu.

## 2. Chạy monitoring

Khởi động backend trước trên `http://127.0.0.1:8080`. Với Docker Compose của
dự án, backend và các dependency được khởi động bằng stack chính. Nếu chạy
Django trực tiếp, dùng môi trường ảo và cấu hình môi trường phát triển của dự
án trước khi chạy `manage.py runserver 0.0.0.0:8080`.

Monitoring cần Docker Engine đang chạy và stack chính đã tạo network
`supplyforge-ai_default`:

```bash
export GRAFANA_ADMIN_PASSWORD='local-only-strong-password'
docker compose -f ops/monitoring/docker-compose.monitoring.yml up -d
```

Trên WSL2/Docker Desktop, nếu `curl http://127.0.0.1:9090/-/ready` bị treo
trong distro dù log Prometheus báo ready, publish cổng cho interface WSL rồi
recreate riêng Prometheus:

```bash
sudo env GRAFANA_ADMIN_PASSWORD='local-only-strong-password' \
  PROMETHEUS_BIND_ADDRESS=0.0.0.0 \
  docker compose -f ops/monitoring/docker-compose.monitoring.yml up -d --force-recreate prometheus
```

Chỉ dùng override này trên máy phát triển đáng tin cậy; không áp dụng cho host
công cộng. Windows Firewall hoặc firewall của host vẫn phải giới hạn cổng 9090.

MySQL exporter is optional and is not started by the default command. To
monitor MySQL, provision a read-only monitoring account and pass its DSN
without storing it in source control:

```bash
export MYSQL_EXPORTER_DSN='monitoring_user:password@(mysql:3306)/supplyforge'
docker compose --profile database -f ops/monitoring/docker-compose.monitoring.yml up -d
```

Mở các địa chỉ sau:

- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3001`
- Alertmanager: `http://127.0.0.1:9093`

Kiểm tra Prometheus tại `Status > Targets`. Target
`django-backend-local` phải `UP`; target simulator và MySQL exporter có thể
`DOWN` khi không sử dụng và không tạo cảnh báo target-down. Trong Grafana, chọn dashboard
`SupplyForge - Vận hành rủi ro và quyết định`.

Kiểm tra nhanh endpoint backend:

```bash
curl -fsS http://127.0.0.1:8080/metrics | rg 'supplyforge_business_(snapshot_up|portfolio_skus|capital_exposure_vnd)'
```

Nếu thay đổi YAML hoặc dashboard, restart riêng monitoring để nạp lại file:

```bash
docker compose -f ops/monitoring/docker-compose.monitoring.yml restart prometheus grafana
```

Không chạy lệnh Terraform trong quy trình này.

## 3. Nguồn metric demo

`ops/scripts/simulate_telemetry.py` chỉ phục vụ demo dashboard khi chưa có
backend hoặc dữ liệu thực. Nó chạy ở cổng `9108` và sử dụng đúng schema metric
của backend.

Không chạy simulator cùng backend thật trong một Prometheus, vì hai nguồn sẽ
biểu diễn hai trạng thái nghiệp vụ khác nhau. Khi demo, dừng backend thật hoặc
dùng một Prometheus cục bộ riêng; sau đó chạy:

```bash
python3 ops/scripts/simulate_telemetry.py
```

Kiểm tra metric demo tại `http://127.0.0.1:9108/metrics`. Dừng bằng `Ctrl+C`.
Simulator không sinh traffic người dùng, không nạp dữ liệu và không kiểm tra
năng lực chịu tải.

## 4. Kiểm thử tải luồng đọc

Kịch bản `ops/loadtest/k6_business_read_flow.js` không gọi endpoint ghi. Mỗi
iteration chỉ đọc:

- `/api/v2/query/dashboard-summary`
- `/api/v1/risk/assessments/list?limit=50&offset=0`
- `/api/v2/jobs/?active_only=true`

Cài `k6` trên máy kiểm thử, tạo một tài khoản test đã xác thực có dữ liệu của
riêng nó, rồi dùng access token hoặc thông tin đăng nhập. Script mặc định chỉ
nhận `localhost`/`127.0.0.1`; không thể vô tình gọi môi trường khác.

Ví dụ dùng token:

```bash
SF_TOKEN='access-token-cua-tai-khoan-test' \
TARGET_RPS=10 PREALLOCATED_VUS=20 MAX_VUS=80 \
k6 run ops/loadtest/k6_business_read_flow.js
```

Hoặc để k6 đăng nhập một lần trong `setup`:

```bash
SF_EMAIL='load-test@example.local' SF_PASSWORD='mat-khau-test' \
TARGET_RPS=10 PREALLOCATED_VUS=20 MAX_VUS=80 \
k6 run ops/loadtest/k6_business_read_flow.js
```

Để đưa số liệu k6 vào Prometheus cục bộ, khởi động monitoring với option
remote-write đã cấu hình rồi chạy:

```bash
SF_TOKEN='access-token-cua-tai-khoan-test' \
TARGET_RPS=10 PREALLOCATED_VUS=20 MAX_VUS=80 \
K6_OUT=experimental-prometheus-rw \
K6_PROMETHEUS_RW_SERVER_URL=http://127.0.0.1:9090/api/v1/write \
k6 run ops/loadtest/k6_business_read_flow.js
```

K6 sẽ tự fail nếu `http_req_failed >= 1%`, P95 >= 800 ms, P99 >= 1.5 s hoặc
check HTTP/JSON không đạt. `TARGET_RPS` là tổng arrival rate, không phải số
thread. Chỉnh `PREALLOCATED_VUS` và `MAX_VUS` đủ cao để k6 phát đủ RPS; nếu k6
ghi nhận dropped iterations thì kết quả chưa phản ánh đúng năng lực backend.

## 5. Lộ trình và tiêu chí nghiệm thu

Chỉ tăng mức tải sau khi mức trước qua threshold của k6 và hệ thống hồi phục
sau giai đoạn ramp-down:

| Mức | Mục đích | Lệnh thay `TARGET_RPS` |
| --- | --- | --- |
| Baseline | Xác nhận cấu hình và token | `10` |
| Tải sử dụng thông thường | Kiểm tra cache/read path | `50` |
| Tải cao cục bộ | Tìm bottleneck DB, cache, gunicorn | `200` |
| Khả năng cao hơn | Chỉ trên máy và môi trường cô lập đủ tài nguyên | tăng từng nấc 25-50% |

Mỗi lần chạy, ghi lại commit, cấu hình k6, kích thước dataset, cache warm/cold
và biểu đồ cùng time range. Một lần chạy chỉ được coi là đạt khi tất cả điều
kiện dưới đây đúng:

- k6 đạt đủ arrival rate, tỷ lệ request lỗi dưới 1%, P95 dưới 800 ms và P99
  dưới 1.5 s.
- `supplyforge:api:error_rate` không tăng kéo dài; `up{job="django-backend-local"}`
  giữ giá trị `1`.
- `supplyforge:business:cache_hit_rate` ổn định sau giai đoạn warm-up; không
  có cache error rate tăng.
- `supplyforge:celery:queue_depth` và `oldest_task_age_seconds` không tăng
  liên tục, dù kịch bản chỉ đọc không chủ động tạo job mới.
- Các KPI snapshot nghiệp vụ không thay đổi bất thường khi cùng dataset active:
  phân bố rủi ro, vốn có trọng số và backlog phải nhất quán trước/sau test.

"10.000 users" không nên được mô phỏng bằng 10.000 Python thread hoặc một máy
laptop. Quy đổi giả định sử dụng thành RPS và tỷ lệ đồng thời, đo ở các nấc ở
trên, sau đó mới dùng nhiều load generator trong một môi trường cô lập. Với
quy mô đó, cần năng lực CPU/network của generator, database và cache tương
xứng; kết quả từ một generator quá tải chỉ đo giới hạn của generator.
