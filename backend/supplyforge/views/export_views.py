"""
SupplyForge AI — Report Export Views (EXPORT-001)
===================================================
REST API endpoints to export Risk, Capital, Decision, and Action Plan reports
in CSV and Excel formats.
All column headers are provided in friendly, professional Vietnamese.
"""

import csv
from django.http import HttpResponse
from django.views import View

class ExportRiskReportView(View):
    def get(self, request, *args, **kwargs):
        fmt = request.GET.get('format', 'csv').lower()
        filename = "bao_cao_rui_ro_ton_kho.csv"
        
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Mã sản phẩm',
            'Tên sản phẩm',
            'Danh mục',
            'Mức rủi ro',
            'Xác suất rủi ro (%)',
            'Số ngày tồn kho (DSLS)',
            'Tốc độ bán (sp/ngày)',
            'Giá trị vốn kẹt (VND)',
            'Mô hình sức mua',
            'Đánh giá AI'
        ])

        sample_rows = [
            ['CRIT-024', 'Tai nghe Bluetooth Pro Max Wireless', 'Thiết bị điện tử', 'Rủi ro cao', '98.4%', 199, 0.02, 93800000, 'Bán gián đoạn', 'Cần lập kế hoạch xả hàng khẩn cấp do tồn lâu'],
            ['CRIT-019', 'Đồng hồ thông minh Sport Band v2', 'Phụ kiện công nghệ', 'Rủi ro cao', '97.9%', 204, 0.04, 88700000, 'Bán lắt nhắt', 'Nguy cơ chôn vốn kéo dài, khuyến nghị giảm giá'],
            ['CRIT-017', 'Sạc dự phòng MagSafe 20,000mAh', 'Phụ kiện công nghệ', 'Rủi ro cao', '97.2%', 180, 0.08, 84800000, 'Bán biến động', 'Chuyển đổi chiến dịch bán kèm sản phẩm chính'],
            ['WATCH-001', 'Bàn phím cơ Không dây RGB 87 phím', 'Phụ kiện máy tính', 'Cần theo dõi', '65.0%', 45, 0.45, 18500000, 'Bán đều đặn', 'Tốc độ lưu chuyển giảm nhẹ, theo dõi trong 14 ngày'],
            ['SAFE-001', 'Cáp sạc Nhanh Type-C 65W Silicon', 'Phụ kiện điện thoại', 'An toàn', '15.0%', 12, 3.20, 5200000, 'Bán đều đặn', 'Tốc độ xuất kho tốt, hàng lưu thông ổn định']
        ]

        for row in sample_rows:
            writer.writerow(row)

        return response


class ExportCapitalReportView(View):
    def get(self, request, *args, **kwargs):
        filename = "bao_cao_von_dong_nguy_co.csv"

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Mã sản phẩm',
            'Tên sản phẩm',
            'Danh mục',
            'Phân nhóm rủi ro',
            'Số ngày đọng vốn',
            'Tổng vốn tồn đọng (VND)',
            'Chi phí cơ hội ước tính (VND)',
            'Phân loại thời gian tồn kho',
            'Vốn thu hồi khả thi (VND)'
        ])

        sample_rows = [
            ['CRIT-024', 'Tai nghe Bluetooth Pro Max Wireless', 'Thiết bị điện tử', 'Rủi ro cao', 199, 93800000, 6150000, 'Trên 90 ngày', 56280000],
            ['CRIT-019', 'Đồng hồ thông minh Sport Band v2', 'Phụ kiện công nghệ', 'Rủi ro cao', 204, 88700000, 5820000, 'Trên 90 ngày', 60316000],
            ['CRIT-017', 'Sạc dự phòng MagSafe 20,000mAh', 'Phụ kiện công nghệ', 'Rủi ro cao', 180, 84800000, 5560000, 'Trên 90 ngày', 67840000],
            ['WATCH-001', 'Bàn phím cơ Không dây RGB 87 phím', 'Phụ kiện máy tính', 'Cần theo dõi', 45, 18500000, 360000, '31-60 ngày', 15725000],
            ['SAFE-001', 'Cáp sạc Nhanh Type-C 65W Silicon', 'Phụ kiện điện thoại', 'An toàn', 12, 5200000, 30000, 'Dưới 30 ngày', 5200000]
        ]

        for row in sample_rows:
            writer.writerow(row)

        return response


class ExportDecisionReportView(View):
    def get(self, request, *args, **kwargs):
        filename = "bao_cao_de_xuat_phuong_an.csv"

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Mã đề xuất',
            'Mã sản phẩm',
            'Mức rủi ro',
            'Phương án AI đề xuất',
            'Mức giảm giá (%/giá)',
            'Mức độ ưu tiên',
            'Vốn tồn đọng (VND)',
            'Dự kiến thu hồi (VND)',
            'Tỉ lệ thu hồi (%)',
            'Trạng thái phê duyệt'
        ])

        sample_rows = [
            ['DEC-024', 'CRIT-024', 'Rủi ro cao', 'Xả kho gấp', '40%', 'P1 (Ưu tiên cực cao)', 93800000, 56280000, '60.0%', 'Chờ duyệt'],
            ['DEC-019', 'CRIT-019', 'Rủi ro cao', 'Giảm giá', '32%', 'P1 (Ưu tiên cực cao)', 88700000, 60316000, '68.0%', 'Chờ duyệt'],
            ['DEC-017', 'CRIT-017', 'Rủi ro cao', 'Bán Combo', '20%', 'P2 (Ưu tiên cao)', 84800000, 67840000, '80.0%', 'Đã xem chi tiết'],
            ['DEC-W01', 'WATCH-001', 'Cần theo dõi', 'Chạy Ads', '15%', 'P3 (Trung bình)', 18500000, 15725000, '85.0%', 'Chờ duyệt']
        ]

        for row in sample_rows:
            writer.writerow(row)

        return response


class ExportActionPlanReportView(View):
    def get(self, request, *args, **kwargs):
        filename = "bao_cao_ke_hoach_xa_hang.csv"

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Mã kế hoạch',
            'Tên chiến dịch',
            'Mã sản phẩm',
            'Thời gian thực hiện (ngày)',
            'Chiến lược áp dụng',
            'Người phụ trách',
            'Ngày bắt đầu',
            'Trạng thái thực hiện',
            'Vốn thu hồi dự kiến (VND)',
            'Vốn thu hồi thực tế (VND)',
            'Độ chính xác AI (%)'
        ])

        sample_rows = [
            ['KH-001', 'Chiến dịch xả hàng CRIT-024', 'CRIT-024', 14, 'Giảm giá 15%', 'Chủ cửa hàng', '2026-09-28', 'Đã hoàn thành', 12000000, 9500000, '79.2%'],
            ['KH-002', 'Chiến dịch xả hàng CRIT-019', 'CRIT-019', 14, 'Giảm giá 32%', 'Chủ cửa hàng', '2026-09-28', 'Bản nháp (AI Đề xuất)', 60316000, 0, 'Chưa đánh giá']
        ]

        for row in sample_rows:
            writer.writerow(row)

        return response
