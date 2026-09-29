"""
Unit tests for Search, Filtering, Sorting, and Report Exports (EXPORT-001)
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

class SearchFilterExportTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_export_risk_report_csv(self):
        url = reverse('export_risk_report')
        response = self.client.get(url, {'format': 'csv'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertIn('attachment; filename="bao_cao_rui_ro_ton_kho.csv"', response['Content-Disposition'])
        content = response.content.decode('utf-8-sig')
        self.assertIn('Mã sản phẩm', content)
        self.assertIn('Tên sản phẩm', content)
        self.assertIn('CRIT-024', content)

    def test_export_capital_report_csv(self):
        url = reverse('export_capital_report')
        response = self.client.get(url, {'format': 'csv'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8-sig')
        content = response.content.decode('utf-8-sig')
        self.assertIn('Tổng vốn tồn đọng (VND)', content)

    def test_export_decision_report_csv(self):
        url = reverse('export_decision_report')
        response = self.client.get(url, {'format': 'csv'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn('Mã đề xuất', content)
        self.assertIn('Phương án AI đề xuất', content)

    def test_export_action_plan_report_csv(self):
        url = reverse('export_action_plan_report')
        response = self.client.get(url, {'format': 'csv'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn('Mã kế hoạch', content)
        self.assertIn('Tên chiến dịch', content)
