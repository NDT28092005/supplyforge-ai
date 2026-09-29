from django.test import TestCase, Client
from django.urls import reverse
import json


class HealthCheckTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_live_probe(self):
        """Verify /health/live returns 200 OK and expected environment metadata."""
        response = self.client.get('/health/live')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'UP')
        self.assertIn('environment', data)
        self.assertIn('version', data)
        self.assertEqual(data.get('version'), '1.0.0')

    def test_health_live_api_probe(self):
        """Verify /api/v1/health/live returns 200 OK."""
        response = self.client.get('/api/v1/health/live')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'UP')

    def test_health_ready_probe(self):
        """Verify /health/ready checks DB and returns 200 OK when DB is healthy."""
        response = self.client.get('/health/ready')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'UP')
        self.assertEqual(data.get('checks', {}).get('database'), 'UP')

    def test_health_ready_api_probe(self):
        """Verify /api/v1/health/ready returns 200 OK."""
        response = self.client.get('/api/v1/health/ready')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data.get('status'), 'UP')
