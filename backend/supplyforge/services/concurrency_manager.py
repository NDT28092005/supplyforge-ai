import logging
from django.db import transaction
from supplyforge.models import IngestionSession

logger = logging.getLogger(__name__)


class ImportConcurrencyManager:
    """
    IR-018 Concurrent Import Policy Manager.
    Supports:
    - Queueing Policy (Option 2 - Recommended): Places concurrent upload in QUEUED status.
    - Reject Policy (Option 1): Rejects with IMPORT_ALREADY_RUNNING.
    """

    @staticmethod
    def evaluate_and_register_session(session, policy='queue'):
        """
        Evaluate concurrency status for session workspace.
        If another active import is running:
          - 'queue': Mark session as QUEUED and return queued payload.
          - 'reject': Mark session as FAILED and return reject payload.
        """
        workspace = session.workspace

        # Check active processing sessions for workspace (excluding current session)
        active_sessions = IngestionSession.objects.filter(
            workspace=workspace,
            status__in=['PROCESSING', 'PROFILING', 'UPLOADING']
        ).exclude(id=session.id)

        if active_sessions.exists():
            active_session = active_sessions.first()
            if policy == 'reject':
                session.status = 'FAILED'
                session.error_message = 'IMPORT_ALREADY_RUNNING: Một tiến trình nạp tệp khác đang chạy trên hệ thống.'
                session.save(update_fields=['status', 'error_message', 'updated_at'])
                return {
                    'status': 'REJECTED',
                    'error_code': 'IMPORT_ALREADY_RUNNING',
                    'message': 'IMPORT_ALREADY_RUNNING: Một tiến trình nạp tệp khác đang được xử lý.',
                    'activeSessionId': str(active_session.id)
                }

            # Option 2 (Queue Policy)
            session.status = 'QUEUED'
            session.error_message = (
                f"Một tệp khác ({active_session.original_filename}) đang được xử lý. "
                f"Tệp của bạn đã được đưa vào hàng đợi (QUEUED)."
            )
            session.save(update_fields=['status', 'error_message', 'updated_at'])
            return {
                'status': 'QUEUED',
                'sessionId': str(session.id),
                'message': f"Tệp {session.original_filename} đã được xếp vào hàng đợi (QUEUED) thành công.",
                'activeSessionId': str(active_session.id),
                'queuePosition': active_sessions.count()
            }

        return {
            'status': 'PROCESSING',
            'sessionId': str(session.id),
            'message': 'Sẵn sàng xử lý tệp (Processing).'
        }

    @staticmethod
    def dequeue_next_session(workspace_id):
        """
        Find the earliest QUEUED session for workspace and transition to PROCESSING.
        """
        with transaction.atomic():
            queued_session = (
                IngestionSession.objects.select_for_update()
                .filter(workspace_id=workspace_id, status='QUEUED')
                .order_by('created_at')
                .first()
            )
            if queued_session:
                queued_session.status = 'PROCESSING'
                queued_session.error_message = None
                queued_session.save(update_fields=['status', 'error_message', 'updated_at'])
                logger.info(f"Dequeued session {queued_session.id} for processing.")
                return queued_session

        return None
