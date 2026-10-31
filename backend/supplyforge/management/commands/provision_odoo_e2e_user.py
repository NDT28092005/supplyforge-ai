"""Provision a disposable local OWNER for exercising the Odoo UI flow."""

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from supplyforge.models import User, Workspace, WorkspaceEntitlement, WorkspaceMember


class Command(BaseCommand):
    help = 'Create or refresh the local SupplyForge Odoo E2E OWNER and ERP entitlement.'

    EMAIL = 'erp-e2e@supplyforge.test'
    PASSWORD = 'SupplyForge-E2E-Local-2026!'
    WORKSPACE_SLUG = 'odoo-local-e2e'

    CSV_EMAIL = 'erp-csv-e2e@supplyforge.test'
    CSV_PASSWORD = 'SupplyForge-CSV-E2E-Local-2026!'
    CSV_WORKSPACE_SLUG = 'odoo-csv-e2e-1000'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-fixture',
            action='store_true',
            help='Provision an isolated merchant for the 1,000-SKU CSV-aligned Odoo fixture.',
        )

    def handle(self, *args, **options):
        if settings.IS_DEPLOYED:
            raise CommandError('Lệnh này chỉ được phép dùng trong môi trường development cục bộ.')

        csv_fixture = options['csv_fixture']
        email = self.CSV_EMAIL if csv_fixture else self.EMAIL
        password = self.CSV_PASSWORD if csv_fixture else self.PASSWORD
        workspace_slug = self.CSV_WORKSPACE_SLUG if csv_fixture else self.WORKSPACE_SLUG
        workspace_name = 'Odoo CSV E2E Merchant' if csv_fixture else 'Odoo Local E2E Merchant'

        user, _ = User.objects.update_or_create(
            email=email,
            defaults={
                'display_name': 'SupplyForge Odoo CSV E2E Owner' if csv_fixture else 'SupplyForge Odoo E2E Owner',
                'password_hash': make_password(password),
                'status': User.STATUS_ACTIVE,
                'role': User.ROLE_OWNER,
                'is_email_verified': True,
                'email_verification_code': None,
                'email_verification_expires_at': None,
                'failed_login_attempts': 0,
                'locked_until': None,
            },
        )
        workspace, _ = Workspace.objects.get_or_create(
            slug=workspace_slug,
            defaults={'name': workspace_name, 'owner': user},
        )
        if workspace.owner_id != user.id:
            workspace.owner = user
            workspace.save(update_fields=['owner', 'updated_at'])
        WorkspaceMember.objects.update_or_create(
            workspace=workspace,
            user=user,
            defaults={'role': User.ROLE_OWNER},
        )
        WorkspaceEntitlement.objects.update_or_create(
            workspace=workspace,
            feature_code=WorkspaceEntitlement.FEATURE_ERP_INTEGRATIONS,
            defaults={'is_enabled': True, 'assigned_by': 'local-odoo-e2e'},
        )
        self.stdout.write(self.style.SUCCESS(
            f'Local E2E OWNER ready. email={email} workspace_id={workspace.id}'
        ))
