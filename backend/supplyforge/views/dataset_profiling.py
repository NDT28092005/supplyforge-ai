"""
Dataset Profiling V2 — Views (Task 02)
========================================
REST API endpoints for Dataset Profiling execution and report retrieval.

POST /api/v2/ingestion/sessions/<id>/profile      Trigger full dataset profiling
GET  /api/v2/ingestion/sessions/<id>/profile      Get Dataset Profile JSON & Data Quality Report
GET  /api/v2/ingestion/sessions/<id>/sku-profiles Get paginated SKU Profiles
"""

import json
import logging
import os
import sys

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import pandas as pd

from supplyforge.models import IngestionSession
from supplyforge.services.storage_backend import StorageBackend

# Add project root to sys.path to import src.ingestion.dataset_profiler
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.dataset_profiler import DatasetProfiler

logger = logging.getLogger(__name__)


@api_view(['POST'])
def trigger_dataset_profiling(request, session_id):
    """Trigger full dataset profiling on an ingestion session's CSV file."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not session.storage_path or not StorageBackend.exists(session.storage_path):
        return Response(
            {'error': 'Tệp CSV của phiên này không tồn tại trên hệ thống.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Optional column mapping override from request body
    column_mapping = request.data.get('columnMapping') or {}

    try:
        # Load CSV with pandas
        with StorageBackend.localize(session.storage_path) as local_path:
            df = pd.read_csv(local_path, encoding_errors='replace')

        profiler = DatasetProfiler(
            df=df,
            column_mapping=column_mapping,
            session_id=str(session.id)
        )
        profile_result = profiler.run_full_profile()

        # Export standard reports to reports/ directory
        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        file_paths = profiler.export_reports(output_dir=reports_dir)

        # Update IngestionSession DB record
        readiness = profile_result.get('readiness', {})
        session.readiness_status = readiness.get('status', 'READY')
        session.readiness_score = readiness.get('readinessScore', 90.0)
        session.dataset_profile_json = profile_result
        session.save(update_fields=[
            'readiness_status', 'readiness_score', 'dataset_profile_json', 'updated_at'
        ])

        return Response({
            'sessionId': str(session.id),
            'status': session.status,
            'readiness': readiness,
            'reportsGenerated': file_paths,
            'profile': profile_result,
        })

    except Exception as e:
        logger.exception('Dataset profiling failed for session %s', session_id)
        return Response(
            {'error': f'Lỗi thực thi profiling: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_dataset_profile(request, session_id):
    """Retrieve stored Dataset Profile JSON for a session."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if not session.dataset_profile_json:
        # If profile not yet generated, attempt to generate on the fly
        if session.storage_path and StorageBackend.exists(session.storage_path):
            with StorageBackend.localize(session.storage_path) as local_path:
                df = pd.read_csv(local_path, encoding_errors='replace')
            profiler = DatasetProfiler(df=df, session_id=str(session.id))
            profile_result = profiler.run_full_profile()
            reports_dir = os.path.join(PROJECT_ROOT, 'reports')
            profiler.export_reports(output_dir=reports_dir)

            readiness = profile_result.get('readiness', {})
            session.readiness_status = readiness.get('status', 'READY')
            session.readiness_score = readiness.get('readinessScore', 90.0)
            session.dataset_profile_json = profile_result
            session.save(update_fields=[
                'readiness_status', 'readiness_score', 'dataset_profile_json', 'updated_at'
            ])
            return Response(profile_result)

        return Response(
            {'error': 'Phiên ingestion này chưa được chạy Dataset Profiling.'},
            status=status.HTTP_404_NOT_FOUND
        )

    return Response(session.dataset_profile_json)


@api_view(['GET'])
def get_sku_profiles(request, session_id):
    """Retrieve paginated/searchable SKU profiles for a session."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    search = request.GET.get('search', '').strip().lower()
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('pageSize', 20))

    # Read from reports/sku_profile.parquet or reports/sku_profile.csv or generate on the fly
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    parquet_path = os.path.join(reports_dir, 'sku_profile.parquet')
    csv_path = os.path.join(reports_dir, 'sku_profile.csv')

    sku_df = pd.DataFrame()
    if os.path.exists(parquet_path):
        try:
            sku_df = pd.read_parquet(parquet_path)
        except Exception:
            pass

    if sku_df.empty and os.path.exists(csv_path):
        sku_df = pd.read_csv(csv_path)

    if sku_df.empty and session.storage_path and StorageBackend.exists(session.storage_path):
        with StorageBackend.localize(session.storage_path) as local_path:
            df = pd.read_csv(local_path, encoding_errors='replace')
        profiler = DatasetProfiler(df=df, session_id=str(session.id))
        profiler.run_full_profile()
        profiler.export_reports(output_dir=reports_dir)
        sku_df = profiler._last_sku_df

    if sku_df.empty:
        return Response({'total': 0, 'page': page, 'pageSize': page_size, 'items': []})

    # Search filter
    if search:
        mask = (
            sku_df['sku'].astype(str).str.lower().str.contains(search) |
            sku_df['product_name'].astype(str).str.lower().str.contains(search)
        )
        sku_df = sku_df[mask]

    total_count = len(sku_df)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    sliced = sku_df.iloc[start_idx:end_idx].to_dict(orient='records')

    return Response({
        'total': total_count,
        'page': page,
        'pageSize': page_size,
        'totalPages': (total_count + page_size - 1) // page_size if page_size > 0 else 1,
        'items': sliced,
    })
