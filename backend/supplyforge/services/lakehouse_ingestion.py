"""Versioned bronze/silver/gold artifacts for bounded-memory ingestion."""

from __future__ import annotations

import csv
import heapq
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from supplyforge.models import DatasetVersion, IngestionSession, Workspace
from supplyforge.services.storage_backend import StorageBackend


class LakehouseIngestionError(RuntimeError):
    """Raised when a lake artifact cannot be produced safely."""


class LakehouseIngestionService:
    """Creates immutable lake versions around the operational MySQL projection."""

    SILVER_CONTENT_TYPE = 'application/vnd.apache.parquet'
    GOLD_CONTENT_TYPE = 'application/json'
    MANIFEST_SCHEMA_VERSION = 1
    _IMPORT_SUMMARY_FIELDS = (
        'status',
        'import_type',
        'rows_received',
        'rows_valid',
        'rows_rejected',
        'new_rows',
        'duplicate_rows',
        'updated_rows',
        'warnings',
        'products_count',
        'orders_count',
        'order_items_count',
        'temporal_range',
    )

    @classmethod
    def prepare_version(cls, session: IngestionSession) -> DatasetVersion:
        """Create exactly one BUILDING version per session with a stable lineage parent."""
        with transaction.atomic():
            locked_session = IngestionSession.objects.select_for_update().get(id=session.id)
            existing = (
                DatasetVersion.objects.select_for_update()
                .filter(ingestion_session=locked_session)
                .first()
            )
            if existing:
                if existing.status in {
                    DatasetVersion.STATUS_FAILED,
                    DatasetVersion.STATUS_CANCELLED,
                }:
                    manifest = dict(existing.manifest_json or {})
                    manifest.pop('failure', None)
                    manifest.pop('cancellation', None)
                    existing.status = DatasetVersion.STATUS_BUILDING
                    existing.manifest_json = manifest
                    existing.save(update_fields=['status', 'manifest_json', 'updated_at'])
                return existing

            # The workspace lock serializes version numbering across concurrent jobs.
            workspace = Workspace.objects.select_for_update().get(id=locked_session.workspace_id)
            parent = (
                DatasetVersion.objects.select_for_update()
                .filter(workspace=workspace, status=DatasetVersion.STATUS_ACTIVE)
                .order_by('-version_number')
                .first()
            )
            next_number = (
                DatasetVersion.objects.filter(workspace=workspace).aggregate(
                    maximum=Max('version_number')
                )['maximum']
                or 0
            ) + 1
            version = DatasetVersion.objects.create(
                workspace=workspace,
                ingestion_session=locked_session,
                parent_version=parent,
                version_number=next_number,
                version_label=f'v{next_number}.0',
                import_type=locked_session.session_type,
                raw_storage_path=locked_session.raw_storage_path,
                bronze_storage_path=locked_session.lake_storage_path,
                source_checksum=(
                    locked_session.file_hash or locked_session.s3_checksum_sha256 or ''
                ),
            )
            locked_session.dataset_version = version.version_label
            locked_session.save(update_fields=['dataset_version', 'updated_at'])
            return version

    @staticmethod
    def _require_pyarrow():
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise LakehouseIngestionError(
                'pyarrow is required to materialize silver Parquet artifacts.'
            ) from exc
        return pa, pq

    @staticmethod
    def _date_column(fieldnames: list[str], mapping_rule: dict | None) -> str | None:
        mapping_rule = mapping_rule or {}
        for key in ('orderDate', 'recordDate', 'date'):
            mapped = mapping_rule.get(key)
            if isinstance(mapped, str) and mapped in fieldnames:
                return mapped
            if isinstance(mapped, int) and 0 <= mapped < len(fieldnames):
                return fieldnames[mapped]

        for field in fieldnames:
            normalized = field.strip().lower().replace('_', ' ')
            if any(token in normalized for token in ('order date', 'created at', 'record date', 'ngày')):
                return field
        return None

    @staticmethod
    def _partition_date(value: object) -> str:
        raw = str(value or '').strip()
        yyyy_mm_dd = re.match(r'^(\d{4})-(\d{2})-(\d{2})', raw)
        if yyyy_mm_dd:
            return yyyy_mm_dd.group(0)
        dd_mm_yyyy = re.match(r'^(\d{2})/(\d{2})/(\d{4})', raw)
        if dd_mm_yyyy:
            return f'{dd_mm_yyyy.group(3)}-{dd_mm_yyyy.group(2)}-{dd_mm_yyyy.group(1)}'
        return 'unknown'

    @classmethod
    def _silver_prefix(cls, version: DatasetVersion) -> str:
        return (
            f'silver/workspace-{version.workspace_id}/'
            f'dataset-{version.version_number:06d}'
        )

    @classmethod
    def materialize_silver(
        cls,
        version: DatasetVersion,
        source_path: str,
        mapping_rule: dict | None,
        progress_callback=None,
    ) -> dict:
        """Write partitioned Parquet one bounded batch at a time.

        The source remains immutable. A retried version overwrites deterministic
        object keys and only publishes a completed manifest after every batch.
        """
        existing = version.manifest_json.get('silver', {}) if version.manifest_json else {}
        if existing.get('completed'):
            return existing
        if not source_path or not os.path.exists(source_path):
            raise LakehouseIngestionError('Local CSV source is unavailable for lake transform.')

        pa, pq = cls._require_pyarrow()
        prefix = cls._silver_prefix(version)
        batch_size = settings.INGESTION_CHUNK_ROW_SIZE
        partition_counts = Counter()
        rows_written = 0
        file_count = 0
        source_columns: list[str] = []
        total_rows = version.ingestion_session.total_rows or 0

        def flush(rows: list[dict], batch_number: int) -> int:
            nonlocal rows_written, file_count
            grouped = defaultdict(list)
            for row in rows:
                grouped[row['_partition_date']].append(row)
            written = 0
            for partition_date, partition_rows in grouped.items():
                for row in partition_rows:
                    row.pop('_partition_date', None)
                table = pa.Table.from_pylist(partition_rows)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix='.parquet',
                )
                temp_path = temp_file.name
                temp_file.close()
                try:
                    pq.write_table(table, temp_path, compression='snappy')
                    key = (
                        f'{prefix}/order_date={partition_date}/'
                        f'part-{batch_number:06d}-{written:03d}.parquet'
                    )
                    StorageBackend.save_processed_file(
                        temp_path,
                        key,
                        cls.SILVER_CONTENT_TYPE,
                    )
                finally:
                    try:
                        os.remove(temp_path)
                    except FileNotFoundError:
                        pass
                partition_counts[partition_date] += len(partition_rows)
                rows_written += len(partition_rows)
                file_count += 1
                written += 1
            if progress_callback:
                progress_callback({
                    'phase': 'SILVER',
                    'rowsProcessed': rows_written,
                    'totalRows': total_rows,
                    'batchNumber': batch_number + 1,
                    'filesWritten': file_count,
                    'partitionCounts': dict(sorted(partition_counts.items())),
                })
            return written

        with open(source_path, 'r', encoding='utf-8-sig', errors='replace', newline='') as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise LakehouseIngestionError('CSV source has no header row.')
            source_columns = list(reader.fieldnames)
            date_column = cls._date_column(source_columns, mapping_rule)
            batch: list[dict] = []
            batch_number = 0
            for raw_row in reader:
                row = {
                    key: (str(value).strip() if value is not None else None)
                    for key, value in raw_row.items()
                    if key is not None
                }
                row['workspace_id'] = str(version.workspace_id)
                row['dataset_version'] = version.version_label
                row['ingestion_session_id'] = str(version.ingestion_session_id)
                row['_partition_date'] = cls._partition_date(
                    raw_row.get(date_column) if date_column else None
                )
                batch.append(row)
                if len(batch) >= batch_size:
                    flush(batch, batch_number)
                    batch_number += 1
                    batch = []
            if batch:
                flush(batch, batch_number)

        manifest = {
            'completed': True,
            'schemaVersion': cls.MANIFEST_SCHEMA_VERSION,
            'prefix': StorageBackend.lake_uri(prefix),
            'rowsWritten': rows_written,
            'filesWritten': file_count,
            'partitionCounts': dict(sorted(partition_counts.items())),
            'sourceColumns': source_columns,
            'dateColumn': date_column,
            'materializedAt': timezone.now().isoformat(),
        }
        version.manifest_json = {**(version.manifest_json or {}), 'silver': manifest}
        version.silver_storage_path = StorageBackend.lake_uri(prefix)
        version.row_count = rows_written
        version.save(update_fields=[
            'manifest_json', 'silver_storage_path', 'row_count', 'updated_at',
        ])
        return manifest

    @classmethod
    def record_import_result(cls, version: DatasetVersion, result: dict) -> dict:
        """Persist compact import metrics before gold publication for retry safety."""
        summary = {
            key: result.get(key)
            for key in cls._IMPORT_SUMMARY_FIELDS
            if key in result
        }
        manifest = dict(version.manifest_json or {})
        manifest['import'] = {'completed': True, 'summary': summary}
        version.manifest_json = manifest
        version.valid_row_count = int(result.get('rows_valid') or 0)
        version.rejected_row_count = int(result.get('rows_rejected') or 0)
        version.save(update_fields=[
            'manifest_json', 'valid_row_count', 'rejected_row_count', 'updated_at',
        ])
        return summary

    @classmethod
    def completed_import_result(cls, version: DatasetVersion) -> dict | None:
        import_manifest = (version.manifest_json or {}).get('import', {})
        if import_manifest.get('completed'):
            return import_manifest.get('summary', {})
        return None

    @classmethod
    def materialize_gold(cls, version: DatasetVersion) -> dict:
        """Publish the small dashboard aggregate and reconciliation result."""
        import_summary = cls.completed_import_result(version)
        if import_summary is None:
            raise LakehouseIngestionError('Cannot publish gold before operational import succeeds.')

        silver = (version.manifest_json or {}).get('silver', {})
        reconciliation = {
            'sourceRows': version.row_count,
            'silverRows': int(silver.get('rowsWritten') or 0),
            'operationalValidRows': int(import_summary.get('rows_valid') or 0),
            'operationalRejectedRows': int(import_summary.get('rows_rejected') or 0),
            'status': (
                'MATCHED'
                if version.row_count == int(silver.get('rowsWritten') or 0)
                else 'MISMATCH'
            ),
        }
        payload = {
            'datasetVersion': version.version_label,
            'workspaceId': version.workspace_id,
            'parentVersion': version.parent_version.version_label if version.parent_version else None,
            'importType': version.import_type,
            'generatedAt': timezone.now().isoformat(),
            'silver': silver,
            'dashboardAggregate': import_summary,
            'reconciliation': reconciliation,
        }
        key = (
            f'gold/workspace-{version.workspace_id}/'
            f'dataset-{version.version_number:06d}/summary.json'
        )
        gold_path = StorageBackend.save_processed_bytes(
            json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            key,
        )
        manifest = dict(version.manifest_json or {})
        manifest['gold'] = {'completed': True, 'path': gold_path, 'reconciliation': reconciliation}
        version.manifest_json = manifest
        version.gold_storage_path = gold_path
        version.save(update_fields=['manifest_json', 'gold_storage_path', 'updated_at'])
        return payload

    @classmethod
    def materialize_dashboard_gold(cls, version: DatasetVersion) -> dict:
        """Build the active-dataset dashboard read model outside the request path.

        Risk assessments are scanned once after ML inference, then the dashboard
        reads the compact manifest snapshot instead of loading every SKU on a
        cache miss. The snapshot is tied to one immutable dataset version.
        """
        from supplyforge.models import SlowMovingRiskAssessment

        def as_positive_float(value) -> float:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return 0.0
            return parsed if parsed > 0 else 0.0

        def capital_exposure(evidence: dict) -> tuple[float, bool]:
            observed_capital = as_positive_float(evidence.get('capital_exposure_vnd'))
            if observed_capital:
                return observed_capital, True

            stock = as_positive_float(evidence.get('stock_quantity'))
            unit_cost = as_positive_float(evidence.get('unit_cost'))
            if stock and unit_cost:
                return stock * unit_cost, True

            sold_90d = as_positive_float(evidence.get('sold_90d'))
            return sold_90d * 150000, False

        risk_priority = {
            'CRITICAL': 1.0,
            'HIGH_RISK': 0.5,
        }
        counts = {
            'CRITICAL': 0,
            'HIGH_RISK': 0,
            'MEDIUM_RISK': 0,
            'LOW_RISK': 0,
        }
        total_skus = 0
        total_capital = 0.0
        at_risk_capital = 0.0
        aged_capital = 0.0
        has_observed_inventory = False
        top_candidates = []

        assessments = (
            SlowMovingRiskAssessment.objects
            .filter(session_id=version.ingestion_session_id)
            .only('sku', 'product_name', 'risk_class', 'risk_score', 'evidence')
            .iterator(chunk_size=1000)
        )
        for sequence, assessment in enumerate(assessments):
            total_skus += 1
            if assessment.risk_class in counts:
                counts[assessment.risk_class] += 1

            evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
            capital, is_observed = capital_exposure(evidence)
            total_capital += capital
            has_observed_inventory = has_observed_inventory or is_observed
            if assessment.risk_class in {'CRITICAL', 'HIGH_RISK'}:
                at_risk_capital += capital
            if as_positive_float(evidence.get('dsls')) > 90:
                aged_capital += capital

            priority = risk_priority.get(assessment.risk_class, 0.0)
            candidate = (
                priority,
                capital,
                sequence,
                {
                    'sku': assessment.sku,
                    'name': assessment.product_name,
                    'riskClass': assessment.risk_class,
                    'riskScore': assessment.risk_score,
                    'capitalExposureVnd': capital,
                    'daysInInventory': evidence.get('dsls', 0),
                },
            )
            if len(top_candidates) < 5:
                heapq.heappush(top_candidates, candidate)
            elif candidate[:3] > top_candidates[0][:3]:
                heapq.heapreplace(top_candidates, candidate)

        generated_at = timezone.now()
        summary = {
            'hasData': bool(total_skus),
            'totalSkus': total_skus,
            'criticalCount': counts['CRITICAL'],
            'highRiskCount': counts['HIGH_RISK'],
            'mediumRiskCount': counts['MEDIUM_RISK'],
            'lowRiskCount': counts['LOW_RISK'],
            'totalCapitalExposureVnd': total_capital,
            'atRiskCapitalVnd': at_risk_capital,
            'agedCapitalVnd': aged_capital,
            'capitalStatus': 'OBSERVED' if has_observed_inventory else (
                'ESTIMATED' if total_skus else 'NO_DATA'
            ),
            'topRiskSkus': [
                candidate[3]
                for candidate in sorted(
                    top_candidates,
                    key=lambda item: item[:3],
                    reverse=True,
                )
            ],
        }
        key = (
            f'gold/workspace-{version.workspace_id}/'
            f'dataset-{version.version_number:06d}/dashboard.json'
        )
        dashboard_path = StorageBackend.save_processed_bytes(
            json.dumps({
                'datasetVersion': version.version_label,
                'workspaceId': version.workspace_id,
                'generatedAt': generated_at.isoformat(),
                'summary': summary,
            }, ensure_ascii=False).encode('utf-8'),
            key,
        )

        manifest = dict(version.manifest_json or {})
        gold = dict(manifest.get('gold') or {})
        gold['dashboard'] = {
            'completed': True,
            'path': dashboard_path,
            'generatedAt': generated_at.isoformat(),
            'assessmentCount': total_skus,
            'summary': summary,
        }
        manifest['gold'] = gold
        version.manifest_json = manifest
        version.save(update_fields=['manifest_json', 'updated_at'])

        # Old cache keys must not keep serving the prior active dataset.
        from supplyforge.services.cache_policy import CachePolicy

        CachePolicy.bump_workspace_version(version.workspace_id)
        return summary

    @classmethod
    def promote(cls, version: DatasetVersion) -> DatasetVersion:
        """Atomically make a completed version current without deleting history."""
        with transaction.atomic():
            workspace = Workspace.objects.select_for_update().get(id=version.workspace_id)
            locked_version = DatasetVersion.objects.select_for_update().get(id=version.id)
            if locked_version.status in {
                DatasetVersion.STATUS_FAILED,
                DatasetVersion.STATUS_CANCELLED,
            }:
                raise LakehouseIngestionError('A failed or cancelled dataset version cannot be promoted.')
            now = timezone.now()
            DatasetVersion.objects.filter(
                workspace=workspace,
                status=DatasetVersion.STATUS_ACTIVE,
            ).exclude(id=locked_version.id).update(
                status=DatasetVersion.STATUS_SUPERSEDED,
                superseded_at=now,
            )
            locked_version.status = DatasetVersion.STATUS_ACTIVE
            locked_version.activated_at = now
            locked_version.data_as_of = now
            locked_version.save(update_fields=[
                'status', 'activated_at', 'data_as_of', 'updated_at',
            ])
            return locked_version

    @classmethod
    def mark_failed(cls, session: IngestionSession, message: str) -> None:
        """Leave prior active data untouched when a BUILDING version fails."""
        with transaction.atomic():
            version = (
                DatasetVersion.objects.select_for_update()
                .filter(
                    ingestion_session=session,
                    status=DatasetVersion.STATUS_BUILDING,
                )
                .first()
            )
            if version:
                manifest = dict(version.manifest_json or {})
                manifest['failure'] = {
                    'message': message[:512],
                    'at': timezone.now().isoformat(),
                }
                version.status = DatasetVersion.STATUS_FAILED
                version.manifest_json = manifest
                version.save(update_fields=['status', 'manifest_json', 'updated_at'])

    @classmethod
    def mark_cancelled(cls, session: IngestionSession, message: str) -> None:
        """Record a cooperative stop without invalidating a previous active version."""
        with transaction.atomic():
            version = (
                DatasetVersion.objects.select_for_update()
                .filter(
                    ingestion_session=session,
                    status=DatasetVersion.STATUS_BUILDING,
                )
                .first()
            )
            if version:
                manifest = dict(version.manifest_json or {})
                manifest['cancellation'] = {
                    'message': message[:512],
                    'at': timezone.now().isoformat(),
                }
                version.status = DatasetVersion.STATUS_CANCELLED
                version.manifest_json = manifest
                version.save(update_fields=['status', 'manifest_json', 'updated_at'])
