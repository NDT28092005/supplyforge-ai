from django.test import TestCase, Client
import supplyforge.metrics as metrics


class DomainMetricsTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_metrics_objects_exist(self):
        """AC-01: Verify all custom Prometheus metric objects exist in supplyforge.metrics"""
        self.assertIsNotNone(metrics.INGESTION_TOTAL)
        self.assertIsNotNone(metrics.PREDICTION_TOTAL)
        self.assertIsNotNone(metrics.RISK_ASSESSMENT_TOTAL)
        self.assertIsNotNone(metrics.DECISION_GENERATED_TOTAL)
        self.assertIsNotNone(metrics.CACHE_HIT_TOTAL)
        self.assertIsNotNone(metrics.TASK_TOTAL)

    def test_helper_functions_execution(self):
        """AC-10: Test that recording helpers execute safely without throwing exceptions"""
        metrics.record_ingestion(pipeline='medallion', source_type='csv', status='success', rows=100)
        metrics.record_prediction(model='xgboost', model_version='v1', status='success')
        metrics.record_risk_assessment(risk_level='CRITICAL', status='success')
        metrics.update_high_risk_sku_gauge(critical_count=5, high_count=10)
        metrics.record_decision(decision_type='PO_REORDER', action='generated')
        metrics.record_cache(cache_area='dashboard', operation='get', result='hit')
        metrics.record_task(worker_type='data', queue='data_worker', task_type='run_import_pipeline', status='success')

    def test_forbidden_cardinality_labels(self):
        """AC-08: Ensure no high-cardinality or PII labels exist in custom metric labelnames"""
        forbidden_labels = {'user_id', 'workspace_id', 'sku_id', 'order_id', 'email', 'request_id', 'raw_error', 'cache_key'}
        
        all_metrics = [
            metrics.INGESTION_TOTAL,
            metrics.PREDICTION_TOTAL,
            metrics.RISK_ASSESSMENT_TOTAL,
            metrics.DECISION_GENERATED_TOTAL,
            metrics.CACHE_HIT_TOTAL,
            metrics.TASK_TOTAL
        ]
        
        for m in all_metrics:
            labelnames = set(getattr(m, '_labelnames', ()))
            intersection = labelnames.intersection(forbidden_labels)
            self.assertEqual(
                len(intersection), 0,
                f"Metric {m._name} contains forbidden high-cardinality label: {intersection}"
            )

    def test_metrics_exposition_in_endpoint(self):
        """AC-09: Verify custom supplyforge_* metrics appear in /metrics endpoint output"""
        # Execute helper calls to increment metrics
        metrics.record_ingestion(pipeline='medallion', source_type='csv', status='success')
        metrics.record_prediction(model='xgboost', model_version='v1', status='success')
        metrics.record_risk_assessment(risk_level='CRITICAL', status='success')
        metrics.record_decision(decision_type='PO_REORDER', action='generated')
        metrics.record_cache(cache_area='dashboard', operation='get', result='hit')

        response = self.client.get('/metrics')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('supplyforge_ingestion_total', content)
        self.assertIn('supplyforge_prediction_total', content)
        self.assertIn('supplyforge_risk_assessment_total', content)
        self.assertIn('supplyforge_decision_generated_total', content)
        self.assertIn('supplyforge_cache_hit_total', content)
