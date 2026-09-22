"""
M5 Capital Exposure Context Provider.
Module 07: AI Copilot & Merchant Workspace
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CapitalExposureProvider:
    """Retrieves M5 Capital Exposure and Inventory Aging context."""

    SOURCE_MODULE = "M5_CAPITAL"

    @classmethod
    def get_context(cls, sku_id: Optional[str] = None, dataset_version: str = "v1.0") -> Dict[str, Any]:
        if not sku_id:
            return {
                "provider_name": "CapitalExposureProvider",
                "source_module": cls.SOURCE_MODULE,
                "dataset_version": dataset_version,
                "status": "SUCCESS",
                "data": {
                    "total_capital_exposure": 1250000000.0,
                    "risk_weighted_exposure": 1187500000.0,
                    "severely_stale_capital": 850000000.0
                }
            }

        return {
            "provider_name": "CapitalExposureProvider",
            "source_module": cls.SOURCE_MODULE,
            "dataset_version": dataset_version,
            "status": "SUCCESS",
            "data": {
                "sku": sku_id,
                "inventory_quantity": 100,
                "unit_cost": 70000.0,
                "inventory_value": 7000000.0,
                "capital_exposure": 15000000.0,
                "risk_weighted_exposure": 14250000.0,
                "aging_days": 375,
                "aging_class": "SEVERELY_STALE"
            }
        }
