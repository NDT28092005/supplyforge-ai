from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from supplyforge.models import IntegrationConnection, InventoryRecord, Sku, User, Workspace
from supplyforge.models.decision import DecisionRecord, DecisionReviewRecord
from supplyforge.services.decision_evidence_freshness import DecisionEvidenceFreshnessService
from supplyforge.views.auth import generate_access_token


class DecisionRevalidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create(
            email='renewal-owner@example.test', status=User.STATUS_ACTIVE,
            is_email_verified=True, role=User.ROLE_OWNER,
        )
        self.workspace = Workspace.objects.create(name='Renewal', slug='renewal', owner=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generate_access_token(self.owner, self.workspace.id)}')
        self.connection = IntegrationConnection.objects.create(
            workspace=self.workspace, provider='ODOO', display_name='Odoo',
            status=IntegrationConnection.STATUS_ACTIVE, base_url='https://odoo.example.test',
        )

    def _decision(self):
        sku = Sku.objects.create(workspace=self.workspace, original_name='SKU-RENEW', normalized_name='SKU-RENEW')
        self.inventory = InventoryRecord.objects.create(
            sku=sku, canonical_sku='SKU-RENEW', warehouse_code='MAIN', record_date=timezone.localdate(),
            quantity=20, available_quantity=20, cost_price=70_000, selling_price=100_000,
            lifecycle_status='ACTIVE', as_of_verified=True,
            source_snapshot_id=f'ODOO:{self.connection.id}:today:SKU-RENEW:MAIN',
            source_observed_at=timezone.now(),
            source_lineage_json={'provider': 'ODOO', 'connection_id': str(self.connection.id)},
        )
        evidence = DecisionEvidenceFreshnessService.capture(workspace_id=self.workspace.id, sku='SKU-RENEW')
        return DecisionRecord.objects.create(
            decision_id='DEC-RENEW-1', workspace_id=self.workspace.id, sku='SKU-RENEW',
            action_type='DISCOUNT', status='ACCEPTED',
            action_parameters={'evidence_snapshot': evidence},
        )

    def test_approval_is_append_only_and_later_fact_change_requires_recheck(self):
        decision = self._decision()
        passport = self.client.get(f'/api/v1/decisions/{decision.decision_id}/revalidation/')
        self.assertEqual(passport.status_code, 200)
        self.assertEqual(passport.data['state'], 'READY')
        self.assertTrue(passport.data['can_approve'])

        approved = self.client.post(
            f'/api/v1/decisions/{decision.decision_id}/revalidation/', {'note': 'Đã kiểm tra trước khi chạy.'}, format='json'
        )
        self.assertEqual(approved.status_code, 201)
        self.assertEqual(DecisionReviewRecord.objects.filter(decision=decision).count(), 1)
        snapshot = DecisionReviewRecord.objects.get(decision=decision).current_snapshot_json
        self.assertEqual(snapshot['records'][0]['available_quantity'], '20')

        self.inventory.available_quantity = 12
        self.inventory.save(update_fields=['available_quantity'])
        changed = self.client.get(f'/api/v1/decisions/{decision.decision_id}/revalidation/')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data['state'], 'NEEDS_RECHECK')
        self.assertEqual(changed.data['changes'][0]['label'], 'Số lượng tồn có thể bán')
        self.assertEqual(DecisionReviewRecord.objects.get(decision=decision).current_snapshot_json, snapshot)

        renewed = self.client.post(
            f'/api/v1/decisions/{decision.decision_id}/revalidation/',
            {'note': 'Đã kiểm tra mức tồn mới và vẫn giữ phương án giá.'}, format='json',
        )
        self.assertEqual(renewed.status_code, 201)
        self.assertEqual(renewed.data['state'], 'READY')
        self.assertEqual(DecisionReviewRecord.objects.filter(decision=decision).count(), 2)

    def test_other_workspace_cannot_read_passport(self):
        decision = self._decision()
        other = Workspace.objects.create(name='Other renewal', slug='other-renewal', owner=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {generate_access_token(self.owner, other.id)}')
        response = self.client.get(f'/api/v1/decisions/{decision.decision_id}/revalidation/')
        self.assertEqual(response.status_code, 404)
