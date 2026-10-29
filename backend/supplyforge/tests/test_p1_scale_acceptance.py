"""Acceptance checks for P1 database, API, proxy, and observability work."""

from pathlib import Path

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from supplyforge.models import IngestionSession, User, Workspace
from supplyforge.views.auth import generate_access_token


class P1ScaleAcceptanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email='p1-scale@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace = Workspace.objects.create(
            name='P1 Scale Workspace',
            slug='p1-scale-workspace',
            owner=self.user,
        )
        IngestionSession.objects.bulk_create([
            IngestionSession(
                workspace=self.workspace,
                original_filename=f'orders-{index:03d}.csv',
                status='COMPLETED',
                total_rows=1_000 + index,
                preview_rows_json=[{'sku': f'SKU-{index}', 'sensitive_preview': 'not-in-list'}],
            )
            for index in range(105)
        ])
        self.client.credentials(
            HTTP_AUTHORIZATION=(
                f'Bearer {generate_access_token(self.user, self.workspace.id)}'
            )
        )

    def test_v2_session_history_is_paginated_compact_and_join_safe(self):
        with CaptureQueriesContext(connection) as query_context:
            response = self.client.get('/api/v2/ingestion/sessions?page=2&pageSize=25')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['items']), 25)
        self.assertEqual(payload['pagination'], {
            'page': 2,
            'pageSize': 25,
            'totalItems': 105,
            'totalPages': 5,
            'hasNext': True,
            'hasPrevious': True,
        })
        self.assertNotIn('previewRows', payload['items'][0]['profile'])
        # User/workspace auth + COUNT + one joined page query; a relationship
        # lookup per session would make this grow with page size.
        self.assertLessEqual(len(query_context), 5)

    def test_session_history_enforces_page_cap_and_preserves_v1_shape(self):
        v2_response = self.client.get('/api/v2/ingestion/sessions?pageSize=999')
        self.assertEqual(v2_response.status_code, 200)
        self.assertEqual(len(v2_response.json()['items']), 100)
        self.assertEqual(v2_response.json()['pagination']['pageSize'], 100)

        v1_response = self.client.get('/api/v1/ingestion/sessions?page=1&pageSize=20')
        self.assertEqual(v1_response.status_code, 200)
        self.assertIsInstance(v1_response.json(), list)
        self.assertEqual(len(v1_response.json()), 20)
        self.assertEqual(v1_response.headers['X-Total-Count'], '105')

    def test_invalid_session_page_parameters_are_rejected(self):
        response = self.client.get('/api/v2/ingestion/sessions?page=not-a-number')
        self.assertEqual(response.status_code, 400)
        self.assertIn('page', response.json()['error'])

    def test_api_response_has_safe_request_correlation_id(self):
        request_id = 'release-2026_10-request'
        with self.assertLogs('supplyforge.http', level='INFO') as logs:
            response = self.client.get(
                '/api/v1/ping?token=must-not-be-logged',
                HTTP_X_REQUEST_ID=request_id,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Request-ID'], request_id)
        self.assertTrue(any('http_request_completed' in line for line in logs.output))
        self.assertFalse(any('must-not-be-logged' in line for line in logs.output))

    def test_performance_critical_indexes_are_declared(self):
        expected = {
            'product_user_sku_idx',
            'product_user_created_idx',
            'order_user_created_idx',
            'order_item_sku_idx',
            'ingest_ws_created_idx',
            'ingest_ws_status_created_idx',
            'ingest_ws_hash_status_idx',
            'job_ws_status_created_idx',
            'risk_session_class_score_idx',
            'risk_session_score_sku_idx',
            'capital_analysis_rwce_idx',
            'capital_analysis_risk_rwce_idx',
            'capital_analysis_prio_rwce_idx',
        }
        actual = set()
        # Model metadata is database-agnostic and guards the migration intent;
        # applying migrations is covered by Django's test database setup.
        from supplyforge.models import (
            BackgroundJob,
            CapitalExposureItemRecord,
            Order,
            OrderItem,
            Product,
            SlowMovingRiskAssessment,
        )
        for model in (
            Product,
            Order,
            OrderItem,
            IngestionSession,
            BackgroundJob,
            SlowMovingRiskAssessment,
            CapitalExposureItemRecord,
        ):
            actual.update(index.name for index in model._meta.indexes)
        self.assertTrue(expected.issubset(actual))

    def test_nginx_p1_policy_is_present_in_the_container_configuration(self):
        repository_root = Path(__file__).resolve().parents[3]
        http_config = (repository_root / 'frontend' / 'nginx-main.conf').read_text()
        server_config = (repository_root / 'frontend' / 'nginx.conf').read_text()

        self.assertIn('limit_req_zone', http_config)
        self.assertIn('limit_conn_zone', http_config)
        self.assertIn('gzip on;', http_config)
        self.assertIn('limit_req zone=api_per_ip', server_config)
        self.assertIn('proxy_request_buffering off;', server_config)
        self.assertIn('Cache-Control', server_config)
