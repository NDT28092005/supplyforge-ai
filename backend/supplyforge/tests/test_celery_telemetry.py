"""
SF-OPS-08 Unit Tests — Celery Queue Depth & Task Age Telemetry
"""
import time
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.test.client import Client

from supplyforge.metrics import TASK_QUEUE_DEPTH, TASK_AGE_SECONDS
from supplyforge.celery_telemetry import record_task_age, update_celery_queue_depths, on_before_task_publish, on_task_prerun


class CeleryTelemetryTest(TestCase):
    def test_01_task_age_calculation(self):
        """Test 1: Given enqueue=T, start=T+5s -> task_age_seconds = 5."""
        enqueue_time = 1000.0
        start_time = 1005.0

        age = record_task_age(queue_name="data_worker", enqueue_time=enqueue_time, worker_start_time=start_time)
        self.assertAlmostEqual(age, 5.0, places=2)

        recorded_val = TASK_AGE_SECONDS.labels(worker_type="data", queue="data_worker")._value.get()
        self.assertAlmostEqual(recorded_val, 5.0, places=2)

    def test_02_zero_queue_wait(self):
        """Test 2: Given enqueue=T, start=T -> task_age_seconds = 0."""
        t_now = 2000.0
        age = record_task_age(queue_name="data_worker", enqueue_time=t_now, worker_start_time=t_now)
        self.assertEqual(age, 0.0)

        recorded_val = TASK_AGE_SECONDS.labels(worker_type="data", queue="data_worker")._value.get()
        self.assertEqual(recorded_val, 0.0)

    def test_03_queue_identification(self):
        """Test 3: Verify data_worker, ml_worker, and decision_worker are mapped correctly."""
        record_task_age(queue_name="data_worker", enqueue_time=100.0, worker_start_time=110.0)
        val_data = TASK_AGE_SECONDS.labels(worker_type="data", queue="data_worker")._value.get()
        self.assertEqual(val_data, 10.0)

        record_task_age(queue_name="ml_worker", enqueue_time=100.0, worker_start_time=115.0)
        val_ml = TASK_AGE_SECONDS.labels(worker_type="ml", queue="ml_worker")._value.get()
        self.assertEqual(val_ml, 15.0)

        record_task_age(queue_name="decision_worker", enqueue_time=100.0, worker_start_time=120.0)
        val_dec = TASK_AGE_SECONDS.labels(worker_type="decision", queue="decision_worker")._value.get()
        self.assertEqual(val_dec, 20.0)

    @patch("redis.Redis.from_url")
    def test_04_queue_depth(self, mock_from_url):
        """Test 4: Mock broker queue depths (data_worker=10, ml_worker=3, decision_worker=2)."""
        mock_r = MagicMock()
        def llen_side_effect(q):
            mapping = {"data_worker": 10, "ml_worker": 3, "decision_worker": 2}
            return mapping.get(q, 0)
        mock_r.llen.side_effect = llen_side_effect
        mock_from_url.return_value = mock_r

        depths = update_celery_queue_depths()

        self.assertEqual(depths["data_worker"], 10)
        self.assertEqual(depths["ml_worker"], 3)
        self.assertEqual(depths["decision_worker"], 2)

        val_data = TASK_QUEUE_DEPTH.labels(worker_type="data", queue="data_worker")._value.get()
        val_ml = TASK_QUEUE_DEPTH.labels(worker_type="ml", queue="ml_worker")._value.get()
        val_dec = TASK_QUEUE_DEPTH.labels(worker_type="decision", queue="decision_worker")._value.get()

        self.assertEqual(val_data, 10)
        self.assertEqual(val_ml, 3)
        self.assertEqual(val_dec, 2)

    def test_05_telemetry_failure_isolation(self):
        """Test 5: Force metric recording failure to verify task/telemetry does not crash."""
        with patch("supplyforge.metrics.TASK_AGE_SECONDS.labels", side_effect=ValueError("Simulated Prometheus Error")):
            age = record_task_age(queue_name="data_worker", enqueue_time=100.0, worker_start_time=105.0)
            self.assertEqual(age, 0.0)

    def test_06_label_cardinality(self):
        """Test 6: Verify metric labels ONLY contain controlled keys (worker_type, queue)."""
        gauge_depth_labels = list(TASK_QUEUE_DEPTH._labelnames)
        gauge_age_labels = list(TASK_AGE_SECONDS._labelnames)

        self.assertEqual(gauge_depth_labels, ["worker_type", "queue"])
        self.assertEqual(gauge_age_labels, ["worker_type", "queue"])

        for prohibited in ["task_id", "user_id", "workspace_id", "sku_id", "order_id", "request_id"]:
            self.assertNotIn(prohibited, gauge_depth_labels)
            self.assertNotIn(prohibited, gauge_age_labels)

    def test_07_metrics_exposition(self):
        """Test 7: Verify Prometheus /metrics endpoint exposes supplyforge_task_queue_depth and supplyforge_task_age_seconds."""
        update_celery_queue_depths()
        record_task_age(queue_name="data_worker", enqueue_time=time.time() - 2.0)

        client = Client()
        response = client.get("/metrics")
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn("supplyforge_task_queue_depth", content)
        self.assertIn("supplyforge_task_age_seconds", content)
