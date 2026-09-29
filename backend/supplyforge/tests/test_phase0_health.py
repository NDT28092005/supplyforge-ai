import json
from django.test import TestCase, Client


class HealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_live_probe(self):
        """Verify /health/live returns status ok."""
        response = self.client.get('/health/live')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'ok')

    def test_health_live_api_probe(self):
        """Verify /api/v1/health/live returns status ok."""
        response = self.client.get('/api/v1/health/live')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'ok')

    def test_health_ready_probe(self):
        """Verify /health/ready checks DB and Redis and returns ready status."""
        response = self.client.get('/health/ready')
        self.assertIn(response.status_code, [200, 503])
        data = json.loads(response.content)
        self.assertIn(data.get('status'), ['ready', 'not_ready'])
        self.assertEqual(data.get('database'), 'ok')

    def test_health_ready_api_probe(self):
        """Verify /api/v1/health/ready returns ready status."""
        response = self.client.get('/api/v1/health/ready')
        self.assertIn(response.status_code, [200, 503])
        data = json.loads(response.content)
        self.assertIn(data.get('status'), ['ready', 'not_ready'])
        self.assertEqual(data.get('database'), 'ok')
