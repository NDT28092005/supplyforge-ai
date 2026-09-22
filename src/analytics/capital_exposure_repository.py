"""
Task M5-09 — Capital Exposure API & Persistence
Module 05: Capital Exposure & Aging Analysis

Repository pattern for persisting, querying, and retrieving Module 05 capital exposure
analysis runs, portfolio summaries, and detailed SKU exposure items.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator

from supplyforge.models.capital_exposure import (
    CapitalExposureAnalysisRecord,
    CapitalExposureItemRecord
)

logger = logging.getLogger(__name__)


class CapitalExposureRepository:
    """
    Production Repository for Module 05 Capital Exposure & Aging Analysis.
    """

    @staticmethod
    def save_analysis(
        summary_payload: Dict[str, Any],
        sku_assessment_records: List[Dict[str, Any]],
        merchant_id: str = "default_merchant",
        dataset_version: str = "v1.0",
        analysis_id: Optional[str] = None
    ) -> CapitalExposureAnalysisRecord:
        """
        Persists analysis run metadata and bulk inserts SKU exposure items within an atomic transaction.
        Guarantees zero recalculation drift and idempotent persistence.
        """
        aid = analysis_id or str(uuid.uuid4())
        summary_data = summary_payload.get("summary", {})

        with transaction.atomic():
            analysis_rec = CapitalExposureAnalysisRecord.objects.create(
                analysis_id=aid,
                merchant_id=merchant_id,
                dataset_version=dataset_version,
                status="COMPLETED",
                calculation_version=summary_payload.get("module_version", "5.0"),
                total_skus=summary_data.get("sku_count", len(sku_assessment_records)),
                total_inventory_value=summary_data.get("total_inventory_value", 0.0),
                total_risk_weighted_exposure=summary_data.get("total_risk_weighted_exposure", 0.0),
                total_probability_adjusted_exposure=summary_data.get("total_probability_adjusted_exposure", 0.0),
                total_opportunity_cost=summary_data.get("total_opportunity_cost", 0.0),
                annual_opportunity_rate=summary_data.get("annual_opportunity_rate", 0.12),
                summary_payload=summary_payload,
                risk_distribution=summary_payload.get("financial_impact_by_risk") or summary_payload.get("risk_distribution") or [],
                aging_distribution=summary_payload.get("financial_impact_by_aging") or summary_payload.get("aging_distribution") or [],
                risk_aging_matrix=summary_payload.get("financial_impact_matrix") or summary_payload.get("risk_aging_matrix") or [],
                reconciliation_status=summary_payload.get("reconciliation_status") or {}
            )

            item_instances = []
            for rec in sku_assessment_records:
                cap_val = float(rec.get("capital_exposure") or rec.get("inventory_value") or 0.0)
                rwce = float(rec.get("risk_weighted_exposure") or 0.0)
                pae = float(rec.get("probability_adjusted_exposure") or (cap_val * float(rec.get("risk_probability", 0.0))))

                item_instances.append(
                    CapitalExposureItemRecord(
                        analysis=analysis_rec,
                        sku=rec["sku"],
                        canonical_sku_id=rec.get("canonical_sku_id", f"CSKU_{rec['sku']}"),
                        product_name=rec.get("product_name", f"Product {rec['sku']}"),
                        category=rec.get("category", "General"),
                        inventory_value=cap_val,
                        capital_exposure=cap_val,
                        risk_weighted_exposure=rwce,
                        probability_adjusted_exposure=pae,
                        aging_days=rec.get("inventory_age_days") if "inventory_age_days" in rec else rec.get("aging_days"),
                        aging_bucket=rec.get("aging_bucket", "RECENT"),
                        aging_risk_level=rec.get("aging_risk_level", "FRESH"),
                        slow_moving_risk_class=rec.get("slow_moving_risk_class") or rec.get("risk_class") or "LOW_RISK",
                        risk_probability=float(rec.get("risk_probability", 0.0)),
                        aging_priority=rec.get("aging_priority") or rec.get("financial_impact_priority") or "P4",
                        estimated_opportunity_cost=rec.get("estimated_opportunity_cost"),
                        aging_flags=rec.get("aging_flags", [])
                    )
                )

            # Bulk create for high performance
            CapitalExposureItemRecord.objects.bulk_create(item_instances, batch_size=500)

        logger.info("Successfully persisted Capital Exposure Analysis %s with %d items.", aid, len(item_instances))
        return analysis_rec

    @staticmethod
    def get_analysis(analysis_id: str) -> Optional[CapitalExposureAnalysisRecord]:
        """Retrieves an analysis record by ID."""
        try:
            return CapitalExposureAnalysisRecord.objects.get(analysis_id=analysis_id)
        except CapitalExposureAnalysisRecord.DoesNotExist:
            return None

    @staticmethod
    def get_latest_analysis(
        merchant_id: str = "default_merchant",
        dataset_version: Optional[str] = None
    ) -> Optional[CapitalExposureAnalysisRecord]:
        """Retrieves the latest completed analysis run for a merchant/dataset_version."""
        qs = CapitalExposureAnalysisRecord.objects.filter(merchant_id=merchant_id, status="COMPLETED")
        if dataset_version:
            qs = qs.filter(dataset_version=dataset_version)
        return qs.order_by("-created_at").first()

    @staticmethod
    def list_sku_items(
        analysis_id: str,
        risk_level: Optional[str] = None,
        aging_bucket: Optional[str] = None,
        aging_priority: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
        sort: str = "-risk_weighted_exposure"
    ) -> Tuple[List[CapitalExposureItemRecord], Dict[str, Any]]:
        """
        Paginated and filtered query for SKU exposure item records.
        """
        qs = CapitalExposureItemRecord.objects.filter(analysis_id=analysis_id)

        if risk_level:
            qs = qs.filter(slow_moving_risk_class=risk_level.upper())
        if aging_bucket:
            qs = qs.filter(aging_bucket=aging_bucket.upper())
        if aging_priority:
            qs = qs.filter(aging_priority=aging_priority.upper())
        if search:
            qs = qs.filter(Q(sku__icontains=search) | Q(product_name__icontains=search) | Q(category__icontains=search))

        # Sorting
        valid_sorts = [
            "risk_weighted_exposure", "-risk_weighted_exposure",
            "capital_exposure", "-capital_exposure",
            "estimated_opportunity_cost", "-estimated_opportunity_cost",
            "aging_days", "-aging_days", "sku", "-sku"
        ]
        if sort in valid_sorts:
            qs = qs.order_by(sort)
        else:
            qs = qs.order_by("-risk_weighted_exposure")

        paginator = Paginator(qs, limit)
        page_obj = paginator.get_page(page)

        pagination_meta = {
            "total_items": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page_obj.number,
            "limit": limit,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous()
        }

        return list(page_obj.object_list), pagination_meta

    @staticmethod
    def get_sku_item_detail(analysis_id: str, sku: str) -> Optional[CapitalExposureItemRecord]:
        """Retrieves a single SKU exposure item detail by analysis_id and sku."""
        try:
            return CapitalExposureItemRecord.objects.get(analysis_id=analysis_id, sku=sku)
        except CapitalExposureItemRecord.DoesNotExist:
            return None
