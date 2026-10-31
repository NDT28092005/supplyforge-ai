import json
from django.test import TestCase, Client
from supplyforge.models import User, IngestionSession, SlowMovingRiskAssessment, WorkspaceMember
from supplyforge.views.auth import generate_access_token, get_or_create_user_tenant
from supplyforge.services.lineage_service import LineageService


class Lin001AndLin002TestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(
            email="merchant_lin@shop.com",
            display_name="Merchant Lineage",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role=User.ROLE_OWNER
        )
        self.tenant = get_or_create_user_tenant(self.user)
        WorkspaceMember.objects.get_or_create(
            workspace=self.tenant, user=self.user, defaults={'role': User.ROLE_OWNER},
        )
        self.client.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {generate_access_token(self.user, self.tenant.id)}'
        )
        self.session = IngestionSession.objects.create(
            workspace=self.tenant,
            original_filename="orders_import_sept.csv",
            file_size_bytes=10240,
            status='COMPLETED'
        )
        self.risk = SlowMovingRiskAssessment.objects.create(
            session=self.session,
            sku="SKU-LIN-999",
            canonical_sku_id="SKU-LIN-999",
            product_name="Sản phẩm thử nghiệm Lineage",
            risk_class="HIGH_RISK",
            risk_score=88.5,
            risk_probability=0.885,
            model_version="xgboost_exp03_v1",
            calibration_version="calibration_v1.0",
            decision_cutoff="2026-09-01",
            dataset_version="v1.0"
        )

    def test_lin_001_record_lineage_5_step_chain(self):
        """LIN-001: Traces prediction lineage backwards through 5 steps."""
        lineage_res = LineageService.get_full_record_lineage("SKU-LIN-999")
        
        self.assertEqual(lineage_res["record_id"], "SKU-LIN-999")
        chain = lineage_res["lin001_traceability_chain"]
        
        # Step 1: Risk prediction
        self.assertIn("step_1_risk_prediction", chain)
        self.assertEqual(chain["step_1_risk_prediction"]["sku"], "SKU-LIN-999")
        self.assertEqual(chain["step_1_risk_prediction"]["risk_class"], "HIGH_RISK")
        
        # Step 2: Feature snapshot
        self.assertIn("step_2_feature_snapshot", chain)
        self.assertEqual(chain["step_2_feature_snapshot"]["feature_version"], "feat_v1.0")
        
        # Step 3: Canonical data
        self.assertIn("step_3_canonical_data", chain)
        self.assertEqual(chain["step_3_canonical_data"]["canonical_sku_id"], "SKU-LIN-999")
        
        # Step 4: Import
        self.assertIn("step_4_import", chain)
        self.assertEqual(chain["step_4_import"]["session_id"], str(self.session.id))
        
        # Step 5: Original file
        self.assertIn("step_5_original_file", chain)
        self.assertEqual(chain["step_5_original_file"]["file_name"], "orders_import_sept.csv")

    def test_lin_002_prediction_lineage_7_metadata_fields(self):
        """LIN-002: Stores and returns 7-field prediction metadata."""
        meta = LineageService.get_prediction_lineage(assessment=self.risk)
        
        self.assertEqual(meta["model_version"], "xgboost_exp03_v1")
        self.assertEqual(meta["feature_version"], "feat_v1.0")
        self.assertEqual(meta["calibration_version"], "calibration_v1.0")
        self.assertEqual(meta["threshold_version"], "threshold_v1.0")
        self.assertEqual(meta["training_cutoff"], "2026-09-01")
        self.assertIn("prediction_timestamp", meta)
        self.assertEqual(meta["dataset_version"], "v1.0")

    def test_lin_001_002_api_endpoint(self):
        """API Endpoint test: GET /api/v1/ingestion/lineage/<record_id>."""
        response = self.client.get('/api/v1/ingestion/lineage/SKU-LIN-999')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data["record_id"], "SKU-LIN-999")
        self.assertIn("lin001_traceability_chain", data)
        self.assertIn("lin002_prediction_metadata", data)
        self.assertIn("lineage_summary_vi", data)
