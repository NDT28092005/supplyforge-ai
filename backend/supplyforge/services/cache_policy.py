"""
SupplyForge AI — Cache Policy & Versioning Architecture
=========================================================
Centralized Cache Policies, TTLs, Stampede Lock Timeouts, and Workspace Cache Versioning.
"""

from django.core.cache import cache


class CachePolicy:
    TTL_DASHBOARD_SUMMARY = 86400  # 24 hours
    TTL_RISK_SUMMARY = 86400       # 24 hours
    TTL_CAPITAL_SUMMARY = 86400    # 24 hours
    TTL_DECISION_SUMMARY = 43200   # 12 hours
    TTL_PAGINATED_LIST = 3600      # 1 hour
    STAMPEDE_LOCK_TTL = 10         # 10 seconds

    @staticmethod
    def get_workspace_version(workspace_id: int) -> int:
        ver_key = f"sf:v2:ws:{workspace_id}:cache_version"
        try:
            ver = cache.get(ver_key)
            if ver is None:
                cache.set(ver_key, 1, timeout=None)
                return 1
            return int(ver)
        except Exception:
            return 1

    @staticmethod
    def bump_workspace_version(workspace_id: int) -> int:
        ver_key = f"sf:v2:ws:{workspace_id}:cache_version"
        try:
            current = cache.get(ver_key)
            if current is None:
                cache.set(ver_key, 2, timeout=None)
                return 2
            return cache.incr(ver_key)
        except Exception:
            try:
                cache.set(ver_key, 2, timeout=None)
                return 2
            except Exception:
                return 2
