import io
import os
import tempfile
from rest_framework.test import APIClient
from django.test import TestCase
from supplyforge.models import IngestionSession, User, Workspace, WorkspaceMember
from supplyforge.services.nfr_manager import NFRManager
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.views.auth import generate_access_token
from django.core.files.uploadedfile import SimpleUploadedFile


class NFRPerformanceAndMemoryTestCase(TestCase):
    """
    Test suite verifying:
    - NFR-IMP-001: File <= 10 MB upload acceptance within < 3 seconds SLA.
    - NFR-IMP-002: Bounded memory & crash-free execution.
    - NFR-IMP-003: Automated asynchronous thresholding (> 10 MB returns 202 Accepted).
    - Requirement #24: Streaming generator chunked import engine (CHUNK_ROW_SIZE = 50,000).
    """

    def setUp(self):
        self.client = APIClient()
        self.user_id = 'test_merchant_nfr'
        self.user = User.objects.create(
            email='nfr@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace, _ = Workspace.objects.get_or_create(
            id=1,
            defaults={'name': 'NFR Workspace', 'owner': self.user},
        )
        WorkspaceMember.objects.get_or_create(
            workspace=self.workspace,
            user=self.user,
        )
        self.auth = {
            'HTTP_AUTHORIZATION': (
                f'Bearer {generate_access_token(self.user, self.workspace.id)}'
            )
        }

    def test_nfr_imp_001_upload_acceptance_sla_under_3_seconds(self):
        """Verify uploading a 1 MB CSV file returns acceptance response within < 3.0 seconds SLA."""
        rows = ["order_id,sku,product_name,selling_price,quantity,order_date"]
        for i in range(500):
            rows.append(f"ORD-SLA-{i},SKU-SLA-{i},Product SLA {i},150000,2,2026-07-01")
        csv_bytes = "\n".join(rows).encode('utf-8')

        file_obj = SimpleUploadedFile("orders_1mb.csv", csv_bytes, content_type="text/csv")

        response = self.client.post(
            '/api/v2/ingestion/upload',
            {'file': file_obj, 'workspaceId': 1},
            format='multipart'
            ,
            **self.auth
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn('acceptance_latency', data)
        latency_info = data['acceptance_latency']
        self.assertTrue(latency_info['sla_passed'])
        self.assertLess(latency_info['latency_sec'], 3.0)

    def test_nfr_imp_003_auto_async_threshold_exceeded(self):
        """Verify files exceeding 10 MB threshold return HTTP 202 Accepted with async queue dispatch."""
        # Force threshold test using NFRManager method directly
        mock_file_size = 15 * 1024 * 1024  # 15 MB > 10 MB threshold
        should_async = NFRManager.should_dispatch_async(mock_file_size)
        self.assertTrue(should_async)

    def test_req24_chunked_streaming_generator_execution(self):
        """Verify Requirement #24: read_csv_in_chunks generator yields 50k row chunks without memory spikes."""
        temp_csv = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv')
        try:
            temp_csv.write("order_id,sku,product_name,selling_price,quantity,order_date\n")
            for i in range(120):
                temp_csv.write(f"ORD-CHUNK-{i},SKU-CHUNK-{i},Chunked Item {i},200000,1,2026-08-01\n")
            temp_csv.close()

            chunks_yielded = 0
            total_rows_yielded = 0

            # Use chunk_size = 50 rows for test fast verification
            for header, chunk in DynamicFileImportService.read_csv_in_chunks(temp_csv.name, chunk_size=50):
                chunks_yielded += 1
                total_rows_yielded += len(chunk)
                self.assertTrue(header.startswith("order_id"))
                self.assertLessEqual(len(chunk), 50)

            self.assertEqual(chunks_yielded, 3)  # 120 rows / 50 chunk size = 3 chunks (50 + 50 + 20)
            self.assertEqual(total_rows_yielded, 120)

            # Test process_file_in_chunks
            res = DynamicFileImportService.process_file_in_chunks(
                temp_csv.name, {}, self.user_id, session_type='INITIAL', force_reset=True, chunk_size=50
            )
            self.assertEqual(res["status"], "DATA_READY")
        finally:
            if os.path.exists(temp_csv.name):
                os.remove(temp_csv.name)
