from unittest.mock import patch
from django.test import TestCase, Client

class HealthEndpointsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_live_endpoint(self):
        """AC-01: /health/live returns 200 OK with status ok without calling dependencies"""
        response = self.client.get('/health/live')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

        response_v1 = self.client.get('/api/v1/health/live')
        self.assertEqual(response_v1.status_code, 200)
        self.assertEqual(response_v1.json()["status"], "ok")

    @patch('supplyforge.views.health._check_mysql')
    @patch('supplyforge.views.health._check_redis')
    def test_health_ready_healthy(self, mock_redis, mock_mysql):
        """AC-02: /health/ready returns 200 OK when critical dependencies are healthy"""
        mock_mysql.return_value = "healthy"
        mock_redis.return_value = "healthy"

        response = self.client.get('/health/ready')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ready", "database": "ok", "redis": "ok",
        })

    @patch('supplyforge.views.health._check_mysql')
    @patch('supplyforge.views.health._check_redis')
    def test_health_ready_mysql_failure(self, mock_redis, mock_mysql):
        """AC-02: /health/ready returns 503 when MySQL is unhealthy"""
        mock_mysql.return_value = "unhealthy"
        mock_redis.return_value = "healthy"

        response = self.client.get('/health/ready')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "not_ready", "database": "unavailable", "redis": "ok",
        })

    @patch('supplyforge.views.health._check_mysql')
    @patch('supplyforge.views.health._check_redis')
    def test_health_ready_redis_failure(self, mock_redis, mock_mysql):
        """AC-02: /health/ready returns 503 when Redis is unhealthy"""
        mock_mysql.return_value = "healthy"
        mock_redis.return_value = "unhealthy"

        response = self.client.get('/health/ready')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "not_ready", "database": "ok", "redis": "unavailable",
        })

    @patch('supplyforge.views.health._check_mysql')
    @patch('supplyforge.views.health._check_redis')
    @patch('supplyforge.views.health._check_celery')
    def test_health_dependencies_all_healthy(self, mock_celery, mock_redis, mock_mysql):
        """AC-03: /health/dependencies returns 200 with structured status when all dependencies are healthy"""
        mock_mysql.return_value = "healthy"
        mock_redis.return_value = "healthy"
        mock_celery.return_value = "healthy"

        response = self.client.get('/health/dependencies')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["dependencies"]["mysql"]["status"], "healthy")
        self.assertEqual(data["dependencies"]["redis"]["status"], "healthy")
        self.assertEqual(data["dependencies"]["celery"]["status"], "healthy")

    @patch('supplyforge.views.health._check_mysql')
    @patch('supplyforge.views.health._check_redis')
    @patch('supplyforge.views.health._check_celery')
    def test_health_dependencies_degraded(self, mock_celery, mock_redis, mock_mysql):
        """AC-03: /health/dependencies returns 503 when Celery or any dependency is unhealthy"""
        mock_mysql.return_value = "healthy"
        mock_redis.return_value = "healthy"
        mock_celery.return_value = "unhealthy"

        response = self.client.get('/health/dependencies')
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["dependencies"]["celery"]["status"], "unhealthy")

    def test_health_security_no_secret_leaks(self):
        """AC-04: Health endpoints must not leak credentials, passwords, or connection strings"""
        for url in ['/health/live', '/health/ready', '/health/dependencies']:
            response = self.client.get(url)
            content_str = response.content.decode('utf-8').lower()
            self.assertNotIn('password', content_str)
            self.assertNotIn('secret', content_str)
            self.assertNotIn('token', content_str)
            self.assertNotIn('mysql://', content_str)
            self.assertNotIn('redis://', content_str)
