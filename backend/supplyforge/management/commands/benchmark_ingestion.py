"""Run a local, bounded-memory ingestion benchmark without cloud services."""

from __future__ import annotations

import csv
import json
import resource
import sys
import time
import tracemalloc
import uuid
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from supplyforge.models import IngestionSession, Workspace
from supplyforge.services.csv_profiler import StreamingCSVProfiler
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService
from supplyforge.services.storage_backend import StorageBackend


class Command(BaseCommand):
    help = (
        'Generate and ingest a synthetic CSV locally, reporting throughput, '
        'memory high-water mark, and raw/bronze/silver/gold reconciliation.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--rows', type=int, default=100_000)
        parser.add_argument('--sku-count', type=int, default=10_000)
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--chunk-size', type=int, default=None)
        parser.add_argument('--output-dir', default='')
        parser.add_argument('--report', default='')
        parser.add_argument('--include-post-import-hooks', action='store_true')
        parser.add_argument(
            '--trace-python-memory',
            action='store_true',
            help='Capture Python allocation peak; this adds measurable benchmark overhead.',
        )
        parser.add_argument(
            '--allow-non-sqlite',
            action='store_true',
            help='Acknowledge that benchmark rows will be written to the configured database.',
        )

    def handle(self, *args, **options):
        rows = options['rows']
        sku_count = options['sku_count']
        days = options['days']
        chunk_size = options['chunk_size'] or settings.INGESTION_CHUNK_ROW_SIZE
        self._validate_options(rows, sku_count, days, chunk_size, options)

        output_dir = Path(options['output_dir'] or settings.INGESTION_UPLOAD_DIR) / 'benchmarks'
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        source_path = output_dir / f'ingestion-benchmark-{run_id}.csv'
        user_id = f'benchmark-{run_id}'
        workspace = Workspace.objects.create(name=f'Local ingestion benchmark {run_id[:8]}')
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename=source_path.name,
            storage_path=str(source_path),
            raw_storage_path=str(source_path),
            session_type='INITIAL',
            status='PROCESSING',
        )

        trace_python_memory = options['trace_python_memory']
        if trace_python_memory:
            tracemalloc.start()
        started = time.monotonic()
        timings = {}
        try:
            stage_started = time.monotonic()
            self._write_synthetic_csv(source_path, rows, sku_count, days)
            session.file_size_bytes = source_path.stat().st_size
            session.save(update_fields=['file_size_bytes', 'updated_at'])
            timings['generateSeconds'] = self._elapsed(stage_started)

            stage_started = time.monotonic()
            profile = StreamingCSVProfiler.profile_csv(str(source_path))
            if profile.validation and profile.validation.get('status') == 'REJECT':
                raise CommandError(f"Generated CSV was rejected: {profile.validation.get('errors', [])}")
            session.total_rows = profile.total_rows
            session.total_columns = profile.total_columns
            session.headers_json = profile.headers
            session.column_types_json = profile.column_types
            session.preview_rows_json = profile.preview_rows
            session.missing_values_json = profile.missing_values
            session.dataset_profile_json = profile.to_dict()
            timings['profileSeconds'] = self._elapsed(stage_started)

            stage_started = time.monotonic()
            session.lake_storage_path = StorageBackend.publish_raw_to_lake(
                str(source_path),
                f'bronze/workspace-{workspace.id}/sessions/{session.id}/source.csv',
            )
            session.save(update_fields=[
                'total_rows', 'total_columns', 'headers_json', 'column_types_json',
                'preview_rows_json', 'missing_values_json', 'dataset_profile_json',
                'lake_storage_path', 'updated_at',
            ])
            version = LakehouseIngestionService.prepare_version(session)
            timings['bronzeSeconds'] = self._elapsed(stage_started)

            mapping_rule = {
                'orderId': 'order_id',
                'itemSku': 'sku',
                'productName': 'product_name',
                'price': 'selling_price',
                'cost': 'cost_price',
                'quantity': 'quantity',
                'orderDate': 'order_date',
                'stock': 'stock',
            }
            stage_started = time.monotonic()
            silver = LakehouseIngestionService.materialize_silver(
                version,
                str(source_path),
                mapping_rule,
            )
            timings['silverSeconds'] = self._elapsed(stage_started)

            stage_started = time.monotonic()
            import_result = DynamicFileImportService.process_file_in_chunks(
                str(source_path),
                mapping_rule,
                user_id,
                session_type='INITIAL',
                force_reset=True,
                session_id=str(session.id),
                workspace_id=workspace.id,
                chunk_size=chunk_size,
                run_post_import_hooks=options['include_post_import_hooks'],
            )
            LakehouseIngestionService.record_import_result(version, import_result)
            timings['operationalImportSeconds'] = self._elapsed(stage_started)

            stage_started = time.monotonic()
            gold = LakehouseIngestionService.materialize_gold(version)
            version = LakehouseIngestionService.promote(version)
            session.status = 'COMPLETED'
            session.readiness_status = 'COMPLETED'
            session.save(update_fields=['status', 'readiness_status', 'updated_at'])
            timings['goldAndPromoteSeconds'] = self._elapsed(stage_started)

            report = self._build_report(
                source_path=source_path,
                rows=rows,
                sku_count=sku_count,
                days=days,
                chunk_size=chunk_size,
                profile=profile,
                version=version,
                silver=silver,
                import_result=import_result,
                gold=gold,
                timings=timings,
                elapsed=self._elapsed(started),
                trace_python_memory=trace_python_memory,
            )
            self._assert_reconciled(report)
            if options['report']:
                report_path = Path(options['report'])
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report['reportPath'] = str(report_path)
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if trace_python_memory:
                tracemalloc.stop()

    def _validate_options(self, rows, sku_count, days, chunk_size, options):
        if settings.STORAGE_BACKEND != 'local':
            raise CommandError('benchmark_ingestion is local-only. Set STORAGE_BACKEND=local.')
        if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3' and not options['allow_non_sqlite']:
            raise CommandError(
                'Refusing to write benchmark data to a non-SQLite database. '
                'Use USE_SQLITE=1 or explicitly pass --allow-non-sqlite.'
            )
        if not 1 <= rows <= settings.INGESTION_MAX_ROWS:
            raise CommandError(f'--rows must be between 1 and {settings.INGESTION_MAX_ROWS:,}.')
        if not 1 <= sku_count <= rows:
            raise CommandError('--sku-count must be between 1 and --rows.')
        if not 1 <= days <= 366:
            raise CommandError('--days must be between 1 and 366.')
        if chunk_size < 100:
            raise CommandError('--chunk-size must be at least 100.')

    @staticmethod
    def _write_synthetic_csv(path: Path, rows: int, sku_count: int, days: int) -> None:
        start_date = date(2025, 1, 1)
        with path.open('w', encoding='utf-8', newline='') as output:
            writer = csv.writer(output)
            writer.writerow([
                'order_id', 'sku', 'product_name', 'selling_price',
                'cost_price', 'quantity', 'order_date', 'stock',
            ])
            for index in range(rows):
                sku_index = index % sku_count
                order_date = start_date + timedelta(days=index % days)
                price = 100_000 + (sku_index % 100) * 1_000
                writer.writerow([
                    f'BENCH-{index:09d}',
                    f'BENCH-SKU-{sku_index:07d}',
                    f'Benchmark product {sku_index}',
                    price,
                    int(price * 0.65),
                    (index % 5) + 1,
                    order_date.isoformat(),
                    100 + (sku_index % 50),
                ])

    @staticmethod
    def _elapsed(started: float) -> float:
        return round(time.monotonic() - started, 3)

    @staticmethod
    def _peak_rss_bytes() -> int:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == 'darwin' else value * 1024)

    def _build_report(self, **kwargs) -> dict:
        current_bytes, peak_python_bytes = (
            tracemalloc.get_traced_memory()
            if kwargs['trace_python_memory']
            else (None, None)
        )
        profile = kwargs['profile']
        version = kwargs['version']
        import_result = kwargs['import_result']
        silver = kwargs['silver']
        gold = kwargs['gold']
        elapsed = kwargs['elapsed']
        return {
            'status': 'PASS',
            'ranAt': timezone.now().isoformat(),
            'localOnly': True,
            'source': {
                'path': str(kwargs['source_path']),
                'rowsRequested': kwargs['rows'],
                'skuCount': kwargs['sku_count'],
                'datePartitions': kwargs['days'],
                'chunkSize': kwargs['chunk_size'],
            },
            'dataset': {
                'workspaceId': version.workspace_id,
                'sessionId': str(version.ingestion_session_id),
                'version': version.version_label,
                'dataAsOf': version.data_as_of.isoformat() if version.data_as_of else None,
            },
            'reconciliation': {
                'profileRows': profile.total_rows,
                'silverRows': silver['rowsWritten'],
                'operationalRowsReceived': import_result.get('rows_received', 0),
                'operationalValidRows': import_result.get('rows_valid', 0),
                'operationalRejectedRows': import_result.get('rows_rejected', 0),
                'gold': gold['reconciliation'],
            },
            'timingSeconds': kwargs['timings'],
            'totalSeconds': elapsed,
            'rowsPerSecond': round(kwargs['rows'] / elapsed, 2) if elapsed else None,
            'memory': {
                'pythonCurrentBytes': current_bytes,
                'pythonPeakBytes': peak_python_bytes,
                'processPeakRssBytes': self._peak_rss_bytes(),
            },
        }

    @staticmethod
    def _assert_reconciled(report: dict) -> None:
        source_rows = report['source']['rowsRequested']
        reconciliation = report['reconciliation']
        checks = {
            'profileRows': reconciliation['profileRows'],
            'silverRows': reconciliation['silverRows'],
            'operationalRowsReceived': reconciliation['operationalRowsReceived'],
            'operationalValidRows': reconciliation['operationalValidRows'],
        }
        mismatched = {name: value for name, value in checks.items() if value != source_rows}
        if mismatched or reconciliation['operationalRejectedRows']:
            raise CommandError(
                f'Reconciliation failed. Expected {source_rows} rows; observed {mismatched}; '
                f"rejected={reconciliation['operationalRejectedRows']}"
            )
