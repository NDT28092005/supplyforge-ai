"""Worker-only creation of capital exposure read models."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import Max

from src.analytics.aging_risk_classifier import AgingRiskClassifier
from src.analytics.capital_exposure_repository import CapitalExposureRepository
from src.analytics.capital_valuation_engine import CapitalValuationEngine
from src.analytics.financial_impact_engine import FinancialImpactEngine
from src.analytics.inventory_aging_engine import InventoryAgingEngine
from src.analytics.risk_weighted_exposure_engine import RiskWeightedExposureEngine
from supplyforge.models import IngestionSession, Order, SlowMovingRiskAssessment

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
    def get_current_analysis(cls, workspace_id: int):
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
        session = cls._latest_risk_session(workspace_id)
        if not session:
            return None

        merchant_id = f'workspace:{workspace_id}'
        dataset_version = f'session:{session.id}'
        existing = CapitalExposureRepository.get_latest_analysis(
            merchant_id=merchant_id,
            dataset_version=dataset_version,
        )
        if existing:
            return existing

        lock_key = f'sf:capital-analysis:{workspace_id}:{session.id}'
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

            assessments = SlowMovingRiskAssessment.objects.filter(session=session)
            if not assessments.exists():
                return None

            orders = Order.objects.filter(
                user_id=str(session.workspace.owner_id or workspace_id),
            )
            reference_date = orders.aggregate(Max('created_at'))['created_at__max'] or datetime.now()
            if getattr(reference_date, 'tzinfo', None) is not None:
                reference_date = reference_date.replace(tzinfo=None)

            product_rows: list[dict] = []
            risk_rows: list[dict] = []
            for assessment in assessments.iterator(chunk_size=1000):
                evidence = assessment.evidence if isinstance(assessment.evidence, dict) else {}
                stock = int(evidence.get('stock_quantity') or 0)
                cost = float(evidence.get('unit_cost') or 0.0)
                product_rows.append({
                    'sku': assessment.sku,
                    'product_name': assessment.product_name,
                    'category': assessment.category or 'Tồn kho',
                    'stock_on_hand': stock,
                    'unit_cost': cost,
                    'dsls': int(evidence.get('dsls') or 0),
                    'capital_exposure_vnd': float(
                        evidence.get('capital_exposure_vnd') or stock * cost
                    ),
                    'last_sale_date': None,
                })
                risk_rows.append({
                    'sku': assessment.sku,
                    'risk_class': assessment.risk_class,
                    'risk_probability': float(assessment.risk_probability or 0.0),
                    'risk_score': float(assessment.risk_score or 0.0),
                })

            sample_df = pd.DataFrame(product_rows)
            valuation = CapitalValuationEngine()
            aging = InventoryAgingEngine()
            exposure = RiskWeightedExposureEngine()
            classifier = AgingRiskClassifier()
            impact = FinancialImpactEngine(default_opportunity_rate=annual_rate)

            sku_values, _ = valuation.value_dataset(sample_df, risk_rows)
            aging_records, _, _ = aging.analyze_dataset_aging(
                sku_values,
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
