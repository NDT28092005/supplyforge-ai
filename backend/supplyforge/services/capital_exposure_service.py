"""Worker-only creation of capital exposure read models."""

from __future__ import annotations

import logging
from datetime import datetime

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Max

from src.analytics.aging_risk_classifier import AgingRiskClassifier
from src.analytics.capital_exposure_repository import CapitalExposureRepository
from src.analytics.financial_impact_engine import FinancialImpactEngine
from src.analytics.inventory_aging_engine import InventoryAgingEngine
from src.analytics.risk_weighted_exposure_engine import RiskWeightedExposureEngine
from supplyforge.models import (
    IngestionSession, Order, SlowMovingAssessmentRun, SlowMovingRiskAssessment,
)

logger = logging.getLogger(__name__)


class CapitalExposureAnalysisService:
    """Build one immutable capital analysis after a dataset has been published.

    This deliberately lives outside HTTP views. A dashboard request may read an
    existing analysis, but it must never perform a portfolio-wide calculation.
    """

    LOCK_TTL_SECONDS = 15 * 60

    @classmethod
    def _latest_risk_session(cls, workspace_id: int):
        return (
            IngestionSession.objects.filter(
                workspace_id=workspace_id,
                risk_assessments__isnull=False,
            )
            .select_related('workspace')
            .order_by('-created_at')
            .distinct()
            .first()
        )

    @classmethod
    def _current_operational_run(cls, workspace_id: int):
        return (
            SlowMovingAssessmentRun.objects.filter(
                workspace_id=workspace_id,
                source_type=SlowMovingAssessmentRun.SOURCE_CSV,
                source_key='CSV',
                status=SlowMovingAssessmentRun.STATUS_COMPLETED,
                is_current=True,
            )
            .select_related('dataset_version', 'dataset_version__ingestion_session')
            .first()
        )

    @classmethod
    def get_current_analysis(cls, workspace_id: int):
        run = cls._current_operational_run(workspace_id)
        if run:
            return CapitalExposureRepository.get_latest_analysis(
                merchant_id=f'workspace:{workspace_id}',
                dataset_version=f'risk-run:{run.id}',
            )
        session = cls._latest_risk_session(workspace_id)
        if not session:
            return None
        return CapitalExposureRepository.get_latest_analysis(
            merchant_id=f'workspace:{workspace_id}',
            dataset_version=f'session:{session.id}',
        )

    @classmethod
    def ensure_current_analysis(
        cls,
        workspace_id: int,
        annual_rate: float = 0.12,
    ):
        run = cls._current_operational_run(workspace_id)
        session = None if run else cls._latest_risk_session(workspace_id)
        if not run and not session:
            return None

        merchant_id = f'workspace:{workspace_id}'
        dataset_version = f'risk-run:{run.id}' if run else f'session:{session.id}'
        existing = CapitalExposureRepository.get_latest_analysis(
            merchant_id=merchant_id,
            dataset_version=dataset_version,
        )
        if existing:
            return existing

        lock_key = f'sf:capital-analysis:{workspace_id}:{run.id if run else session.id}'
        try:
            lock_acquired = cache.add(lock_key, '1', timeout=cls.LOCK_TTL_SECONDS)
        except Exception:
            # The database uniqueness constraint below remains the final guard.
            lock_acquired = True
        if not lock_acquired:
            return None

        try:
            # Re-check after receiving the lock in case the prior worker finished.
            existing = CapitalExposureRepository.get_latest_analysis(
                merchant_id=merchant_id,
                dataset_version=dataset_version,
            )
            if existing:
                return existing

            assessments = (
                SlowMovingRiskAssessment.objects.filter(assessment_run=run, assessment_status='COMPLETE')
                if run else SlowMovingRiskAssessment.objects.filter(session=session)
            )
            if not assessments.exists():
                return None

            orders = Order.objects.filter(workspace_id=workspace_id)
            reference_date = run.analysis_as_of if run else (orders.aggregate(Max('created_at'))['created_at__max'] or datetime.now())
            if getattr(reference_date, 'tzinfo', None) is not None:
                reference_date = reference_date.replace(tzinfo=None)

            valuation_records: list[dict] = []
            for assessment in assessments.iterator(chunk_size=1000):
                evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
                if assessment.risk_probability is None:
                    # A rule priority orders merchant attention but is not a
                    # calibrated likelihood.  Do not fabricate a
                    # probability-weighted capital claim from it.
                    logger.info(
                        'Capital risk weighting withheld for workspace %s: SKU %s has no calibrated probability.',
                        workspace_id,
                        assessment.sku,
                    )
                    return None
                readiness = evidence.get('inventory_readiness') or {}
                if readiness.get('status') != 'READY':
                    logger.info(
                        'Capital analysis withheld for workspace %s: SKU %s has no verified as-of inventory snapshot.',
                        workspace_id,
                        assessment.sku,
                    )
                    return None
                stock = evidence.get('stock_quantity')
                capital_exposure = evidence.get('capital_exposure_vnd')
                if stock is None or capital_exposure is None:
                    logger.warning(
                        'Capital analysis withheld for workspace %s: SKU %s has incomplete verified inventory evidence.',
                        workspace_id,
                        assessment.sku,
                    )
                    return None
                try:
                    stock = float(stock)
                    capital_exposure = float(capital_exposure)
                except (TypeError, ValueError):
                    logger.warning(
                        'Capital analysis withheld for workspace %s: SKU %s has invalid verified inventory evidence.',
                        workspace_id,
                        assessment.sku,
                    )
                    return None
                if stock < 0 or capital_exposure < 0:
                    logger.warning(
                        'Capital analysis withheld for workspace %s: SKU %s has negative verified inventory evidence.',
                        workspace_id,
                        assessment.sku,
                    )
                    return None

                # ``capital_exposure_vnd`` is an exact sum of the newest
                # verified SKU/warehouse snapshots. Do not re-derive it as
                # stock x a made-up unit cost: warehouses can legitimately
                # carry different costs, in which case the per-unit figure is
                # intentionally unavailable.
                valuation_records.append({
                    'sku': assessment.sku,
                    'canonical_sku_id': assessment.canonical_sku_id or f'CSKU_{assessment.sku}',
                    'product_name': assessment.product_name,
                    'category': assessment.category or 'Tồn kho',
                    'stock_on_hand': stock,
                    'unit_cost': evidence.get('unit_cost'),
                    'cost_status': 'VERIFIED_AGGREGATE',
                    'dsls': int(evidence.get('dsls') or 0),
                    'inventory_capital_exposure': capital_exposure,
                    'observed_cost_value': None,
                    'last_sale_date': None,
                    'risk_class': assessment.risk_class,
                    'risk_probability': float(assessment.risk_probability or 0.0),
                    'risk_score': float(assessment.risk_score or 0.0),
                })

            aging = InventoryAgingEngine()
            exposure = RiskWeightedExposureEngine()
            classifier = AgingRiskClassifier()
            impact = FinancialImpactEngine(default_opportunity_rate=annual_rate)

            aging_records, _, _ = aging.analyze_dataset_aging(
                valuation_records,
                analysis_date=reference_date.strftime('%Y-%m-%d'),
            )
            exposure_records, _ = exposure.evaluate_portfolio_exposure(aging_records)
            classified, _, _, _ = classifier.evaluate_dataset_aging_risk(exposure_records)
            financial_summary = impact.evaluate_portfolio_financial_impact(
                classified,
                annual_rate=annual_rate,
            )

            try:
                return CapitalExposureRepository.save_analysis(
                    summary_payload=financial_summary,
                    sku_assessment_records=classified,
                    merchant_id=merchant_id,
                    dataset_version=dataset_version,
                )
            except IntegrityError:
                # Concurrent imports may reach this point. The unique dataset
                # constraint makes the first committed analysis authoritative.
                return CapitalExposureRepository.get_latest_analysis(
                    merchant_id=merchant_id,
                    dataset_version=dataset_version,
                )
        finally:
            try:
                cache.delete(lock_key)
            except Exception:
                logger.warning('Could not release capital analysis lock for workspace %s.', workspace_id)
