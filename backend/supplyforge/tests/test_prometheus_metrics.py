from django.test import TestCase, Client

class PrometheusMetricsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_metrics_endpoint_returns_200(self):
        """Kiểm tra /metrics trả về HTTP 200 và Prometheus exposition format"""
        response = self.client.get('/metrics')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check Prometheus exposition format markers
        self.assertIn('# HELP', content)
        self.assertIn('# TYPE', content)
        
        # Check for django HTTP or python system metrics
        self.assertTrue(
            'django_http' in content or 'python_info' in content or 'django_db' in content,
            "Expected Prometheus metrics for Django/Python to be present in /metrics output"
        )
