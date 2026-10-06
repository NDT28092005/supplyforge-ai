"""
SupplyForge AI — High-Speed Query Service REST APIs
===================================================
Endpoints returning cached aggregated responses with latency telemetry headers.
"""

import time
import logging
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from supplyforge.services.query_service import DashboardQueryService
from supplyforge.services.cache_policy import CachePolicy
from supplyforge.services.cache_warming_service import CacheWarmingService

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['GET'])
def get_cached_dashboard_summary(request):
    """
    GET /api/v2/query/dashboard-summary
    High-speed cached Executive Dashboard Summary.
    SLO Target: Cache HIT P95 < 30ms.
    """
    start_time = time.time()
    workspace_id = request.GET.get('workspaceId') or request.GET.get('workspace_id') or getattr(request, 'workspace_id', 1)

    summary, cache_status = DashboardQueryService.get_executive_summary(int(workspace_id), force_refresh=False)
    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    res = Response(summary, status=status.HTTP_200_OK)
    res['X-Cache-Status'] = cache_status
    res['X-Cache-Version'] = summary.get('cacheVersion', '1')
    res['X-Response-Time-ms'] = str(elapsed_ms)
    return res


@csrf_exempt
@api_view(['POST'])
def refresh_workspace_cache(request):
    """
    POST /api/v2/query/cache-refresh (Protected Endpoint)
    Manually triggers cache invalidation & warming for workspace.
    Requires ADMIN/OWNER permissions.
    """
    role = getattr(request, 'user_role', 'ADMIN')
    if role not in ['ADMIN', 'OWNER', 'MANAGER']:
        return Response({'error': 'Bạn không có quyền làm mới bộ nhớ đệm.'}, status=status.HTTP_403_FORBIDDEN)

    workspace_id = request.data.get('workspaceId') or request.data.get('workspace_id') or getattr(request, 'workspace_id', 1)

    CacheWarmingService.warm_workspace_cache(int(workspace_id))
    new_version = str(CachePolicy.get_workspace_version(int(workspace_id)))

    res = Response({
        'status': 'SUCCESS',
        'message': f'Đã làm mới bộ nhớ đệm cho Workspace {workspace_id}.',
        'newCacheVersion': new_version
    }, status=status.HTTP_200_OK)
    res['X-Cache-Status'] = 'REFRESHED'
    res['X-Cache-Version'] = new_version
    return res

