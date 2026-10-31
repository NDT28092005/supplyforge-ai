from django.conf import settings
from django.test import SimpleTestCase

from supplyforge.tasks import (
    enqueue_due_integration_syncs,
    process_file_import_async,
    process_integration_event,
    refresh_integration_operational_analytics,
    run_integration_sync,
    sync_shopee_orders_task,
    sync_shopee_products_task,
)


class WorkerQueueTopologyTests(SimpleTestCase):
    """Protect the isolation contract required by the production worker pool."""

    def test_expected_queues_are_declared(self):
        queue_names = {queue.name for queue in settings.CELERY_TASK_QUEUES}
        self.assertTrue({
            'celery',
            'data_worker',
            'ml_worker',
            'decision_worker',
            'integration_worker',
        }.issubset(queue_names))

    def test_erp_tasks_are_routed_to_the_integration_queue(self):
        for task in (
            run_integration_sync,
            refresh_integration_operational_analytics,
            process_integration_event,
            enqueue_due_integration_syncs,
            sync_shopee_products_task,
            sync_shopee_orders_task,
        ):
            self.assertEqual(task.queue, 'integration_worker')

    def test_import_task_remains_in_data_queue(self):
        self.assertEqual(process_file_import_async.queue, 'data_worker')
