"""
SupplyForge AI — Notification System Unit Tests (NOTI-001 & NOTI-002)
====================================================================
Tests notification listing, auto-seeding of 6 trigger types, mark-as-read, and creation.
"""

from django.test import TestCase
from django.urls import reverse
import json
from supplyforge.models import NotificationRecord


class NotificationSystemTests(TestCase):
    def test_auto_seed_notifications_covering_all_triggers(self):
        """GET /api/v1/notifications/ auto-seeds sample alerts if empty."""
        response = self.client.get('/api/v1/notifications/')
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data['success'])
        self.assertGreaterEqual(data['count'], 6)
        self.assertGreaterEqual(data['unread_count'], 6)

        types_found = {item['notification_type'] for item in data['notifications']}
        expected_types = {
            NotificationRecord.TRIGGER_NEW_CRITICAL_SKU,
            NotificationRecord.TRIGGER_CAPITAL_EXPOSURE_INCREASE,
            NotificationRecord.TRIGGER_DATASET_STALE,
            NotificationRecord.TRIGGER_IMPORT_FAILED,
            NotificationRecord.TRIGGER_PREDICTION_FAILED,
            NotificationRecord.TRIGGER_ACTION_DEADLINE_APPROACHING
        }
        self.assertEqual(types_found, expected_types)

    def test_mark_notifications_read(self):
        """POST /api/v1/notifications/mark-read/ marks notification as read."""
        record = NotificationRecord.objects.create(
            workspace_id=1,
            notification_type=NotificationRecord.TRIGGER_NEW_CRITICAL_SKU,
            title='Test Alert',
            message='Test Message',
            severity=NotificationRecord.SEVERITY_HIGH,
            is_read=False
        )

        response = self.client.post(
            '/api/v1/notifications/mark-read/',
            data=json.dumps({'id': record.id}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)

        record.refresh_from_db()
        self.assertTrue(record.is_read)

    def test_mark_all_notifications_read(self):
        """POST /api/v1/notifications/mark-read/ with mark_all=True marks all items as read."""
        self.client.get('/api/v1/notifications/') # auto-seed

        response = self.client.post(
            '/api/v1/notifications/mark-read/',
            data=json.dumps({'mark_all': True}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['unread_count'], 0)

        unread_in_db = NotificationRecord.objects.filter(workspace_id=1, is_read=False).count()
        self.assertEqual(unread_in_db, 0)

    def test_create_notification(self):
        """POST /api/v1/notifications/create/ creates a new alert trigger."""
        payload = {
            'workspace_id': 1,
            'notification_type': NotificationRecord.TRIGGER_CAPITAL_EXPOSURE_INCREASE,
            'title': 'Vốn đọng tăng đọt biến',
            'message': 'Đo lường rủi ro vốn tăng.',
            'severity': NotificationRecord.SEVERITY_CRITICAL
        }

        response = self.client.post(
            '/api/v1/notifications/create/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['notification']['title'], 'Vốn đọng tăng đọt biến')
