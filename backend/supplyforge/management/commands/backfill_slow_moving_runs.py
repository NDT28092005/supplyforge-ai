"""Publish trusted slow-moving runs for already active CSV datasets."""

from django.core.management.base import BaseCommand, CommandError

from supplyforge.models import DatasetVersion
from supplyforge.services.slow_moving_run_service import SlowMovingRunService


class Command(BaseCommand):
    help = 'Build an idempotent operational slow-moving run for active CSV dataset versions.'

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', type=int, help='Backfill one workspace only.')

    def handle(self, *args, **options):
        versions = DatasetVersion.objects.filter(status=DatasetVersion.STATUS_ACTIVE).order_by('workspace_id')
        workspace_id = options.get('workspace_id')
        if workspace_id:
            versions = versions.filter(workspace_id=workspace_id)
        if workspace_id and not versions.exists():
            raise CommandError('No active CSV dataset was found for this workspace.')

        completed = failed = 0
        for version in versions.iterator():
            try:
                run = SlowMovingRunService.run_csv_for_dataset(version)
                completed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'workspace={version.workspace_id} dataset={version.version_label} run={run.id}'
                    )
                )
            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f'workspace={version.workspace_id} dataset={version.version_label}: {exc}'
                    )
                )
        if failed:
            raise CommandError(f'Completed {completed} run(s); {failed} run(s) failed.')
        self.stdout.write(self.style.SUCCESS(f'Completed {completed} slow-moving run(s).'))
