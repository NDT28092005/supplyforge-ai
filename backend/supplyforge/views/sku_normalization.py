"""
SKU Normalization V2 — Views (DAT-06)
======================================
REST API endpoints for SKU normalization, candidate match review, merchant merge/undo,
and master SKU catalog retrieval.

POST /api/v2/ingestion/sessions/<id>/normalize-skus  Execute SKU normalization
GET  /api/v2/ingestion/sessions/<id>/sku-candidates  Get REVIEW_REQUIRED candidate matches
POST /api/v2/ingestion/sessions/<id>/sku-merge       Merchant merge SKUs
POST /api/v2/ingestion/sessions/<id>/sku-undo-merge  Undo previous merge decision
GET  /api/v2/ingestion/sessions/<id>/sku-master      Get SKU master catalog
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

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.sku_normalizer import SkuNormalizer
from src.ingestion.column_mapper import ColumnMapper

logger = logging.getLogger(__name__)


@api_view(['POST'])
def trigger_sku_normalization(request, session_id):
    """Execute DAT-06 SKU Normalization pipeline on session CSV."""
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

    mapping_result = session.column_mapping_json
    if not mapping_result:
        headers = session.headers_json or []
        preview_rows = session.preview_rows_json or []
        mapper = ColumnMapper(session_id=str(session.id))
        mapping_result = mapper.map_columns(headers=headers, sample_rows=preview_rows)
        session.column_mapping_json = mapping_result

    try:
        with StorageBackend.localize(session.storage_path) as local_path:
            df = pd.read_csv(local_path, nrows=50000, encoding_errors='replace')

        normalizer = SkuNormalizer(session_id=str(session.id))
        summary_result = normalizer.normalize_dataset(df, mapping_result)

        reports_dir = os.path.join(PROJECT_ROOT, 'reports')
        generated_files = normalizer.export_artifacts(summary_result, output_dir=reports_dir)

        session.canonical_sku_count = summary_result.get('totalCanonicalSkus', 0)
        session.sku_normalization_json = summary_result
        session.save(update_fields=['canonical_sku_count', 'sku_normalization_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'totalOriginalSkus': summary_result['totalOriginalSkus'],
            'totalCanonicalSkus': summary_result['totalCanonicalSkus'],
            'autoMergedCount': summary_result['autoMergedCount'],
            'pendingReviewCount': summary_result['pendingReviewCandidatesCount'],
            'reportsGenerated': generated_files,
            'summary': summary_result,
        })

    except Exception as e:
        logger.exception("SKU normalization failed for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi SKU Normalization: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_sku_candidates(request, session_id):
    """Retrieve pending REVIEW_REQUIRED candidate merge pairs."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    candidates_file = os.path.join(reports_dir, 'sku_match_candidates.json')

    if os.path.exists(candidates_file):
        with open(candidates_file, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
        return Response({'candidates': candidates})

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.sku_normalization_json:
            return Response({'candidates': session.sku_normalization_json.get('candidates', [])})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'candidates': []})


@api_view(['POST'])
def merchant_merge_sku(request, session_id):
    """Merchant confirms merging a child SKU into a canonical SKU."""
    canonical_sku_id = request.data.get('canonicalSkuId')
    child_sku_id = request.data.get('childSkuId')
    candidate_pair_id = request.data.get('candidatePairId')

    if not canonical_sku_id or not child_sku_id:
        return Response(
            {'error': 'Vui lòng truyền đủ canonicalSkuId và childSkuId.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    normalizer = SkuNormalizer(session_id=session_id)
    audit_entry = normalizer.handle_merchant_merge(canonical_sku_id, child_sku_id, candidate_pair_id)

    # Save to audit log on disk
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    audit_file = os.path.join(reports_dir, 'sku_merge_audit_log.json')
    logs = []
    if os.path.exists(audit_file):
        try:
            with open(audit_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            pass
    logs.append(audit_entry)
    with open(audit_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

    return Response({
        'sessionId': session_id,
        'message': 'Đã gộp sản phẩm thành công.',
        'auditEntry': audit_entry,
    })


@api_view(['POST'])
def merchant_undo_sku_merge(request, session_id):
    """Merchant undoes a previous SKU merge decision."""
    canonical_sku_id = request.data.get('canonicalSkuId')
    child_sku_id = request.data.get('childSkuId')

    if not canonical_sku_id or not child_sku_id:
        return Response(
            {'error': 'Vui lòng truyền đủ canonicalSkuId và childSkuId.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    normalizer = SkuNormalizer(session_id=session_id)
    audit_entry = normalizer.handle_merchant_undo(canonical_sku_id, child_sku_id)

    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    audit_file = os.path.join(reports_dir, 'sku_merge_audit_log.json')
    logs = []
    if os.path.exists(audit_file):
        try:
            with open(audit_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            pass
    logs.append(audit_entry)
    with open(audit_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

    return Response({
        'sessionId': session_id,
        'message': 'Đã hoàn tác gộp sản phẩm thành công.',
        'auditEntry': audit_entry,
    })


@api_view(['GET'])
def get_sku_master_catalog(request, session_id):
    """Retrieve master SKU catalog of canonical SKUs."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sku_master_file = os.path.join(reports_dir, 'sku_master.json')

    if os.path.exists(sku_master_file):
        with open(sku_master_file, 'r', encoding='utf-8') as f:
            sku_master = json.load(f)
        return Response({'skuMaster': sku_master})

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.sku_normalization_json:
            return Response({'skuMaster': session.sku_normalization_json.get('skuMaster', [])})
    except IngestionSession.DoesNotExist:
        pass

    return Response({'skuMaster': []})
