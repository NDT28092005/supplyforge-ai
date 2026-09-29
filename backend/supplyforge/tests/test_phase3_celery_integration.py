import os
import tempfile
from django.test import TestCase, override_settings
from django.contrib.auth.hashers import make_password
from supplyforge.models import User, Workspace, Product
from supplyforge.tasks import health_check_task, process_file_import_async


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True, CELERY_RESULT_BACKEND='cache+memory://')
class CeleryIntegrationPyramidTests(TestCase):
    """
    Task 3.4: Celery Integration Test suite (4th layer of Test Pyramid).
    - Verifies celery background task execution under CELERY_TASK_ALWAYS_EAGER=True
    - Health check tasks for data_worker, ml_worker, decision_worker
    - Async CSV file processing pipeline and status transitions
    """

    def setUp(self):
        self.user = User.objects.create(
            email="celery_tester@supplyforge.local",
            password_hash=make_password("Pass123456"),
            display_name="Celery Tester",
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
            role="OWNER"
        )
        self.workspace = Workspace.objects.create(
            name="Celery Test Workspace",
            owner=self.user,
            slug="celery_ws"
        )

    def test_health_check_task_execution(self):
        """Celery health check task executes synchronously and returns status ok."""
        for worker in ["data_worker", "ml_worker", "decision_worker"]:
            result = health_check_task.apply(args=[worker])
            self.assertTrue(result.successful())
            res_dict = result.result
            self.assertEqual(res_dict["status"], "ok")
            self.assertEqual(res_dict["worker_type"], worker)

    def test_process_file_import_async_execution(self):
        """Async CSV import Celery task processes dataset and populates canonical models."""
        csv_content = (
            "id,user_id,third_party_id,product_name,item_sku,stock,cost,price,order_date\n"
            "p_celery_1,user_celery_01,tp_c_1,Celery Widget Alpha,SKU_CELERY_001,50,12.5,25.0,2026-09-29 10:00:00\n"
            "p_celery_2,user_celery_01,tp_c_2,Celery Widget Beta,SKU_CELERY_002,100,50.0,99.99,2026-09-29 10:05:00\n"
        )

        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".csv") as tmp:
            tmp.write(csv_content)
            tmp_path = tmp.name

        try:
            mapping_rule = {
                "id": "id",
                "user_id": "user_id",
                "third_party_id": "third_party_id",
                "product_name": "product_name",
                "item_sku": "item_sku",
                "stock": "stock",
                "cost": "cost",
                "price": "price",
                "order_date": "order_date"
            }

            task_result = process_file_import_async.apply(args=[tmp_path, mapping_rule, str(self.user.id)])
            self.assertTrue(task_result.successful())
            output = task_result.result

            self.assertEqual(output["status"], "SUCCESS")
            self.assertEqual(output["progress"], 100)
            self.assertIn("Import completed", output["message"])

            # Verify Database persistence
            products = Product.objects.filter(item_sku__startswith="SKU_CELERY_")
            self.assertEqual(products.count(), 2)

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
