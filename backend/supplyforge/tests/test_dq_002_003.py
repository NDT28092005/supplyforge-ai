import json
from django.test import TestCase
from supplyforge.models import User, IngestionSession
from supplyforge.views.auth import get_or_create_user_tenant
from supplyforge.services.data_quality_service import DataQualityService


class DQ002AndDQ003TestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="merchant_dq002@shop.com",
            display_name="Merchant DQ002",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant = get_or_create_user_tenant(self.user)
        self.session = IngestionSession.objects.create(
            workspace=self.tenant,
            original_filename="raw_sales_low_dq.csv",
            total_rows=1000,
            status='COMPLETED'
        )

    def test_dq_002_quality_issue_detection_vietnamese(self):
        """DQ-002: Detects quality issues with percentages in user-friendly Vietnamese."""
        issues = DataQualityService.detect_quality_issues(
            total_rows=1000,
            duplicate_count=23,       # 2.3%
            missing_sku_count=2,      # 0.2%
            missing_date_count=1,     # 0.1%
            invalid_qty_count=1,      # 0.1%
            missing_revenue_count=11  # 1.1%
        )

        labels = [issue["label"] for issue in issues]
        self.assertIn("Thiếu mã SKU", labels)
        self.assertIn("Ngày không hợp lệ", labels)
        self.assertIn("Trùng lặp đơn hàng / giao dịch", labels)
        self.assertIn("Số lượng âm", labels)
        self.assertIn("Thiếu giá trị / doanh thu", labels)

        sku_issue = next(i for i in issues if i["issue_code"] == "MISSING_SKU")
        self.assertEqual(sku_issue["display_rate"], "0.2%")

        dup_issue = next(i for i in issues if i["issue_code"] == "DUPLICATE_ORDER")
        self.assertEqual(dup_issue["display_rate"], "2.3%")

    def test_dq_003_quality_impact_propagation_5_layers(self):
        """DQ-003: Propagates Data Quality impact across 5 downstream layers (Risk->Explanation->Capital->Decision->Copilot)."""
        # Set low quality metrics (health score < 70)
        self.session.valid_rows_count = 100  # 90% rejected -> score 64
        self.session.save()

        prop_res = DataQualityService.propagate_health_score_to_pipeline(self.session)
        
        self.assertIn("pipeline_stages", prop_res)
        stages = prop_res["pipeline_stages"]

        # Layer 1: Risk Model
        risk_stage = stages["3_RiskModel"]["payload"]
        self.assertEqual(risk_stage["risk_adjustment_factor"], 1.30)
        self.assertIn("Phạt 30% trọng số rủi ro", risk_stage["quality_impact_note"])

        # Layer 2: Explanation
        expl_stage = stages["4_Explanation"]["payload"]
        self.assertTrue(expl_stage["quality_warnings_included"])
        self.assertIn("Cảnh báo: Dữ liệu chưa đầy đủ", expl_stage["explanation_warning_vi"])

        # Layer 3: Capital Exposure
        cap_stage = stages["5_Capital"]["payload"]
        self.assertEqual(cap_stage["capital_haircut_pct"], 15.0)
        self.assertFalse(cap_stage["is_recovery_guaranteed"])

        # Layer 4: Decision Support
        dec_stage = stages["6_Decision"]["payload"]
        self.assertEqual(dec_stage["decision_confidence_vi"], "Thấp")
        self.assertFalse(dec_stage["is_definitive_claim_allowed"])
        self.assertIn("Dữ liệu chưa đầy đủ", dec_stage["decision_reason_vi"])

        # Layer 5: Copilot Context
        copilot_stage = stages["7_Copilot"]["payload"]
        self.assertTrue(copilot_stage["is_data_quality_low"])
        self.assertIn("Lưu ý từ Trợ lý AI", copilot_stage["copilot_disclaimer_vi"])
