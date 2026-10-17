"""
Slow-Moving Analytics V2 — Views (M2-01)
========================================
REST API endpoints for Slow-Moving Risk Feature Engineering (M2-01).
Calculates deterministic demand features as of decision cutoff t0.

POST /api/v2/analytics/sessions/<id>/compute-features Compute M2-01 SKU Feature Matrix
GET  /api/v2/analytics/sessions/<id>/features         Retrieve Feature Matrix & Demand Pattern Breakdown
GET  /api/v2/analytics/sessions/<id>/feature-quality  Retrieve Feature Quality Audit Report
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

from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.ingestion.data_readiness_gate import DataReadinessError

logger = logging.getLogger(__name__)


@api_view(['POST'])
def compute_slow_moving_features(request, session_id):
    """Compute M2-01 SKU Demand Features as of decision cutoff t0."""
    try:
        session = IngestionSession.objects.get(id=session_id)
    except IngestionSession.DoesNotExist:
        return Response(
            {'error': 'Không tìm thấy phiên ingestion.'},
            status=status.HTTP_404_NOT_FOUND
        )

    decision_date = request.data.get('decisionDate') or request.GET.get('decisionDate')

    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    inc_csv_path = os.path.join(reports_dir, 'incremental_dataset.csv')
    norm_csv_path = os.path.join(reports_dir, 'normalized_dataset.csv')

    data_filepath = session.storage_path
    if os.path.exists(inc_csv_path):
        data_filepath = inc_csv_path
    elif os.path.exists(norm_csv_path):
        data_filepath = norm_csv_path

    if not data_filepath or not StorageBackend.exists(data_filepath):
        return Response(
            {'error': 'Dữ liệu giao dịch không tồn tại.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with StorageBackend.localize(data_filepath) as local_path:
            df = pd.read_csv(local_path, nrows=50000, encoding_errors='replace')
        engineer = SlowMovingFeatureEngineer(session_id=str(session.id))
        result = engineer.compute_sku_features(
            df=df,
            decision_date=decision_date,
            session_id=str(session.id),
            output_dir=reports_dir,
            data_dir=data_dir
        )

        session.slow_moving_features_json = result
        session.save(update_fields=['slow_moving_features_json', 'updated_at'])

        return Response({
            'sessionId': str(session.id),
            'decisionDate': result['decisionDate'],
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'qualityReport': result['qualityReport'],
            'featureMatrixSample': result['featureMatrix'][:20],
        })

    except DataReadinessError as dre:
        logger.warning("Readiness Gate intercepted feature computation for session %s: %s", session_id, str(dre))
        return Response(
            {'error': f'Cổng Data Readiness Gate đã chặn tính toán: {str(dre)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to compute M2-01 features for session %s", session_id)
        return Response(
            {'error': f'Lỗi tính toán Feature Engineering M2-01: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_slow_moving_features(request, session_id):
    """Retrieve computed M2-01 SKU Feature Matrix."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    summary_path = os.path.join(reports_dir, 'feature_engineering_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.slow_moving_features_json:
            return Response(session.slow_moving_features_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None, 'featureMatrix': []})


