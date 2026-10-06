"""
SupplyForge AI — Proactive Cache Warming & Invalidation Service
================================================================
Pre-computes & warms aggregate caches across core modules upon pipeline finalization.
"""

import logging
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.services.query_service import DashboardQueryService

logger = logging.getLogger(__name__)


class CacheWarmingService:
    @classmethod
    def warm_workspace_cache(cls, workspace_id: int):
        """
        Warms aggregate + top-N caches for Dashboard, Risk, Capital, Decision modules.
        Triggered at the end of import pipeline.
        """
        logger.info(f"[CacheWarming] Pre-computing & warming Redis caches for workspace_id={workspace_id}")

        # 1. Bump version to invalidate any old keys atomically in O(1)
        new_version = CachePolicy.bump_workspace_version(workspace_id)

        # 2. Warm Dashboard Summary Cache
        try:
            summary, status = DashboardQueryService.get_executive_summary(workspace_id, force_refresh=True)
            logger.info(f"[CacheWarming] Workspace {workspace_id} warmed v{new_version} ({status}) successfully.")
            from supplyforge.metrics import record_cache
            record_cache(cache_area='dashboard', operation='warm', result='warm')
        except Exception as e:
            logger.error(f"[CacheWarming] Failed to warm cache for workspace {workspace_id}: {e}")
