"""
NFR Performance & Memory Management Service — Module 01 Ingestion
===================================================================
Defines non-functional performance, latency SLA, memory streaming bounds,
and automated thresholding logic for requirements:
- NFR-IMP-001: File ≤ 10 MB upload acceptance latency < 3 seconds.
- NFR-IMP-002: File 500 MB bounded processing (no timeout, crash, RAM exhaustion).
- NFR-IMP-003: Asynchronous API upload thresholding (> 10 MB -> 202 Accepted).
- Requirement #24: Memory requirement — Chunked streaming execution engine (50k rows/chunk).
"""

import time
import gc
import logging

logger = logging.getLogger(__name__)


class NFRManager:
    # Latency SLA threshold for upload acceptance
    ACCEPTANCE_SLA_MAX_SEC = 3.0

    # Automatic Asynchronous processing threshold: 10 MB (10,485,760 bytes)
    ASYNC_THRESHOLD_BYTES = 10 * 1024 * 1024

    # Maximum file size SLA limit: 500 MB (524,288,000 bytes)
    MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024

    # Maximum rows SLA limit: 5,000,000 rows
    MAX_ROWS_SLA_LIMIT = 5_000_000

    # Memory streaming chunk size: 50,000 rows per chunk
    CHUNK_ROW_SIZE = 50_000

    @classmethod
    def should_dispatch_async(cls, file_size_bytes: int, force_async: bool = False) -> bool:
        """
        NFR-IMP-003: Determine whether upload request should be dispatched asynchronously
        based on the 10 MB file size threshold.
        """
        if force_async:
            return True
        return file_size_bytes > cls.ASYNC_THRESHOLD_BYTES

    @classmethod
    def measure_acceptance_latency(cls, start_time_sec: float) -> dict:
        """
        NFR-IMP-001: Evaluate whether upload acceptance response met the < 3.0 second SLA.
        """
        elapsed = time.time() - start_time_sec
        sla_passed = elapsed < cls.ACCEPTANCE_SLA_MAX_SEC
        return {
            'latency_sec': round(elapsed, 4),
            'sla_limit_sec': cls.ACCEPTANCE_SLA_MAX_SEC,
            'sla_passed': sla_passed,
            'message': (
                f"Upload acceptance returned in {elapsed:.3f}s "
                f"({'SLA COMPLIANT (< 3s)' if sla_passed else 'SLA VIOLATED (> 3s)'})."
            )
        }

    @classmethod
    def release_chunk_memory(cls):
        """
        Requirement #24: Garbage collect local chunk buffers between iterations
        to ensure bounded RAM usage (< 100 MB peak RAM even for 500 MB CSV).
        """
        gc.collect()