@api_view(['GET'])
def get_feature_quality_report(request, session_id):
    """Retrieve Feature Quality Validation Report."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    qual_path = os.path.join(reports_dir, 'feature_quality_report.json')

    if os.path.exists(qual_path):
        try:
            with open(qual_path, 'r', encoding='utf-8') as f:
                qual_report = json.load(f)
            return Response({'qualityReport': qual_report})
        except Exception:
            pass

    return Response({'qualityReport': None})


# ── M2-02 Demand Pattern Classification Views ─────────────────────────

@api_view(['POST'])
def classify_demand_patterns(request, session_id):
    """Classify SKU Demand Patterns (M2-02) based on M2-01 features."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    # Load M2-01 features from session or parquet/csv
    features_data = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.slow_moving_features_json:
            features_data = session.slow_moving_features_json.get('featureMatrix')
    except IngestionSession.DoesNotExist:
        session = None

    features_df = None
    if features_data:
        features_df = pd.DataFrame(features_data)
    else:
        parquet_path = os.path.join(data_dir, 'slow_moving_features.parquet')
        csv_path = os.path.join(data_dir, 'slow_moving_features.csv')
        if os.path.exists(parquet_path):
            try:
                features_df = pd.read_parquet(parquet_path)
            except Exception:
                pass
        if features_df is None and os.path.exists(csv_path):
            try:
                features_df = pd.read_csv(csv_path)
            except Exception:
                pass

    if features_df is None or features_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy tập đặc trưng M2-01. Vui lòng thực thi M2-01 Feature Engineering trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        classifier = DemandPatternClassifier(session_id=session_id)
        result = classifier.classify_demand_patterns(
            features_df=features_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.demand_pattern_json = result
            session.save(update_fields=['demand_pattern_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'recordsSample': result['demandPatternRecords'][:20],
        })

    except Exception as e:
        logger.exception("Failed to classify M2-02 demand patterns for session %s", session_id)
        return Response(
            {'error': f'Lỗi phân loại Demand Pattern M2-02: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_demand_patterns(request, session_id):
    """Retrieve SKU Demand Pattern Classification records."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    summary_path = os.path.join(reports_dir, 'demand_pattern_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.demand_pattern_json:
            return Response(session.demand_pattern_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None, 'demandPatternRecords': []})


@api_view(['GET'])
def get_demand_pattern_summary(request, session_id):
    """Retrieve Demand Pattern Distribution Summary Report."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    summary_path = os.path.join(reports_dir, 'demand_pattern_summary.json')

    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


# ── M2-03 Slow-Moving Risk Feature Assembly Views ─────────────────────

@api_view(['POST'])
def assemble_risk_features(request, session_id):
    """Assemble Slow-Moving Risk Feature Matrix (M2-03) from M2-01 and M2-02."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    # Load M2-01 features
    features_m201_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.slow_moving_features_json:
            m201_data = session.slow_moving_features_json.get('featureMatrix')
            if m201_data:
                features_m201_df = pd.DataFrame(m201_data)
    except IngestionSession.DoesNotExist:
        session = None

    if features_m201_df is None:
        p1 = os.path.join(data_dir, 'slow_moving_features.parquet')
        c1 = os.path.join(data_dir, 'slow_moving_features.csv')
        if os.path.exists(p1):
            try:
                features_m201_df = pd.read_parquet(p1)
            except Exception:
                pass
        if features_m201_df is None and os.path.exists(c1):
            try:
                features_m201_df = pd.read_csv(c1)
            except Exception:
                pass

    if features_m201_df is None or features_m201_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy tập đặc trưng M2-01. Vui lòng thực thi M2-01 Feature Engineering trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Load M2-02 patterns
    patterns_m202_df = None
    if session and session.demand_pattern_json:
        m202_data = session.demand_pattern_json.get('demandPatternRecords')
        if m202_data:
            patterns_m202_df = pd.DataFrame(m202_data)

    if patterns_m202_df is None:
        p2 = os.path.join(data_dir, 'demand_pattern_features.parquet')
        c2 = os.path.join(data_dir, 'demand_pattern_features.csv')
        if os.path.exists(p2):
            try:
                patterns_m202_df = pd.read_parquet(p2)
            except Exception:
                pass
        if patterns_m202_df is None and os.path.exists(c2):
            try:
                patterns_m202_df = pd.read_csv(c2)
            except Exception:
                pass

    try:
        assembler = RiskFeatureAssembler(session_id=session_id)
        result = assembler.assemble_risk_features(
            features_m201_df=features_m201_df,
            patterns_m202_df=patterns_m202_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.risk_features_json = result
            session.save(update_fields=['risk_features_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'featureRegistry': result['featureRegistry'],
            'riskFeatureSample': result['riskFeatureRecords'][:20],
        })

    except FeatureLeakageError as fle:
        logger.error("Automated Leakage Inspector caught leakage for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Phát hiện rò rỉ dữ liệu tương lai (Feature Leakage Error): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to assemble M2-03 risk features for session %s", session_id)
        return Response(
            {'error': f'Lỗi hợp nhất Risk Feature M2-03: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_features(request, session_id):
    """Retrieve Assembled Slow-Moving Risk Feature Matrix."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    reg_path = os.path.join(reports_dir, 'risk_feature_registry.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_features_json:
            return Response(session.risk_features_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(reg_path):
        try:
            with open(reg_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            return Response({'featureRegistry': registry})
        except Exception:
            pass

    return Response({'featureRegistry': [], 'riskFeatureRecords': []})


@api_view(['GET'])
def get_feature_registry(request, session_id):
    """Retrieve Official Risk Feature Registry Schema & Metadata."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    reg_path = os.path.join(reports_dir, 'risk_feature_registry.json')

    if os.path.exists(reg_path):
        try:
            with open(reg_path, 'r', encoding='utf-8') as f:
                registry = json.load(f)
            return Response({'featureRegistry': registry})
        except Exception:
            pass

    return Response({'featureRegistry': []})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


# ── M2-04 Slow-Moving Risk Feature Engineering Views ───────────────────

@api_view(['POST'])
def build_risk_feature_matrix(request, session_id):
    """Build & Profile Canonical Slow-Moving Risk Feature Matrix (M2-04)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    risk_features_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_features_json:
            recs = session.risk_features_json.get('riskFeatureRecords')
            if recs:
                risk_features_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if risk_features_df is None or risk_features_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_risk_features.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_risk_features.csv')
        if os.path.exists(p_path):
            try:
                risk_features_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if risk_features_df is None and os.path.exists(c_path):
            try:
                risk_features_df = pd.read_csv(c_path)
            except Exception:
                pass

    if risk_features_df is None or risk_features_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy tập đặc trưng M2-03. Vui lòng thực thi M2-03 Risk Feature Assembly trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = RiskFeatureMatrixEngine(session_id=session_id)
        result = engine.build_risk_feature_matrix(
            risk_features_m203_df=risk_features_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.risk_feature_matrix_json = result
            session.save(update_fields=['risk_feature_matrix_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'featureDictionary': result['featureDictionary'],
            'leakageAudit': result['leakageAudit'],
            'correlationSummary': result['correlationSummary'],
            'matrixSample': result['riskFeatureMatrixRecords'][:20],
        })

    except FeatureLeakageError as fle:
        logger.error("Automated Leakage Audit caught forbidden features for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Phát hiện rò rỉ dữ liệu (Feature Leakage Error): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to build M2-04 risk feature matrix for session %s", session_id)
        return Response(
            {'error': f'Lỗi xây dựng Risk Feature Matrix M2-04: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_feature_matrix(request, session_id):
    """Retrieve Canonical Risk Feature Matrix."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    dict_path = os.path.join(reports_dir, 'feature_dictionary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_feature_matrix_json:
            return Response(session.risk_feature_matrix_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(dict_path):
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                dictionary = json.load(f)
            return Response({'featureDictionary': dictionary})
        except Exception:
            pass

    return Response({'featureDictionary': [], 'riskFeatureMatrixRecords': []})


@api_view(['GET'])
def get_feature_dictionary(request, session_id):
    """Retrieve Official Feature Dictionary Metadata."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    dict_path = os.path.join(reports_dir, 'feature_dictionary.json')

    if os.path.exists(dict_path):
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                dictionary = json.load(f)
            return Response({'featureDictionary': dictionary})
        except Exception:
            pass

    return Response({'featureDictionary': []})


@api_view(['GET'])
def get_feature_correlation(request, session_id):
    """Retrieve Feature Correlation & Redundancy Profiling report."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    corr_path = os.path.join(reports_dir, 'feature_correlation.csv')

    high_corr_pairs = []
    if os.path.exists(corr_path):
        try:
            corr_df = pd.read_csv(corr_path, index_col=0)
            cols = corr_df.columns
            for i in range(len(cols)):
                for j in range(i + 1, len(cols)):
                    c1, c2 = cols[i], cols[j]
                    val = float(corr_df.loc[c1, c2])
                    if abs(val) > 0.85:
                        high_corr_pairs.append({'featureA': c1, 'featureB': c2, 'pearsonCorrelation': val})
        except Exception:
            pass

    return Response({'highCorrelationPairs': high_corr_pairs})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


# ── M2-05 Slow-Moving Risk Feature Scoring Views ──────────────────────

@api_view(['POST'])
def compute_risk_scores(request, session_id):
    """Compute Slow-Moving Risk Feature Scoring & Diagnostic Flags (M2-05)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    custom_thresholds = request.data.get('customThresholds')

    risk_matrix_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_feature_matrix_json:
            recs = session.risk_feature_matrix_json.get('riskFeatureMatrixRecords')
            if recs:
                risk_matrix_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if risk_matrix_df is None or risk_matrix_df.empty:
        p_path = os.path.join(data_dir, 'risk_feature_matrix.parquet')
        c_path = os.path.join(data_dir, 'risk_feature_matrix.csv')
        if os.path.exists(p_path):
            try:
                risk_matrix_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if risk_matrix_df is None and os.path.exists(c_path):
            try:
                risk_matrix_df = pd.read_csv(c_path)
            except Exception:
                pass

    if risk_matrix_df is None or risk_matrix_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Feature Matrix M2-04. Vui lòng thực thi M2-04 Risk Feature Engineering trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        scorer = RiskFeatureScorer(session_id=session_id)
        result = scorer.compute_risk_scores(
            risk_matrix_df=risk_matrix_df,
            custom_thresholds=custom_thresholds,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.risk_scores_json = result
            session.save(update_fields=['risk_scores_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'thresholdsConfig': result['thresholdsConfig'],
            'scoreSample': result['riskScoreRecords'][:20],
        })

    except FeatureLeakageError as fle:
        logger.error("Automated Leakage Inspector caught leakage in M2-05 for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Phát hiện rò rỉ dữ liệu (Feature Leakage Error): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to compute M2-05 risk scores for session %s", session_id)
        return Response(
            {'error': f'Lỗi tính điểm Risk Feature Scoring M2-05: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_scores(request, session_id):
    """Retrieve SKU Slow-Moving Risk Feature Scoring Dataset."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_scoring_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_scores_json:
            return Response(session.risk_scores_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None, 'riskScoreRecords': []})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


@api_view(['GET'])
def get_risk_scoring_config(request, session_id):
    """Retrieve Risk Scoring Threshold Configuration."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    config_path = os.path.join(reports_dir, 'risk_scoring_config.json')

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return Response({'thresholdsConfig': config})
        except Exception:
            pass

    return Response({'thresholdsConfig': RiskFeatureScorer.DEFAULT_THRESHOLDS})


# ── M2-06 Slow-Moving Risk Classification Views ────────────────────────

@api_view(['POST'])
def classify_slow_moving_risk(request, session_id):
    """Perform XGBoost ML Inference for SKU Slow-Moving Risk Classification (M2-06)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    risk_scores_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_scores_json:
            recs = session.risk_scores_json.get('riskScoreRecords')
            if recs:
                risk_scores_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if risk_scores_df is None or risk_scores_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_risk_scores.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_risk_scores.csv')
        if os.path.exists(p_path):
            try:
                risk_scores_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if risk_scores_df is None and os.path.exists(c_path):
            try:
                risk_scores_df = pd.read_csv(c_path)
            except Exception:
                pass

    if risk_scores_df is None or risk_scores_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Risk Feature Scores M2-05. Vui lòng thực thi M2-05 Risk Feature Scoring trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        classifier = SlowMovingRiskClassifier(session_id=session_id)
        result = classifier.classify_slow_moving_risk(
            risk_scores_m205_df=risk_scores_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.risk_classifications_json = result
            session.save(update_fields=['risk_classifications_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'classificationSample': result['riskClassificationRecords'][:20],
        })

    except FeatureLeakageError as fle:
        logger.error("Inference Leakage Inspector caught leakage in M2-06 for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Phát hiện rò rỉ dữ liệu khi inference (Inference Feature Leakage Error): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to run M2-06 XGBoost risk classification for session %s", session_id)
        return Response(
            {'error': f'Lỗi phân loại XGBoost Risk Classification M2-06: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_classifications(request, session_id):
    """Retrieve SKU Slow-Moving Risk Classification Dataset & Probabilities."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_classification_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_classifications_json:
            return Response(session.risk_classifications_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None, 'riskClassificationRecords': []})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier
from src.analytics.slow_moving_risk_prioritizer import SlowMovingRiskPrioritizer, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


@api_view(['GET'])
def get_risk_classification_summary(request, session_id):
    """Retrieve Risk Classification Distribution Summary Report."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_classification_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusClassified': 0,
        'distributionSummary': {'CRITICAL': 0, 'HIGH_RISK': 0, 'MEDIUM_RISK': 0, 'LOW_RISK': 0}
    })


# ── M2-07 Slow-Moving Risk Ranking & Prioritization Views ─────────────

@api_view(['POST'])
def prioritize_slow_moving_risk(request, session_id):
    """Perform Deterministic Hierarchical Risk Ranking & Prioritization (M2-07)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    custom_weights = request.data.get('customWeights')

    risk_cls_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_classifications_json:
            recs = session.risk_classifications_json.get('riskClassificationRecords')
            if recs:
                risk_cls_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if risk_cls_df is None or risk_cls_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_risk_classifications.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')
        if os.path.exists(p_path):
            try:
                risk_cls_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if risk_cls_df is None and os.path.exists(c_path):
            try:
                risk_cls_df = pd.read_csv(c_path)
            except Exception:
                pass

    if risk_cls_df is None or risk_cls_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Risk Classifications M2-06. Vui lòng thực thi M2-06 Risk Classification trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        prioritizer = SlowMovingRiskPrioritizer(session_id=session_id)
        result = prioritizer.prioritize_slow_moving_risk(
            risk_classifications_m206_df=risk_cls_df,
            custom_weights=custom_weights,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.risk_prioritized_queue_json = result
            session.save(update_fields=['risk_prioritized_queue_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'totalSkus': result['totalSkus'],
            'summary': result['summary'],
            'priorityConfig': result['priorityConfig'],
            'prioritizedQueueSample': result['prioritizedQueueRecords'][:20],
        })

    except FeatureLeakageError as fle:
        logger.error("Prioritization Leakage Inspector caught leakage in M2-07 for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Phát hiện rò rỉ dữ liệu khi xếp hạng ưu tiên (Prioritization Feature Leakage Error): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to run M2-07 Risk Ranking & Prioritization for session %s", session_id)
        return Response(
            {'error': f'Lỗi xếp hạng ưu tiên M2-07: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_prioritized_queue(request, session_id):
    """Retrieve Prioritized Slow-Moving SKU Risk Queue Dataset."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_prioritization_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_prioritized_queue_json:
            return Response(session.risk_prioritized_queue_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response({'summary': summary})
        except Exception:
            pass

    return Response({'summary': None, 'prioritizedQueueRecords': []})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier
from src.analytics.slow_moving_risk_prioritizer import SlowMovingRiskPrioritizer
from src.analytics.feature_readiness_gate import FeatureReadinessGate, FeatureLeakageError
from src.ingestion.data_readiness_gate import DataReadinessError


@api_view(['GET'])
def get_risk_prioritization_summary(request, session_id):
    """Retrieve Risk Prioritization Summary Report."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_prioritization_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusPrioritized': 0,
        'distributionSummary': {'P1_Immediate': 0, 'P2_High': 0, 'P3_Monitor': 0, 'P4_Normal': 0}
    })


# ── M2-08 Feature Validation & Readiness Gate Views ──────────────────

@api_view(['POST'])
def validate_feature_matrix(request, session_id):
    """Execute 8-step validation protocol and freeze Module 02 Feature Layer (M2-08)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    full_matrix_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_prioritized_queue_json:
            recs = session.risk_prioritized_queue_json.get('prioritizedQueueRecords')
            if recs:
                full_matrix_df = pd.DataFrame(recs)
        elif session.risk_feature_matrix_json:
            recs = session.risk_feature_matrix_json.get('riskFeatureMatrixRecords')
            if recs:
                full_matrix_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if full_matrix_df is None or full_matrix_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.csv')
        if os.path.exists(p_path):
            try:
                full_matrix_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if full_matrix_df is None and os.path.exists(c_path):
            try:
                full_matrix_df = pd.read_csv(c_path)
            except Exception:
                pass

    if full_matrix_df is None or full_matrix_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Feature Dataset từ M2-04 -> M2-07. Vui lòng thực thi các bước Feature Layer trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        gate = FeatureReadinessGate(session_id=session_id)
        result = gate.validate_and_freeze_feature_matrix(
            full_feature_matrix_df=full_matrix_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.feature_readiness_certificate_json = result
            session.save(update_fields=['feature_readiness_certificate_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'status': result['status'],
            'totalSkus': result['totalSkus'],
            'totalFeatures': result['totalFeatures'],
            'certificate': result['certificate'],
            'validationReport': result['validationReport'],
        })

    except FeatureLeakageError as fle:
        logger.error("Feature Readiness Gate caught leakage in M2-08 for session %s: %s", session_id, str(fle))
        return Response(
            {'error': f'Cổng Feature Readiness Gate bị KHÓA (BLOCKED): {str(fle)}'},
            status=status.HTTP_403_FORBIDDEN
        )
    except Exception as e:
        logger.exception("Failed to run M2-08 Feature Readiness Gate for session %s", session_id)
        return Response(
            {'error': f'Lỗi cổng kiểm định Feature Readiness Gate M2-08: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_feature_readiness_certificate(request, session_id):
    """Retrieve Official Feature Readiness Certificate JSON."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    cert_path = os.path.join(reports_dir, 'feature_readiness_certificate.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.feature_readiness_certificate_json:
            return Response(session.feature_readiness_certificate_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(cert_path):
        try:
            with open(cert_path, 'r', encoding='utf-8') as f:
                cert = json.load(f)
            return Response({'certificate': cert})
        except Exception:
            pass

    return Response({'certificate': None})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier
from src.analytics.slow_moving_risk_prioritizer import SlowMovingRiskPrioritizer
from src.analytics.feature_readiness_gate import FeatureReadinessGate, FeatureLeakageError
from src.analytics.feature_snapshot_engine import FeatureSnapshotEngine
from src.ingestion.data_readiness_gate import DataReadinessError


@api_view(['GET'])
def get_frozen_feature_matrix(request, session_id):
    """Retrieve Frozen Feature Matrix Dataset."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    val_path = os.path.join(reports_dir, 'feature_validation_report.json')

    if os.path.exists(val_path):
        try:
            with open(val_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
            return Response(report)
        except Exception:
            pass

    return Response({'status': 'NOT_VALIDATED', 'totalSkus': 0})


# ── M2-09 Feature Snapshot & Downstream Handoff Views ─────────────────

@api_view(['POST'])
def create_feature_snapshot(request, session_id):
    """Freeze Immutable Feature Snapshot, compute SHA-256 integrity, trace lineage & export contract (M2-09)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    contract_dir = os.path.join(PROJECT_ROOT, 'contracts')

    validated_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.feature_readiness_certificate_json:
            p_path = os.path.join(data_dir, 'slow_moving_feature_matrix.parquet')
            c_path = os.path.join(data_dir, 'slow_moving_feature_matrix.csv')
            if os.path.exists(p_path):
                try:
                    validated_df = pd.read_parquet(p_path)
                except Exception:
                    pass
            if validated_df is None and os.path.exists(c_path):
                try:
                    validated_df = pd.read_csv(c_path)
                except Exception:
                    pass
        if validated_df is None and session.risk_prioritized_queue_json:
            recs = session.risk_prioritized_queue_json.get('prioritizedQueueRecords')
            if recs:
                validated_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if validated_df is None or validated_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_feature_matrix.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_feature_matrix.csv')
        if os.path.exists(p_path):
            try:
                validated_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if validated_df is None and os.path.exists(c_path):
            try:
                validated_df = pd.read_csv(c_path)
            except Exception:
                pass

    if validated_df is None or validated_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Feature Matrix đã kiểm định M2-08. Vui lòng thực thi M2-08 Feature Readiness Gate trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = FeatureSnapshotEngine(session_id=session_id)
        result = engine.create_feature_snapshot_and_contract(
            validated_feature_matrix_df=validated_df,
            dataset_version="v1.0",
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir,
            contract_dir=contract_dir
        )

        if session:
            session.feature_snapshot_metadata_json = result
            session.save(update_fields=['feature_snapshot_metadata_json', 'updated_at'])

        return Response({
            'sessionId': session_id,
            'featureVersion': result['featureVersion'],
            'contractVersion': result['contractVersion'],
            'status': result['status'],
            'totalSkus': result['totalSkus'],
            'totalFeatures': result['totalFeatures'],
            'checksum': result['checksum'],
            'snapshotMetadata': result['snapshotMetadata'],
            'contract': result['contract'],
        })

    except Exception as e:
        logger.exception("Failed to run M2-09 Feature Snapshot & Downstream Handoff for session %s", session_id)
        return Response(
            {'error': f'Lỗi tạo Feature Snapshot M2-09: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_feature_snapshot_metadata(request, session_id):
    """Retrieve Feature Snapshot Metadata M2-FEATURE-v1.0."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    meta_path = os.path.join(reports_dir, 'feature_snapshot_metadata.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.feature_snapshot_metadata_json:
            return Response(session.feature_snapshot_metadata_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            return Response({'snapshotMetadata': meta})
        except Exception:
            pass

    return Response({'snapshotMetadata': None})


from src.analytics.slow_moving_feature_engineer import SlowMovingFeatureEngineer
from src.analytics.demand_pattern_classifier import DemandPatternClassifier
from src.analytics.risk_feature_assembler import RiskFeatureAssembler
from src.analytics.risk_feature_matrix_engine import RiskFeatureMatrixEngine
from src.analytics.risk_feature_scorer import RiskFeatureScorer
from src.analytics.slow_moving_risk_classifier import SlowMovingRiskClassifier
from src.analytics.slow_moving_risk_prioritizer import SlowMovingRiskPrioritizer
from src.analytics.feature_readiness_gate import FeatureReadinessGate, FeatureLeakageError
from src.analytics.feature_snapshot_engine import FeatureSnapshotEngine
from src.analytics.module02_acceptance_engine import Module02AcceptanceEngine
from src.analytics.risk_model_inference_engine import RiskModelInferenceEngine
from src.analytics.risk_scoring_engine import RiskScoringEngine
from src.analytics.risk_classification_engine import RiskClassificationEngine
from src.analytics.risk_probability_calibrator import RiskProbabilityCalibrator
from src.analytics.risk_diagnostic_engine import RiskDiagnosticEngine
from src.analytics.risk_assessment_assembler import RiskAssessmentAssembler
from src.ingestion.data_readiness_gate import DataReadinessError


# ── M3-06 Risk Assessment Assembly Views ─────────────────────────────

@api_view(['POST'])
def run_risk_assessment_assembly(request, session_id):
    """Execute Risk Assessment Assembly Engine (M3-06)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    pred_df = None
    diag_df = None
    p_path = os.path.join(data_dir, 'slow_moving_risk_classifications.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_probability_calibration_json:
            recs = session.m3_probability_calibration_json.get('calibratedPredictions')
            if recs:
                pred_df = pd.DataFrame(recs)
        elif session.m3_risk_classifications_json:
            recs = session.m3_risk_classifications_json.get('classifications')
            if recs:
                pred_df = pd.DataFrame(recs)

        if session.m3_risk_diagnostics_json:
            drecs = session.m3_risk_diagnostics_json.get('profiles')
            if drecs:
                diag_df = pd.DataFrame(drecs)
    except IngestionSession.DoesNotExist:
        session = None

    if pred_df is None or pred_df.empty:
        if os.path.exists(p_path):
            try:
                pred_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if pred_df is None and os.path.exists(c_path):
            try:
                pred_df = pd.read_csv(c_path)
            except Exception:
                pass

    if pred_df is None or pred_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu M3-03/M3-04 Predictions. Vui lòng thực thi M3-03 / M3-04 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        assembler = RiskAssessmentAssembler(session_id=session_id)
        result = assembler.assemble_risk_assessments(
            predictions_df=pred_df,
            diagnostics_df=diag_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.m3_risk_assessments_json = result
            session.save(update_fields=['m3_risk_assessments_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M3-06 Risk Assessment Assembly for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Assessment Assembly M3-06: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_assessments(request, session_id):
    """Retrieve Unified SKU Risk Assessment Profiles."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    val_path = os.path.join(reports_dir, 'risk_assessment_validation.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_assessments_json:
            return Response(session.m3_risk_assessments_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(val_path):
        try:
            with open(val_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'assessments': []})


@api_view(['GET'])
def get_risk_assessment_summary(request, session_id):
    """Retrieve Risk Assessment Status Summary & Distribution."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_assessment_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusAssembled': 0,
        'completeCount': 0,
        'partialCount': 0,
        'invalidCount': 0,
        'assessmentStatusDistribution': {}
    })


# ── M3-05 Risk Diagnostic Engine Views ─────────────────────────────────

@api_view(['POST'])
def run_risk_diagnostics(request, session_id):
    """Execute Risk Diagnostic Engine on SKU predictions & observables (M3-05)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    pred_df = None
    p_path = os.path.join(data_dir, 'slow_moving_risk_classifications.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_probability_calibration_json:
            recs = session.m3_probability_calibration_json.get('calibratedPredictions')
            if recs:
                pred_df = pd.DataFrame(recs)
        elif session.m3_risk_classifications_json:
            recs = session.m3_risk_classifications_json.get('classifications')
            if recs:
                pred_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if pred_df is None or pred_df.empty:
        if os.path.exists(p_path):
            try:
                pred_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if pred_df is None and os.path.exists(c_path):
            try:
                pred_df = pd.read_csv(c_path)
            except Exception:
                pass

    if pred_df is None or pred_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu M3-03/M3-04 Predictions. Vui lòng thực thi M3-03 / M3-04 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = RiskDiagnosticEngine(session_id=session_id)
        result = engine.diagnose_sku_risks(
            predictions_df=pred_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.m3_risk_diagnostics_json = result
            session.save(update_fields=['m3_risk_diagnostics_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M3-05 Risk Diagnostic Engine for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Diagnostics M3-05: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_diagnostics(request, session_id):
    """Retrieve SKU Risk Diagnostic Profiles & Evidence."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    val_path = os.path.join(reports_dir, 'diagnostic_rule_validation.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_diagnostics_json:
            return Response(session.m3_risk_diagnostics_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(val_path):
        try:
            with open(val_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'profiles': []})


@api_view(['GET'])
def get_diagnostic_summary(request, session_id):
    """Retrieve Diagnostic Signal Activation Summary & Frequency Distribution."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    val_path = os.path.join(reports_dir, 'diagnostic_rule_validation.json')

    if os.path.exists(val_path):
        try:
            with open(val_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusDiagnosed': 0,
        'signalCounts': {},
        'signalDistribution': []
    })


# ── M3-04 Risk Probability Calibration Views ──────────────────────────

@api_view(['POST'])
def run_probability_calibration(request, session_id):
    """Execute Risk Probability Calibration Engine & Benchmark (M3-04)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    models_dir = os.path.join(PROJECT_ROOT, 'models')

    pred_df = None
    p_path = os.path.join(data_dir, 'slow_moving_risk_classifications.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_classifications.csv')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_classifications_json:
            recs = session.m3_risk_classifications_json.get('classifications')
            if recs:
                pred_df = pd.DataFrame(recs)
        elif session.risk_model_predictions_json:
            recs = session.risk_model_predictions_json.get('predictions')
            if recs:
                pred_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if pred_df is None or pred_df.empty:
        if os.path.exists(p_path):
            try:
                pred_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if pred_df is None and os.path.exists(c_path):
            try:
                pred_df = pd.read_csv(c_path)
            except Exception:
                pass

    if pred_df is None or pred_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu M3-01/M3-03 Predictions / Classifications. Vui lòng thực thi M3-01 / M3-03 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        calibrator = RiskProbabilityCalibrator(session_id=session_id)
        result = calibrator.benchmark_and_calibrate(
            predictions_df=pred_df,
            session_id=session_id,
            output_dir=reports_dir,
            models_dir=models_dir,
            data_dir=data_dir
        )

        if session:
            session.m3_probability_calibration_json = result
            session.save(update_fields=['m3_probability_calibration_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M3-04 Risk Probability Calibration for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Probability Calibration M3-04: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_probability_calibrated_predictions(request, session_id):
    """Retrieve SKU predictions with calibrated probability & confidence levels."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    res_path = os.path.join(reports_dir, 'calibration_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_probability_calibration_json:
            return Response(session.m3_probability_calibration_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(res_path):
        try:
            with open(res_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'calibratedPredictions': []})


@api_view(['GET'])
def get_calibration_summary(request, session_id):
    """Retrieve Multi-Method Calibration Benchmark Summary & Metrics (ECE, Brier, Log Loss)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'calibration_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusCalibrated': 0,
        'optimalCalibrationMethod': 'platt_sigmoid',
        'optimalECE': 0.0,
        'benchmark': []
    })


# ── M3-03 Risk Classification Views ───────────────────────────────────

@api_view(['POST'])
def run_risk_classification(request, session_id):
    """Execute Risk Classification Engine on Scored Risk Dataset (M3-03)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    scored_df = None
    p_path = os.path.join(data_dir, 'slow_moving_risk_scores.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_scores.csv')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_scores_json:
            recs = session.m3_risk_scores_json.get('scores')
            if recs:
                scored_df = pd.DataFrame(recs)
        elif session.risk_model_predictions_json:
            recs = session.risk_model_predictions_json.get('predictions')
            if recs:
                scored_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if scored_df is None or scored_df.empty:
        if os.path.exists(p_path):
            try:
                scored_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if scored_df is None and os.path.exists(c_path):
            try:
                scored_df = pd.read_csv(c_path)
            except Exception:
                pass

    if scored_df is None or scored_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu M3-02 Risk Scores / Predictions. Vui lòng chạy M3-02 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        amb_thresh = float(request.data.get('ambiguity_threshold', 0.10)) if request.data else 0.10
        engine = RiskClassificationEngine(session_id=session_id)
        result = engine.classify_sku_risks(
            scored_df=scored_df,
            ambiguity_threshold=amb_thresh,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.m3_risk_classifications_json = result
            session.save(update_fields=['m3_risk_classifications_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M3-03 Risk Classification for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Classification M3-03: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_classifications(request, session_id):
    """Retrieve SKU Risk Classifications, Severity & Confidence."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    res_path = os.path.join(reports_dir, 'risk_classification_results.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_classifications_json:
            return Response(session.m3_risk_classifications_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(res_path):
        try:
            with open(res_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'classifications': []})


@api_view(['GET'])
def get_risk_classification_summary(request, session_id):
    """Retrieve Risk Classification Distribution & Severity Summary."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_classification_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusClassified': 0,
        'confidentCount': 0,
        'ambiguousCount': 0,
        'classDistribution': {},
        'severityDistribution': {},
        'statusDistribution': {}
    })


# ── M3-02 Risk Scoring Engine Views ───────────────────────────────────

@api_view(['POST'])
def run_risk_scoring(request, session_id):
    """Execute Risk Scoring Engine on XGBoost Predictions (M3-02)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    pred_df = None
    p_path = os.path.join(data_dir, 'slow_moving_risk_model_predictions.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_model_predictions.csv')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_model_predictions_json:
            recs = session.risk_model_predictions_json.get('predictions')
            if recs:
                pred_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if pred_df is None or pred_df.empty:
        if os.path.exists(p_path):
            try:
                pred_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if pred_df is None and os.path.exists(c_path):
            try:
                pred_df = pd.read_csv(c_path)
            except Exception:
                pass

    if pred_df is None or pred_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy kết quả dự đoán M3-01 Risk Model Predictions. Vui lòng chạy M3-01 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = RiskScoringEngine(session_id=session_id)
        result = engine.calculate_risk_scores(
            predictions_df=pred_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        if session:
            session.m3_risk_scores_json = result
            session.save(update_fields=['m3_risk_scores_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M3-02 Risk Scoring for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Scoring M3-02: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_scores(request, session_id):
    """Retrieve Normalized SKU Risk Scores & Priorities."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    res_path = os.path.join(reports_dir, 'risk_scoring_results.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.m3_risk_scores_json:
            return Response(session.m3_risk_scores_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(res_path):
        try:
            with open(res_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'scores': []})


@api_view(['GET'])
def get_risk_scoring_summary(request, session_id):
    """Retrieve Risk Scoring Distribution & Consistency Summary."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_scoring_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'totalSkusScored': 0,
        'validScoresCount': 0,
        'invalidScoresCount': 0,
        'classDistribution': {},
        'priorityDistribution': {}
    })


# ── M3-01 Risk Model Integration Views ─────────────────────────────────

@api_view(['POST'])
def run_risk_model_inference(request, session_id):
    """Execute XGBoost model inference on Feature Snapshot (M3-01)."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')

    snap_df = None
    p_path = os.path.join(data_dir, 'slow_moving_feature_snapshot_v1.0.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_feature_snapshot_v1.0.csv')
    m_path = os.path.join(data_dir, 'slow_moving_feature_matrix.parquet')

    if os.path.exists(p_path):
        try:
            snap_df = pd.read_parquet(p_path)
        except Exception:
            pass
    if snap_df is None and os.path.exists(c_path):
        try:
            snap_df = pd.read_csv(c_path)
        except Exception:
            pass
    if snap_df is None and os.path.exists(m_path):
        try:
            snap_df = pd.read_parquet(m_path)
        except Exception:
            pass

    if snap_df is None or snap_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy Frozen Feature Snapshot M2-FEATURE-v1.0. Vui lòng chạy M2-08/M2-09 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = RiskModelInferenceEngine(session_id=session_id)
        result = engine.run_risk_model_inference(
            feature_snapshot_df=snap_df,
            session_id=session_id,
            output_dir=reports_dir,
            data_dir=data_dir
        )

        try:
            session = IngestionSession.objects.get(id=session_id)
            session.risk_model_predictions_json = result
            session.save(update_fields=['risk_model_predictions_json', 'updated_at'])
        except IngestionSession.DoesNotExist:
            pass

        return Response(result)

    except ValueError as ve:
        return Response({'error': str(ve), 'status': 'BLOCKED'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("Failed to run M3-01 Risk Model Inference for session %s", session_id)
        return Response(
            {'error': f'Lỗi thực thi Risk Model Inference M3-01: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_model_predictions(request, session_id):
    """Retrieve SKU Predictions from XGBoost Risk Model."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    res_path = os.path.join(reports_dir, 'risk_model_inference_results.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_model_predictions_json:
            return Response(session.risk_model_predictions_json)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(res_path):
        try:
            with open(res_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data)
        except Exception:
            pass

    return Response({'predictions': []})


@api_view(['GET'])
def get_risk_model_status(request, session_id):
    """Retrieve XGBoost Risk Model Traceability & Status Metadata."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    sum_path = os.path.join(reports_dir, 'risk_model_inference_summary.json')

    if os.path.exists(sum_path):
        try:
            with open(sum_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            return Response(summary)
        except Exception:
            pass

    return Response({
        'model_version': 'xgboost_exp03_v1',
        'experiment_version': 'EXP-03',
        'feature_schema_version': 'M2-FEATURE-v1.0',
        'status': 'READY_FOR_INFERENCE'
    })


@api_view(['GET'])
def get_risk_model_contract(request, session_id):
    """Retrieve Downstream Handoff Contract for Risk Model (EXP-03)."""
    contract_dir = os.path.join(PROJECT_ROOT, 'contracts')
    c_path = os.path.join(contract_dir, 'risk_model_feature_contract_v1.json')

    if os.path.exists(c_path):
        try:
            with open(c_path, 'r', encoding='utf-8') as f:
                contract = json.load(f)
            return Response(contract)
        except Exception:
            pass

    return Response({'contract_status': 'NOT_GENERATED'})


# ── M2-10 Risk Dashboard UI & Module 02 Acceptance Views ─────────────

@api_view(['POST'])
def run_module02_acceptance(request, session_id):
    """Execute 18-Criteria Acceptance Protocol & Generate Module 02 Final Certificate (M2-10)."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')

    risk_df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_prioritized_queue_json:
            recs = session.risk_prioritized_queue_json.get('prioritizedQueueRecords')
            if recs:
                risk_df = pd.DataFrame(recs)
        elif session.risk_classifications_json:
            recs = session.risk_classifications_json.get('riskClassificationRecords')
            if recs:
                risk_df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        session = None

    if risk_df is None or risk_df.empty:
        p_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.parquet')
        c_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.csv')
        if os.path.exists(p_path):
            try:
                risk_df = pd.read_parquet(p_path)
            except Exception:
                pass
        if risk_df is None and os.path.exists(c_path):
            try:
                risk_df = pd.read_csv(c_path)
            except Exception:
                pass

    if risk_df is None or risk_df.empty:
        return Response(
            {'error': 'Chưa tìm thấy dữ liệu Risk Prediction / Queue. Vui lòng thực thi M2-06 / M2-07 trước.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        engine = Module02AcceptanceEngine(session_id=session_id)
        result = engine.run_module02_acceptance(
            risk_dataset_df=risk_df,
            session_id=session_id,
            output_dir=reports_dir
        )

        if session:
            session.module02_acceptance_json = result
            session.save(update_fields=['module02_acceptance_json', 'updated_at'])

        return Response(result)

    except Exception as e:
        logger.exception("Failed to run M2-10 Module 02 Acceptance for session %s", session_id)
        return Response(
            {'error': f'Lỗi nghiệm thu Module 02 (M2-10): {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_risk_summary(request, session_id):
    """Retrieve Executive Risk KPI Summary & Distribution."""
    reports_dir = os.path.join(PROJECT_ROOT, 'reports')
    acc_path = os.path.join(reports_dir, 'module_02_acceptance.json')
    cls_path = os.path.join(reports_dir, 'risk_classification_summary.json')

    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.module02_acceptance_json:
            return Response(session.module02_acceptance_json.get('summary', {}))
        if session.risk_classifications_json:
            sum_data = session.risk_classifications_json.get('summary', {}).get('distributionSummary', {})
            return Response(sum_data)
    except IngestionSession.DoesNotExist:
        pass

    if os.path.exists(acc_path):
        try:
            with open(acc_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Response(data.get('summary_metrics', {}))
        except Exception:
            pass

    return Response({
        'totalSkus': 0,
        'criticalRisk': 0,
        'highRisk': 0,
        'mediumRisk': 0,
        'lowRisk': 0,
        'highRiskRatePct': '0.0%'
    })


@api_view(['GET'])
def get_risk_products(request, session_id):
    """Retrieve SKU Risk List with Filtering, Search & Sorting."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    p_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.csv')

    df = None
    try:
        session = IngestionSession.objects.get(id=session_id)
        if session.risk_prioritized_queue_json:
            recs = session.risk_prioritized_queue_json.get('prioritizedQueueRecords')
            if recs:
                df = pd.DataFrame(recs)
    except IngestionSession.DoesNotExist:
        pass

    if df is None or df.empty:
        if os.path.exists(p_path):
            try:
                df = pd.read_parquet(p_path)
            except Exception:
                pass
        if df is None and os.path.exists(c_path):
            try:
                df = pd.read_csv(c_path)
            except Exception:
                pass

    if df is None or df.empty:
        return Response({'totalSkus': 0, 'products': []})

    # Filters
    risk_filter = request.GET.get('risk_level')
    search_query = request.GET.get('search')
    sort_by = request.GET.get('sort_by', 'priority_score')

    if risk_filter:
        df = df[df['risk_level'] == risk_filter]

    if search_query:
        sq = search_query.lower()
        df = df[
            df['sku'].astype(str).str.lower().str.contains(sq) |
            df['product_name'].astype(str).str.lower().str.contains(sq)
        ]

    if sort_by in df.columns:
        asc = sort_by in ['sales_velocity_30d', 'priority_rank']
        df = df.sort_values(by=sort_by, ascending=asc)

    records = df.to_dict(orient='records')
    return Response({'totalSkus': len(records), 'products': records})


@api_view(['GET'])
def get_risk_product_detail(request, session_id, sku):
    """Retrieve Single SKU Risk Detail for Detail Drawer."""
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    p_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.parquet')
    c_path = os.path.join(data_dir, 'slow_moving_risk_prioritized_queue.csv')

    df = None
    if os.path.exists(p_path):
        try:
            df = pd.read_parquet(p_path)
        except Exception:
            pass
    if df is None and os.path.exists(c_path):
        try:
            df = pd.read_csv(c_path)
        except Exception:
            pass

    if df is not None and not df.empty:
        sku_col = 'canonical_sku_id' if 'canonical_sku_id' in df.columns else 'sku'
        sub = df[(df['sku'] == sku) | (df[sku_col] == sku)]
        if not sub.empty:
            rec = sub.iloc[0].to_dict()
            # SHAP placeholder simulation
            rec['shap_contributions'] = [
                {'feature': 'zero_rate_90d', 'weight': 0.38, 'impact': 'HIGH_RISK_INCREASE'},
                {'feature': 'dsls', 'weight': 0.28, 'impact': 'HIGH_RISK_INCREASE'},
                {'feature': 'sales_velocity_30d', 'weight': 0.20, 'impact': 'HIGH_RISK_INCREASE'},
                {'feature': 'demand_probability', 'weight': 0.14, 'impact': 'HIGH_RISK_INCREASE'}
            ]
            return Response(rec)

    return Response({'error': f'Không tìm thấy chi tiết SKU {sku}'}, status=status.HTTP_404_NOT_FOUND)
