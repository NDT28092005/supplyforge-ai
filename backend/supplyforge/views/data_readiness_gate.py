"""
Data Readiness Gate V2 — Views (DAT-11)
========================================
REST API endpoints for Data Readiness Gate Certification, 5 Readiness Criteria,
Hard-Rule Primacy Evaluator, and Downstream Protection Guard status.

POST /api/v2/ingestion/sessions/<id>/evaluate-readiness     Evaluate Data Readiness Gate
GET  /api/v2/ingestion/sessions/<id>/readiness-gate-status Retrieve Readiness Gate Status & Protection Signal
"""

import json
import logging
import os
import sys

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import pandas as pd

from supplyforge.models import IngestionSession

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.data_readiness_gate import DataReadinessGate

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
def evaluate_data_readiness(request, session_id):
    """Evaluate Data Readiness Gate for an Ingestion Session."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    inc_csv_path = os.path.join(reports_dir, 'incremental_dataset.csv')
    norm_csv_path = os.path.join(reports_dir, 'normalized_dataset.csv')

    data_filepath = session.storage_path
    if os.path.exists(inc_csv_path):
        data_filepath = inc_csv_path
    elif os.path.exists(norm_csv_path):
        data_filepath = norm_csv_path

    df = None
    if data_filepath and os.path.exists(data_filepath):
        try:
            df = pd.read_csv(data_filepath, nrows=10000, encoding_errors='replace')
        except Exception:
            pass

    try:
        gate = DataReadinessGate(session_id=str(session.id))
        readiness_record = gate.evaluate_readiness(
            session_id=str(session.id),
            df=df,
            output_dir=reports_dir
        )

        session.data_readiness_json = readiness_record
        session.final_readiness_status = readiness_record['readinessStatus']
        session.readiness_score = readiness_record['readinessScore']
        session.save(update_fields=['data_readiness_json', 'final_readiness_status', 'readiness_score', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'readinessStatus': readiness_record['readinessStatus'],
            'readinessScore': readiness_record['readinessScore'],
            'record': readiness_record,
        })

    except Exception as e:
        logger.exception("Failed to evaluate Data Readiness Gate for session %s", session_id)
        return Response(
            {'error': f'Lỗi đánh giá Data Readiness Gate: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
@api_view(['GET'])
def get_readiness_gate_status(request, session_id):
    """Retrieve Data Readiness Gate Status & Downstream Interceptor payload."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    gate_file = os.path.join(reports_dir, 'data_readiness_gate.json')

    if os.path.exists(gate_file):
        try:
            with open(gate_file, 'r', encoding='utf-8') as f:
                record = json.load(f)
            return Response({'record': record})
        except Exception:
            pass

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.data_readiness_json:
            return Response({'record': session.data_readiness_json})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'record': None})
