import io
from contextlib import contextmanager
from unittest.mock import mock_open, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from supplyforge.models import BackgroundJob, DatasetVersion, IngestionSession, User, Workspace
from supplyforge.services.csv_validator import CSVFormatValidator, ValidationStatus
from supplyforge.services.ingestion import DynamicFileImportService
from supplyforge.services.lakehouse_ingestion import LakehouseIngestionService
from supplyforge.tasks import ImportCancelled, _import_progress_reporter
from supplyforge.views.auth import generate_access_token


class DatasetVersionLifecycleTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name='Lakehouse workspace')

    def _session(self, name, session_type='INITIAL'):
        return IngestionSession.objects.create(
            workspace=self.workspace,
            original_filename=name,
            raw_storage_path=f'/raw/{name}',
            lake_storage_path=f'/bronze/{name}',
            session_type=session_type,
            status='PROCESSING',
        )

    def test_versions_are_immutable_and_promote_without_deleting_history(self):
        initial_session = self._session('initial.csv')
        initial_version = LakehouseIngestionService.prepare_version(initial_session)
        LakehouseIngestionService.promote(initial_version)

        incremental_session = self._session('incremental.csv', 'INCREMENTAL')
        incremental_version = LakehouseIngestionService.prepare_version(incremental_session)

        self.assertEqual(initial_version.version_label, 'v1.0')
        self.assertEqual(incremental_version.version_label, 'v2.0')
        self.assertEqual(incremental_version.parent_version_id, initial_version.id)

        LakehouseIngestionService.promote(incremental_version)
        initial_version.refresh_from_db()
        incremental_version.refresh_from_db()

        self.assertEqual(initial_version.status, DatasetVersion.STATUS_SUPERSEDED)
        self.assertEqual(incremental_version.status, DatasetVersion.STATUS_ACTIVE)
        self.assertEqual(DatasetVersion.objects.filter(workspace=self.workspace).count(), 2)

    def test_failure_marks_only_building_version_and_preserves_manifest(self):
        session = self._session('failed.csv')
        version = LakehouseIngestionService.prepare_version(session)
        version.manifest_json = {'silver': {'completed': True, 'rowsWritten': 10}}
        version.save(update_fields=['manifest_json', 'updated_at'])

        LakehouseIngestionService.mark_failed(session, 'Parquet writer unavailable')
        version.refresh_from_db()

        self.assertEqual(version.status, DatasetVersion.STATUS_FAILED)
        self.assertTrue(version.manifest_json['silver']['completed'])
        self.assertEqual(version.manifest_json['failure']['message'], 'Parquet writer unavailable')

    def test_initial_version_keeps_current_dataset_active_until_promoted(self):
        current_session = self._session('current.csv')
        current = LakehouseIngestionService.prepare_version(current_session)
        LakehouseIngestionService.promote(current)

        replacement_session = self._session('replacement.csv')
        replacement = LakehouseIngestionService.prepare_version(replacement_session)

        current.refresh_from_db()
        self.assertEqual(current.status, DatasetVersion.STATUS_ACTIVE)
        self.assertEqual(replacement.status, DatasetVersion.STATUS_BUILDING)

    def test_cancelled_version_resumes_without_replacing_previous_active_version(self):
        current_session = self._session('current.csv')
        current = LakehouseIngestionService.prepare_version(current_session)
        LakehouseIngestionService.promote(current)

        replacement_session = self._session('cancelled.csv')
        cancelled = LakehouseIngestionService.prepare_version(replacement_session)
        LakehouseIngestionService.mark_cancelled(replacement_session, 'User stopped import')
        cancelled.refresh_from_db()

        self.assertEqual(cancelled.status, DatasetVersion.STATUS_CANCELLED)
        current.refresh_from_db()
        self.assertEqual(current.status, DatasetVersion.STATUS_ACTIVE)

        resumed = LakehouseIngestionService.prepare_version(replacement_session)
        resumed.refresh_from_db()
        self.assertEqual(resumed.id, cancelled.id)
        self.assertEqual(resumed.status, DatasetVersion.STATUS_BUILDING)
        self.assertNotIn('cancellation', resumed.manifest_json)

    @override_settings(INGESTION_CHUNK_ROW_SIZE=2)
    def test_silver_materialization_partitions_bounded_batches(self):
        class FakeTable:
            @staticmethod
            def from_pylist(rows):
                return rows

        class FakePyArrow:
            Table = FakeTable

        class FakeParquet:
            @staticmethod
            def write_table(table, path, compression):
                self.assertEqual(compression, 'snappy')

        class FakeTemporaryFile:
            name = '/virtual/part.parquet'

            @staticmethod
            def close():
                return None

        session = self._session('orders.csv')
        version = LakehouseIngestionService.prepare_version(session)
        source_path = '/virtual/orders.csv'
        source_content = (
            'sku,order_date\n'
            'SKU-1,2026-01-01\n'
            'SKU-2,2026-01-02\n'
            'SKU-3,2026-01-01\n'
        )

        with patch.object(
            LakehouseIngestionService,
            '_require_pyarrow',
            return_value=(FakePyArrow, FakeParquet),
        ), patch(
            'supplyforge.services.lakehouse_ingestion.os.path.exists',
            return_value=True,
        ), patch(
            'supplyforge.services.lakehouse_ingestion.open',
            mock_open(read_data=source_content),
            create=True,
        ), patch(
            'supplyforge.services.lakehouse_ingestion.tempfile.NamedTemporaryFile',
            return_value=FakeTemporaryFile(),
        ), patch(
            'supplyforge.services.lakehouse_ingestion.os.remove',
        ), patch(
            'supplyforge.services.lakehouse_ingestion.StorageBackend.save_processed_file',
            side_effect=lambda path, key, content_type: f'/lake/{key}',
        ) as save_file:
            manifest = LakehouseIngestionService.materialize_silver(
                version,
                source_path,
                {'orderDate': 'order_date'},
            )

        self.assertEqual(manifest['rowsWritten'], 3)
        self.assertEqual(manifest['partitionCounts'], {'2026-01-01': 2, '2026-01-02': 1})
        self.assertEqual(save_file.call_count, 3)
        version.refresh_from_db()
        self.assertTrue(version.manifest_json['silver']['completed'])


