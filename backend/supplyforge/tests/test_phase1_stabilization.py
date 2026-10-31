import json
from unittest.mock import patch
from django.test import TestCase, Client
from supplyforge.tasks import health_check_task


class Phase1StabilizationTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_live_endpoint(self):
        """Task 1.1: GET /health/live returns {'status': 'ok'}."""
        response = self.client.get('/health/live')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'ok')

    def test_health_ready_endpoint(self):
        """Task 1.1: GET /health/ready returns {'status': 'ready', 'database': 'ok', 'redis': 'ok'}."""
        response = self.client.get('/health/ready')
        self.assertIn(response.status_code, [200, 503])
        data = json.loads(response.content)
        self.assertIn('status', data)
        self.assertIn('database', data)
        self.assertIn('redis', data)
        self.assertEqual(data.get('database'), 'ok')

    def test_version_endpoint(self):
        """Task 1.2: GET /api/version returns version information."""
        response = self.client.get('/api/version')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('application_version', data)
        self.assertIn('commit', data)
        self.assertIn('model_version', data)
        self.assertIn('feature_version', data)
        self.assertEqual(data.get('application_version'), '1.0.0')

    def test_celery_health_check_task(self):
        """Task 1.3: health_check_task executes and returns expected dictionary."""
        result = health_check_task.apply(args=['ml_worker']).get()
        self.assertEqual(result.get('status'), 'ok')
        self.assertEqual(result.get('worker_type'), 'ml_worker')
        self.assertIn('task_id', result)
        self.assertIn('timestamp', result)

    def test_celery_health_endpoint(self):
        """Task 1.3: GET /api/v1/health/celery dispatches task and returns status."""
        response = self.client.get('/api/v1/health/celery?worker_type=data_worker')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('celery_broker'), 'connected')
        self.assertIn('architecture', data)
        self.assertEqual(data.get('architecture', {}).get('flow'), 'API -> Redis -> Celery')

    @patch('supplyforge.tasks.health_check_task.apply_async')
    def test_celery_health_endpoint_routes_to_requested_worker_queue(self, mocked_apply_async):
        """The probe must test the requested worker pool, not the default queue."""
        mocked_apply_async.return_value.id = 'probe-task-id'

        response = self.client.get('/api/v1/health/celery?worker_type=integration_worker')

        self.assertEqual(response.status_code, 200)
        mocked_apply_async.assert_called_once_with(
            args=['integration_worker'], queue='integration_worker'
        )

    def test_celery_health_endpoint_rejects_unknown_worker_queue(self):
        response = self.client.get('/api/v1/health/celery?worker_type=any_queue')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')
