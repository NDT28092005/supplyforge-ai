from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from supplyforge.models import (
    DecisionAuditEventRecord, DecisionRecord, SlowMovingAssessmentRun, User, Workspace,
)
from supplyforge.services.decision_trust_report import DecisionTrustReportService
from supplyforge.views.decision_views import DecisionDataStatusView


class DecisionDataStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email='decision-data-status@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(name='Decision data status', slug='decision-data-status', owner=self.user)
        self.run = SlowMovingAssessmentRun.objects.create(
            workspace=self.workspace, source_type='CSV', source_key='CSV', analysis_as_of=timezone.now(),
            source_scope={}, source_scope_fingerprint='scope', source_snapshot_fingerprint='snapshot',
            policy_version='test', policy_checksum='test', status='COMPLETED', is_current=True,
            completed_at=timezone.now(),
        )

    def test_report_separates_ready_data_from_missing_data_and_plain_feedback(self):
        ready = DecisionRecord.objects.create(
            decision_id='DATA-READY', workspace_id=self.workspace.id, sku='SKU-READY', assessment_run=self.run,
            status='RECOMMENDED', evidence_state='READY',
        )
        DecisionRecord.objects.create(
            decision_id='DATA-MISSING', workspace_id=self.workspace.id, sku='SKU-MISSING', assessment_run=self.run,
            status='RECOMMENDED', evidence_state='DATA_NEEDED',
        )
        DecisionAuditEventRecord.objects.create(
            decision=ready, event_type='DECISION_REJECTED', old_status='RECOMMENDED', new_status='REJECTED',
            metadata={'merchant_feedback': {'reason': 'DATA_DOES_NOT_MATCH', 'note': 'Tồn thực tế chưa khớp'}},
        )

        report = DecisionTrustReportService.build(workspace_id=self.workspace.id)

        self.assertEqual(report['state'], 'CHECK_DATA')
        self.assertEqual(report['counts']['ready_for_review'], 1)
        self.assertEqual(report['counts']['needs_data'], 1)
        self.assertEqual(report['merchant_feedback']['items'][0]['label'], 'Dữ liệu thực tế chưa khớp')
        self.assertNotIn('DATA_DOES_NOT_MATCH', str(report))

    def test_view_requires_workspace_context(self):
        factory = APIRequestFactory()
        denied = DecisionDataStatusView.as_view()(factory.get('/api/v1/decisions/data-status/'))
        self.assertEqual(denied.status_code, 401)

        request = factory.get('/api/v1/decisions/data-status/')
        request.tenant_context_validated = True
        request.workspace_id = self.workspace.id
        allowed = DecisionDataStatusView.as_view()(request)
        self.assertEqual(allowed.status_code, 200)
