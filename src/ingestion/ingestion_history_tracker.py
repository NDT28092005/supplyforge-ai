"""
Ingestion History & Audit Trail Engine — Module 01 Data Ingestion (DAT-09)
=============================================================================
Manages end-to-end processing history, lifecycle stage timelines, processing statistics,
data time range metadata, dataset version lineage (reproducibility), error logs, and audit trails.

Outputs standard reports to:
  - reports/ingestion_history.json
  - reports/ingestion_processing_log.json
  - reports/ingestion_statistics.json
  - reports/ingestion_error_log.json
  - reports/dataset_version_history.json
  - reports/ingestion_audit_log.json
"""

import json
import os
import random
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Union


class IngestionHistoryTracker:
    """Ingestion History, Audit Trail & Lineage Engine (DAT-09)."""

    LIFECYCLE_STAGES = [
        'UPLOADED',
        'PROFILING',
        'MAPPING',
        'SCHEMA_VALIDATION',
        'QUALITY_VALIDATION',
        'SKU_NORMALIZATION',
        'MERGING',
        'COMPLETED'
    ]

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or 'default_session'

    @staticmethod
    def generate_ingestion_id() -> str:
        """Generate unique ingestion ID in format ING-YYYYMMDD-XXXXX."""
        today_str = datetime.now().strftime('%Y%m%d')
        seq = random.randint(10000, 99999)
        return f"ING-{today_str}-{seq}"

    # ── Main Event Recording Pipeline ──────────────────────────────────

    def record_ingestion_event(
        self,
        session_id: str,
        stage: str,
        status: str,
        filename: str,
        ingestion_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        stats: Optional[Dict[str, Any]] = None,
        time_info: Optional[Dict[str, Any]] = None,
        version_info: Optional[Dict[str, Any]] = None,
        error_info: Optional[Dict[str, Any]] = None,
        audit_action: Optional[str] = None,
        user: str = 'merchant_default',
        output_dir: str = 'reports/'
    ) -> Dict[str, Any]:
        """Record or update an ingestion session event and persist 6 history artifacts."""
        ing_id = ingestion_id or self.generate_ingestion_id()
        now_iso = datetime.now().isoformat()

        # Load existing history files if available
        os.makedirs(output_dir, exist_ok=True)
        history_list = self._load_json_file(os.path.join(output_dir, 'ingestion_history.json'))
        proc_logs = self._load_json_file(os.path.join(output_dir, 'ingestion_processing_log.json'))
        error_logs = self._load_json_file(os.path.join(output_dir, 'ingestion_error_log.json'))
        ver_history = self._load_json_file(os.path.join(output_dir, 'dataset_version_history.json'))
        audit_logs = self._load_json_file(os.path.join(output_dir, 'ingestion_audit_log.json'))

        # Find or create session history record
        session_record = None
        for item in history_list:
            if item.get('sessionId') == session_id or item.get('ingestionId') == ing_id:
                session_record = item
                break

        if not session_record:
            session_record = {
                'ingestionId': ing_id,
                'sessionId': session_id,
                'datasetId': dataset_id or 'Shopee_Default_Dataset',
                'filename': filename,
                'uploadedAt': now_iso,
                'uploadedBy': user,
                'currentStage': stage,
                'status': status,
                'datasetVersion': (version_info or {}).get('currentVersion', 'v1.0'),
                'timeline': [],
                'statistics': {},
                'timeRange': {},
            }
            history_list.insert(0, session_record)

        # Update session record attributes
        session_record['currentStage'] = stage
        session_record['status'] = status
        session_record['lastUpdatedAt'] = now_iso
        if version_info and 'currentVersion' in version_info:
            session_record['datasetVersion'] = version_info['currentVersion']

        # Append timeline stage transition
        session_record['timeline'].append({
            'stage': stage,
            'status': status,
            'timestamp': now_iso,
        })

        proc_logs.append({
            'ingestionId': ing_id,
            'sessionId': session_id,
            'stage': stage,
            'status': status,
            'timestamp': now_iso,
            'details': stats or {},
        })

        # Update statistics if provided
        if stats:
            session_record['statistics'] = {
                'totalRecords': stats.get('totalRecords', 0),
                'validRecords': stats.get('validRecords', 0),
                'invalidRecords': stats.get('invalidRecords', 0),
                'newRecords': stats.get('inserted', stats.get('newRecords', 0)),
                'updatedRecords': stats.get('updated', stats.get('updatedRecords', 0)),
                'duplicateRecords': stats.get('duplicatesSkipped', stats.get('duplicateRecords', 0)),
                'rejectedRecords': stats.get('quarantined', stats.get('rejectedRecords', 0)),
                'newSkus': stats.get('newSkus', 0),
                'matchedSkus': stats.get('matchedSkus', 0),
                'reviewRequiredSkus': stats.get('reviewRequiredSkus', 0),
            }

        # Update time range info if provided
        if time_info:
            session_record['timeRange'] = {
                'dataMinDate': time_info.get('dataMinDate', time_info.get('newMinDate')),
                'dataMaxDate': time_info.get('dataMaxDate', time_info.get('newMaxDate')),
                'previousMaxDate': time_info.get('existingMaxDate'),
                'overlapStatus': time_info.get('overlapStatus'),
                'overlapDays': time_info.get('overlapDays', 0),
            }

        # Record error log if failed/rejected
        if status in ('FAILED', 'REJECTED') or error_info:
            err_entry = {
                'ingestionId': ing_id,
                'sessionId': session_id,
                'filename': filename,
                'errorStage': stage,
                'errorCode': (error_info or {}).get('code', f"ERR_{stage}"),
                'errorMessage': (error_info or {}).get('message', f"Xử lý thất bại tại bước {stage}"),
                'failedRecords': (error_info or {}).get('failedRecords', 0),
                'timestamp': now_iso,
            }
            error_logs.append(err_entry)
            session_record['errorDetails'] = err_entry

        # Record version lineage
        if version_info:
            ver_entry = {
                'version': version_info.get('currentVersion', 'v1.0'),
                'ingestionId': ing_id,
                'sessionId': session_id,
                'filename': filename,
                'createdAt': now_iso,
                'totalRecords': session_record['statistics'].get('totalRecords', 0),
            }

            # Avoid duplicate version entries
            if not any(v.get('version') == ver_entry['version'] and v.get('ingestionId') == ing_id for v in ver_history):
                ver_history.append(ver_entry)

        # Record audit trail action
        action_name = audit_action or stage
        audit_entry = {
            'ingestionId': ing_id,
            'sessionId': session_id,
            'user': user,
            'action': action_name,
            'datasetVersion': session_record['datasetVersion'],
            'timestamp': now_iso,
            'status': status,
        }
        audit_logs.append(audit_entry)

        # Export 6 report artifacts
        exported_files = self.export_artifacts(
            history_list=history_list,
            proc_logs=proc_logs,
            statistics=session_record['statistics'],
            error_logs=error_logs,
            ver_history=ver_history,
            audit_logs=audit_logs,
            output_dir=output_dir
        )

        return {
            'ingestionId': ing_id,
            'sessionId': session_id,
            'currentStage': stage,
            'status': status,
            'sessionRecord': session_record,
            'reportsGenerated': exported_files,
        }

    # ── Exporter: Save 6 Reports ──────────────────────────────────────

    def export_artifacts(
        self,
        history_list: List[Dict[str, Any]],
        proc_logs: List[Dict[str, Any]],
        statistics: Dict[str, Any],
        error_logs: List[Dict[str, Any]],
        ver_history: List[Dict[str, Any]],
        audit_logs: List[Dict[str, Any]],
        output_dir: str = 'reports/'
    ) -> Dict[str, str]:
        """Export all 6 standard DAT-09 artifacts to reports/."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. ingestion_history.json
        hist_path = os.path.join(output_dir, 'ingestion_history.json')
        with open(hist_path, 'w', encoding='utf-8') as f:
            json.dump(history_list, f, indent=2, ensure_ascii=False)

        # 2. ingestion_processing_log.json
        proc_path = os.path.join(output_dir, 'ingestion_processing_log.json')
        with open(proc_path, 'w', encoding='utf-8') as f:
            json.dump(proc_logs, f, indent=2, ensure_ascii=False)

        # 3. ingestion_statistics.json
        stat_path = os.path.join(output_dir, 'ingestion_statistics.json')
        with open(stat_path, 'w', encoding='utf-8') as f:
            json.dump(statistics, f, indent=2, ensure_ascii=False)

        # 4. ingestion_error_log.json
        err_path = os.path.join(output_dir, 'ingestion_error_log.json')
        with open(err_path, 'w', encoding='utf-8') as f:
            json.dump(error_logs, f, indent=2, ensure_ascii=False)

        # 5. dataset_version_history.json
        ver_path = os.path.join(output_dir, 'dataset_version_history.json')
        with open(ver_path, 'w', encoding='utf-8') as f:
            json.dump(ver_history, f, indent=2, ensure_ascii=False)

        # 6. ingestion_audit_log.json
        audit_path = os.path.join(output_dir, 'ingestion_audit_log.json')
        with open(audit_path, 'w', encoding='utf-8') as f:
            json.dump(audit_logs, f, indent=2, ensure_ascii=False)

        return {
            'ingestion_history': hist_path,
            'ingestion_processing_log': proc_path,
            'ingestion_statistics': stat_path,
            'ingestion_error_log': err_path,
            'dataset_version_history': ver_path,
            'ingestion_audit_log': audit_path,
        }

    # ── Internal Helper: Load JSON File ──────────────────────────────

    @staticmethod
    def _load_json_file(file_path: str) -> List[Dict[str, Any]]:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        return content
                    elif isinstance(content, dict):
                        return [content]
            except Exception:
                pass
        return []
