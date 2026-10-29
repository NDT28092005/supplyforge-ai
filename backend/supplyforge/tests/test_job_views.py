from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import (
    BackgroundJob,
    DatasetVersion,
    IngestionSession,
    User,
    Workspace,
)
from supplyforge.views.auth import generate_access_token


class JobViewsTestCase(TestCase):
    """HTTP contract tests for import progress and cooperative cancellation."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email='job-api@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace = Workspace.objects.create(
            name='Job API Workspace',
            slug='job-api-workspace',
            owner=self.user,
        )
        self.session = IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename='orders.csv',
            session_type='INITIAL',
            status='PROCESSING',
            dataset_version='v1.0',
        )
        DatasetVersion.objects.create(
            workspace=self.workspace,
            ingestion_session=self.session,
            version_number=1,
            version_label='v1.0',
            import_type='INITIAL',
            status=DatasetVersion.STATUS_ACTIVE,
            data_as_of=timezone.now(),
            activated_at=timezone.now(),
        )
        self.job = BackgroundJob.objects.create(
            workspace=self.workspace,
            job_type='CSV_IMPORT',
            ingestion_session=self.session,
            status='RUNNING',
            current_stage='IMPORTING',
            progress_pct=58,
            stages_json={
                'IMPORTING': {
                    'status': 'RUNNING',
                    'phase': 'SILVER',
                    'rowsProcessed': 5000,
                    'totalRows': 10000,
                    'estimatedTimeRemainingSeconds': 90,
                    'estimatedCompletionAt': '2026-10-18T12:01:30+00:00',
                    'partitionProgress': {
                        'completedCount': 2,
                        'totalCount': 4,
                        'partitions': {'2026-10-17': 2500, '2026-10-18': 2500},
                    },
                    'checkpoint': {'phase': 'SILVER', 'batchNumber': 5},
                },
            },
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=(
                f'Bearer {generate_access_token(self.user, self.workspace.id)}'
            )
        )

    def test_status_exposes_progress_eta_checkpoint_and_freshness(self):
        response = self.client.get(f'/api/v2/jobs/{self.job.id}/status')

        self.assertEqual(response.status_code, 200)
        payload = response.data
        self.assertEqual(payload['estimatedTimeRemaining'], 90)
        self.assertEqual(
            payload['estimatedCompletionAt'],
            '2026-10-18T12:01:30+00:00',
        )
        self.assertEqual(payload['partitionProgress']['completedCount'], 2)
        self.assertEqual(payload['checkpoint']['phase'], 'SILVER')
        self.assertEqual(payload['importPhase'], 'SILVER')
        self.assertEqual(payload['datasetVersion'], 'v1.0')
        self.assertIsNotNone(payload['dataAsOf'])
        self.assertFalse(payload['isStale'])

    def test_cancel_requests_worker_stop_at_next_durable_checkpoint(self):
        response = self.client.post(f'/api/v2/jobs/{self.job.id}/cancel')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'CANCEL_REQUESTED')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'CANCEL_REQUESTED')

    def test_cancel_rejects_job_after_dataset_publish(self):
        stages = self.job.stages_json
        stages['IMPORTING']['checkpoint'] = {'phase': 'PUBLISHED'}
        self.job.stages_json = stages
        self.job.save(update_fields=['stages_json', 'updated_at'])

        response = self.client.post(f'/api/v2/jobs/{self.job.id}/cancel')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.job.status, 'RUNNING')
        self.assertIn('publish', response.data['message'].lower())

    def test_list_active_only_returns_only_jobs_that_need_polling(self):
        BackgroundJob.objects.create(
            workspace=self.workspace,
            job_type='CSV_IMPORT',
            ingestion_session=self.session,
            status='COMPLETED',
            current_stage='FINALIZING',
            progress_pct=100,
        )

        response = self.client.get('/api/v2/jobs/?active_only=true')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['activeOnly'])
        self.assertEqual([job['jobId'] for job in response.data['jobs']], [str(self.job.id)])