class ImportStageRetryTests(TestCase):
    def test_retry_reuses_completed_operational_import(self):
        workspace = Workspace.objects.create(name='Retry workspace')
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename='retry.csv',
            storage_path='/tmp/retry.csv',
            session_type='INITIAL',
        )
        job = BackgroundJob.objects.create(
            workspace=workspace,
            ingestion_session=session,
            job_type='CSV_IMPORT',
        )
        version = LakehouseIngestionService.prepare_version(session)
        import_result = {
            'status': 'DATA_READY',
            'rows_valid': 9,
            'rows_rejected': 1,
            'rows_received': 10,
        }
        LakehouseIngestionService.record_import_result(version, import_result)

        @contextmanager
        def localized(_path):
            yield '/tmp/retry.csv'

        with patch(
            'supplyforge.tasks.StorageBackend.localize',
            localized,
        ), patch(
            'supplyforge.services.lakehouse_ingestion.LakehouseIngestionService.materialize_silver',
            return_value={'completed': True, 'rowsWritten': 10},
        ), patch(
            'supplyforge.services.ingestion.DynamicFileImportService.process_file_in_chunks',
        ) as chunk_import, patch(
            'supplyforge.services.lakehouse_ingestion.LakehouseIngestionService.materialize_gold',
            return_value={'reconciliation': {'status': 'MATCHED'}},
        ):
            from supplyforge.tasks import _stage_import

            context = _stage_import(job, {'mapping_rule': {}})

        chunk_import.assert_not_called()
        self.assertEqual(context['import_result'], import_result)
        self.assertEqual(context['lake_reconciliation']['status'], 'MATCHED')


class ImportProgressTests(TestCase):
    def test_progress_records_checkpoint_eta_and_honours_cancellation(self):
        workspace = Workspace.objects.create(name='Progress workspace')
        session = IngestionSession.objects.create(
            workspace=workspace,
            original_filename='progress.csv',
            total_rows=100,
        )
        job = BackgroundJob.objects.create(
            workspace=workspace,
            ingestion_session=session,
            job_type='CSV_IMPORT',
            status='RUNNING',
            stages_json={'IMPORTING': {'status': 'PROCESSING', 'progress': 20}},
        )
        report = _import_progress_reporter(job, total_rows=100)

        report({
            'phase': 'SILVER',
            'rowsProcessed': 40,
            'batchNumber': 2,
            'filesWritten': 3,
            'partitionCounts': {'2026-01-01': 25, '2026-01-02': 15},
        })
        job.refresh_from_db()
        progress = job.stages_json['IMPORTING']
        self.assertEqual(progress['rowsProcessed'], 40)
        self.assertEqual(progress['partitionProgress']['completedCount'], 2)
        self.assertEqual(progress['checkpoint']['phase'], 'SILVER')
        self.assertIn('estimatedTimeRemainingSeconds', progress)

        job.status = 'CANCEL_REQUESTED'
        job.save(update_fields=['status', 'updated_at'])
        with self.assertRaises(ImportCancelled):
            report({'phase': 'OPERATIONAL_IMPORT', 'rowsProcessed': 60})


class DatasetVersionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner_a = User.objects.create(
            email='lake-a@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.owner_b = User.objects.create(
            email='lake-b@example.com',
            status=User.STATUS_ACTIVE,
            is_email_verified=True,
        )
        self.workspace_a = Workspace.objects.create(name='Lake API A', owner=self.owner_a)
        self.workspace_b = Workspace.objects.create(name='Lake API B', owner=self.owner_b)
        self.session_a = IngestionSession.objects.create(
            workspace=self.workspace_a,
            original_filename='a.csv',
        )
        self.session_b = IngestionSession.objects.create(
            workspace=self.workspace_b,
            original_filename='b.csv',
        )
        self.version_a = LakehouseIngestionService.prepare_version(self.session_a)
        LakehouseIngestionService.promote(self.version_a)
        version_b = LakehouseIngestionService.prepare_version(self.session_b)
        LakehouseIngestionService.promote(version_b)

    def test_dataset_versions_are_scoped_to_authenticated_workspace(self):
        token_a = generate_access_token(self.owner_a, workspace_id=self.workspace_a.id)
        response = self.client.get(
            f'/api/v2/ingestion/sessions/{self.session_a.id}/dataset-versions',
            HTTP_AUTHORIZATION=f'Bearer {token_a}',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['currentVersion'], self.version_a.version_label)
        self.assertEqual(len(response.data['versions']), 1)

        cross_tenant = self.client.get(
            f'/api/v2/ingestion/sessions/{self.session_b.id}/dataset-versions',
            HTTP_AUTHORIZATION=f'Bearer {token_a}',
        )
        self.assertEqual(cross_tenant.status_code, 403)


class BoundedChunkImportTests(TestCase):
    def test_csv_validator_never_requests_an_unbounded_read(self):
        class GuardedBytesIO(io.BytesIO):
            def read(self, size=-1):
                if size == -1:
                    raise AssertionError('validator attempted to read the full CSV into memory')
                return super().read(size)

        result = CSVFormatValidator.validate_file(GuardedBytesIO(
            b'order_id,sku,product_name,selling_price,quantity,order_date\n'
            b'ORD-1,SKU-1,Product,100,1,2026-01-01\n'
        ))

        self.assertNotEqual(result.status, ValidationStatus.REJECT)

    def test_chunk_runner_aggregates_results_and_runs_hooks_once(self):
        csv_source = io.StringIO(
            'order_id,sku\n'
            'ORD-1,SKU-1\n'
            'ORD-2,SKU-2\n'
            'ORD-3,SKU-3\n'
            'ORD-4,SKU-4\n'
            'ORD-5,SKU-5\n'
        )

        def result_for_batch(*args, **kwargs):
            is_last = kwargs['run_post_import_hooks']
            return {
                'status': 'DATA_READY',
                'rows_received': 2 if not is_last else 1,
                'new_rows': 2 if not is_last else 1,
                'rows_valid': 2 if not is_last else 1,
                'rows_rejected': 0,
                'rows_appended': 2 if not is_last else 1,
                'duplicate_rows': 0,
                'updated_rows': 0,
                'warnings': 0,
                'data_corrections': [],
                'rejected_rows': [],
                'overlap_detected': False,
                'temporal_range': {},
                'dataset_consistency': {'status': 'PASS'} if is_last else None,
                'products_count': 5,
                'orders_count': 5,
                'order_items_count': 5,
            }

        progress_events = []
        with patch.object(
            DynamicFileImportService,
            'process_batch_import',
            side_effect=result_for_batch,
        ) as process_batch, patch(
            'supplyforge.services.nfr_manager.NFRManager.release_chunk_memory'
        ):
            result = DynamicFileImportService.process_file_in_chunks(
                csv_source,
                mapping_rule={},
                user_id='merchant-bounded',
                chunk_size=2,
                progress_callback=progress_events.append,
            )

        self.assertEqual(process_batch.call_count, 3)
        self.assertEqual(result['rows_received'], 5)
        self.assertEqual(result['new_rows'], 5)
        self.assertEqual(result['products_count'], 5)
        self.assertTrue(process_batch.call_args_list[-1].kwargs['run_post_import_hooks'])
        self.assertFalse(process_batch.call_args_list[0].kwargs['run_post_import_hooks'])
        self.assertEqual(
            [call.kwargs['source_line_offset'] for call in process_batch.call_args_list],
            [0, 2, 4],
        )
        self.assertEqual(
            [event['rowsProcessed'] for event in progress_events],
            [2, 4, 5],
        )
