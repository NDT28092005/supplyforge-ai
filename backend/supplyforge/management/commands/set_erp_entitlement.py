"""Grant or revoke the internal ERP Integrations entitlement for a workspace."""

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from supplyforge.models import Workspace, WorkspaceEntitlement


class Command(BaseCommand):
    help = 'Grant or revoke the ERP Integrations feature for one workspace.'

    def add_arguments(self, parser):
        parser.add_argument('workspace_id', type=int)
        parser.add_argument('--disable', action='store_true', help='Revoke instead of grant.')
        parser.add_argument('--expires-at', help='Optional ISO-8601 expiry timestamp.')
        parser.add_argument('--assigned-by', default='operations', help='Internal operator/audit identifier.')

    def handle(self, *args, **options):
        try:
            workspace = Workspace.objects.get(id=options['workspace_id'])
        except Workspace.DoesNotExist as exc:
            raise CommandError('Workspace không tồn tại.') from exc
        expires_at = None
        if options['expires_at']:
            expires_at = parse_datetime(options['expires_at'])
            if not expires_at:
                raise CommandError('--expires-at phải là thời điểm ISO-8601 hợp lệ.')
        entitlement, _ = WorkspaceEntitlement.objects.update_or_create(
            workspace=workspace,
            feature_code=WorkspaceEntitlement.FEATURE_ERP_INTEGRATIONS,
            defaults={
                'is_enabled': not options['disable'],
                'expires_at': expires_at,
                'assigned_by': options['assigned_by'][:128],
            },
        )
        state = 'đã kích hoạt' if entitlement.is_enabled else 'đã thu hồi'
        self.stdout.write(self.style.SUCCESS(f'ERP Integrations {state} cho workspace {workspace.id}.'))
