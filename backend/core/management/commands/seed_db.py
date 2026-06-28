from django.core.management.base import BaseCommand
from core.models import User, Workspace, WorkspaceMember

class Command(BaseCommand):
    help = 'Seeds the database with workspace demo data'

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding database...")
        
        # Create user
        user, created = User.objects.get_or_create(
            email='demo@supplyforge.local',
            defaults={
                'display_name': 'Demo Seller',
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created demo user: {user.email}"))
        else:
            self.stdout.write(f"Demo user already exists: {user.email}")

        # Create workspace
        workspace, created = Workspace.objects.get_or_create(
            slug='demo',
            defaults={
                'name': 'Cửa hàng Demo',
                'owner': user,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created workspace demo: {workspace.name}"))
        else:
            self.stdout.write(f"Workspace demo already exists: {workspace.name}")
            
        # Add to member
        member, created = WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                'role': 'OWNER',
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Demo user added to workspace as OWNER"))
            
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
