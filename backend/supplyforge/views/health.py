import os
import logging
from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from supplyforge.models import Product, SlowMovingRiskAssessment, Order

logger = logging.getLogger(__name__)


def _check_mysql():
    """Lightweight MySQL connectivity check using SELECT 1;"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            if row and row[0] == 1:
                return "healthy"
        return "unhealthy"
    except Exception as e:
        logger.error(f"[HealthCheck] MySQL check failed: {e}")
        return "unhealthy"


def _check_redis():
    """Lightweight Redis PING check with 1s timeout."""
    try:
        import redis
        redis_url = getattr(settings, 'REDIS_CACHE_URL', None) or getattr(settings, 'CELERY_BROKER_URL', None)
        if not redis_url or not (redis_url.startswith('redis://') or redis_url.startswith('rediss://')):
            redis_host = getattr(settings, 'REDIS_HOST', '127.0.0.1')
            redis_port = getattr(settings, 'REDIS_PORT', '6379')
            redis_url = f"redis://{redis_host}:{redis_port}/0"

        r = redis.Redis.from_url(redis_url, socket_timeout=1.0)
        if r.ping():
            return "healthy"
        return "unhealthy"
    except Exception as e:
        logger.warning(f"[HealthCheck] Redis check failed: {e}")
        return "unhealthy"


def _check_celery():
    """Lightweight Celery worker availability check."""
    try:
        from config.celery import app as celery_app
        i = celery_app.control.inspect(timeout=1.0)
        ping_res = i.ping()
        if ping_res:
            return "healthy"
        return "unhealthy"
    except Exception as e:
        logger.warning(f"[HealthCheck] Celery check failed: {e}")
        return "unhealthy"


@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    """Legacy ping check endpoint."""
    return Response({"service": "supplyforge-ai", "status": "ok"})


@api_view(['GET', 'HEAD'])
@permission_classes([AllowAny])
def health_live(request):
    """
    GET/HEAD /health/live, /api/v1/health/live & / (Liveness Probe for Render & Load Balancers)
    """
    return Response({
        "status": "ok",
        "app": "SupplyForge AI Backend"
    }, status=200)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_ready(request):
    """
    GET /health/ready & /api/v1/health/ready (Readiness Probe)
    Validates critical dependencies: MySQL and Redis.
    Returns 200 OK when ready, 503 Service Unavailable when critical dependency fails.
    """
    mysql_status = _check_mysql()
    redis_status = _check_redis()

    is_ready = (mysql_status == "healthy") and (redis_status == "healthy")
    overall_status = "ready" if is_ready else "not_ready"
    http_code = 200 if is_ready else 503

    # These are intentionally coarse statuses: health probes must aid
    # operations without exposing host names, URLs, credentials or topology.
    return Response({
        "status": overall_status,
        "database": "ok" if mysql_status == "healthy" else "unavailable",
        "redis": "ok" if redis_status == "healthy" else "unavailable",
    }, status=http_code)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_dependencies(request):
    """
    GET /health/dependencies & /api/v1/health/dependencies (Dependency Health Check)
    Detailed diagnostic status breakdown for MySQL, Redis, and Celery.
    Returns 200 OK when all dependencies are healthy, 503 when any dependency is degraded/unhealthy.
    """
    mysql_status = _check_mysql()
    redis_status = _check_redis()
    celery_status = _check_celery()

    all_healthy = (mysql_status == "healthy") and (redis_status == "healthy") and (celery_status == "healthy")
    overall_status = "healthy" if all_healthy else "degraded"
    http_code = 200 if all_healthy else 503

    return Response({
        "status": overall_status,
        "dependencies": {
            "mysql": {
                "status": mysql_status
            },
            "redis": {
                "status": redis_status
            },
            "celery": {
                "status": celery_status
            }
        }
    }, status=http_code)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def health_celery(request):
    """
    GET/POST /api/v1/health/celery (Legacy Celery Worker Dispatch Check)
    """
    worker_type = request.GET.get('worker_type') or 'data_worker'
    allowed_worker_types = {
        'data_worker',
        'ml_worker',
        'decision_worker',
        'integration_worker',
    }
    if worker_type not in allowed_worker_types:
        return Response({
            "status": "error",
            "error": "worker_type không hợp lệ.",
            "allowed_worker_types": sorted(allowed_worker_types),
        }, status=400)
    try:
        from supplyforge.tasks import health_check_task
        # Route the probe to the worker class being checked. Merely queuing a
        # task on the default queue would prove only that some worker exists.
        task_res = health_check_task.apply_async(args=[worker_type], queue=worker_type)
        return Response({
            "status": "ok",
            "celery_broker": "connected",
            "task_id": str(task_res.id),
            "worker_type": worker_type,
            "architecture": {
                "flow": "API -> Redis -> Celery",
                "workers": ["Data Worker", "ML Worker", "Decision Worker", "Integration Worker"]
            }
        }, status=200)
    except Exception as e:
        logger.error(f"[CeleryHealthCheck] Failed to dispatch health check task: {e}")
        return Response({
            "status": "error",
            "celery_broker": "disconnected",
            "architecture": {
                "flow": "API -> Redis -> Celery",
                "workers": ["Data Worker", "ML Worker", "Decision Worker", "Integration Worker"]
            }
        }, status=503)


@api_view(['GET'])
def check_data(request):
    if not (
        getattr(request, 'tenant_context_validated', False)
        and getattr(request, 'user_id', None)
        and getattr(request, 'workspace_id', None)
    ):
        return Response({
            "error": "Yêu cầu cần Authorization Bearer token.",
            "code": "UNAUTHENTICATED",
        }, status=401)

    user_id = str(request.user_id)
    p_count = Product.objects.filter(user_id=user_id).count()
    r_count = SlowMovingRiskAssessment.objects.filter(
        session__workspace_id=request.workspace_id
    ).count()
    o_count = Order.objects.filter(user_id=user_id).count()

    has_data = (p_count > 0) or (r_count > 0) or (o_count > 0)
    return Response({
        "hasData": has_data,
        "count": p_count,
        "assessment_count": r_count,
        "order_count": o_count
    })
