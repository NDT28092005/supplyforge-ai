from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from supplyforge.management.commands.benchmark_ingestion import Command


class BenchmarkIngestionCommandTests(SimpleTestCase):
    def setUp(self):
        self.command = Command()
        self.options = {'allow_non_sqlite': False}

    @override_settings(STORAGE_BACKEND='s3')
    def test_command_refuses_non_local_storage(self):
        with self.assertRaisesMessage(CommandError, 'local-only'):
            self.command._validate_options(100, 10, 1, 100, self.options)

    @override_settings(
        STORAGE_BACKEND='local',
        DATABASES={'default': {'ENGINE': 'django.db.backends.mysql'}},
    )
    def test_command_requires_explicit_opt_in_for_non_sqlite_database(self):
        with self.assertRaisesMessage(CommandError, 'Refusing to write benchmark data'):
            self.command._validate_options(100, 10, 1, 100, self.options)

    @override_settings(
        STORAGE_BACKEND='local',
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3'}},
    )
    def test_command_accepts_local_sqlite_benchmark_options(self):
        self.command._validate_options(100, 10, 1, 100, self.options)

    def test_reconciliation_rejects_missing_rows(self):
        report = {
            'source': {'rowsRequested': 10},
            'reconciliation': {
                'profileRows': 10,
                'silverRows': 10,
                'operationalRowsReceived': 9,
                'operationalValidRows': 9,
                'operationalRejectedRows': 1,
            },
        }

        with self.assertRaisesMessage(CommandError, 'Reconciliation failed'):
            self.command._assert_reconciled(report)
