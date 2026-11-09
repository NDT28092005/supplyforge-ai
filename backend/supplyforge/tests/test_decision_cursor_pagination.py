from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import DecisionRecord


class DecisionCursorPaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        base = timezone.now()
        for index in range(3):
            decision = DecisionRecord.objects.create(
                decision_id=f'CURSOR-{index}', workspace_id=1, sku=f'SKU-{index}',
                status='RECOMMENDED', priority_score=10 - index,
                capital_exposure=100 - index,
            )
            # auto_now_add cannot take an input at create; make the tuple
            # deterministic for a tie-break test.
            DecisionRecord.objects.filter(pk=decision.pk).update(created_at=base - timedelta(minutes=index))

    def test_keyset_cursor_is_stable_and_does_not_return_total_count(self):
        url = reverse('decision_list_create_v1')
        first = self.client.get(url, {'pagination': 'cursor', 'page_size': 2, 'sort': 'priority'})
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual([item['decision_id'] for item in first_payload['items']], ['CURSOR-0', 'CURSOR-1'])
        self.assertTrue(first_payload['pagination']['has_next'])
        self.assertNotIn('total_items', first_payload['pagination'])

        second = self.client.get(url, {
            'pagination': 'cursor', 'page_size': 2, 'sort': 'priority',
            'cursor': first_payload['pagination']['next_cursor'],
        })
        self.assertEqual(second.status_code, 200)
        self.assertEqual([item['decision_id'] for item in second.json()['items']], ['CURSOR-2'])
        self.assertFalse(second.json()['pagination']['has_next'])

    def test_cursor_cannot_be_reused_with_another_sort(self):
        url = reverse('decision_list_create_v1')
        first = self.client.get(url, {'pagination': 'cursor', 'page_size': 1, 'sort': 'priority'}).json()
        response = self.client.get(url, {
            'pagination': 'cursor', 'page_size': 1, 'sort': 'capital',
            'cursor': first['pagination']['next_cursor'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'INVALID_CURSOR')
